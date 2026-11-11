"""UBL 2.1 XRechnung 3.0 generator for a deliberately limited domestic profile."""

from __future__ import annotations

import base64
import hashlib
import json
import xml.etree.ElementTree as ET

import httpx
from fastapi import HTTPException

from app.config import get_settings
from app.finance.schemas import EntityInput, InvoiceInput, Party, money, totals

CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
PROFILE = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
RULES = "XRechnung 3.0.2 / 2026-08-31"
ET.register_namespace("cbc", CBC)
ET.register_namespace("cac", CAC)


def digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def add(parent: ET.Element, name: str, value: object = None, **attrs: str) -> ET.Element:
    prefix, local = name.split(":")
    element = ET.SubElement(parent, f"{{{CBC if prefix == 'cbc' else CAC}}}{local}", attrs)
    if value is not None:
        element.text = str(value)
    return element


def party(root: ET.Element, name: str, data: Party, seller: EntityInput | None = None) -> None:
    p = add(add(root, name), "cac:Party")
    add(p, "cbc:EndpointID", data.email, schemeID="EM")
    address = add(p, "cac:PostalAddress")
    add(address, "cbc:StreetName", data.street)
    add(address, "cbc:CityName", data.city)
    add(address, "cbc:PostalZone", data.postal_code)
    add(add(address, "cac:Country"), "cbc:IdentificationCode", data.country)
    if seller:
        tax = add(p, "cac:PartyTaxScheme")
        add(tax, "cbc:CompanyID", seller.vat_id)
        add(add(tax, "cac:TaxScheme"), "cbc:ID", "VAT")
    add(add(p, "cac:PartyLegalEntity"), "cbc:RegistrationName", data.name)
    if seller:
        contact = add(p, "cac:Contact")
        add(contact, "cbc:Name", seller.contact_name)
        add(contact, "cbc:Telephone", seller.phone)
        add(contact, "cbc:ElectronicMail", seller.email)


def generate(payload: dict[str, object], number: str, credit: bool = False) -> bytes:
    data = InvoiceInput.model_validate(payload["invoice"])
    seller = EntityInput.model_validate(payload["seller"])
    amount = totals(data)
    root_name = "CreditNote" if credit else "Invoice"
    root = ET.Element(
        root_name, xmlns=f"urn:oasis:names:specification:ubl:schema:xsd:{root_name}-2"
    )
    add(root, "cbc:CustomizationID", PROFILE)
    add(root, "cbc:ProfileID", "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0")
    add(root, "cbc:ID", number)
    add(root, "cbc:IssueDate", data.issue_date)
    if not credit:
        add(root, "cbc:DueDate", data.due_date)
    add(
        root,
        "cbc:CreditNoteTypeCode" if credit else "cbc:InvoiceTypeCode",
        "381" if credit else "380",
    )
    add(root, "cbc:DocumentCurrencyCode", "EUR")
    add(root, "cbc:BuyerReference", data.buyer_reference)
    period = add(root, "cac:InvoicePeriod")
    add(period, "cbc:StartDate", data.service_start)
    add(period, "cbc:EndDate", data.service_end)
    if credit:
        reference = add(add(root, "cac:BillingReference"), "cac:InvoiceDocumentReference")
        add(reference, "cbc:ID", payload["original_number"])
        add(reference, "cbc:IssueDate", payload["original_date"])
    party(root, "cac:AccountingSupplierParty", seller, seller)
    party(root, "cac:AccountingCustomerParty", data.buyer)
    payment = add(root, "cac:PaymentMeans")
    add(payment, "cbc:PaymentMeansCode", "58")
    add(add(payment, "cac:PayeeFinancialAccount"), "cbc:ID", seller.iban)
    add(
        add(root, "cac:PaymentTerms"),
        "cbc:Note",
        (
            f"Vollständige Stornierung der Rechnung {payload['original_number']}. "
            "Etwaige Zahlungen sind separat abzugleichen."
            if credit
            else f"Zahlbar bis {data.due_date.isoformat()} ohne Abzug."
        ),
    )
    tax = add(root, "cac:TaxTotal")
    add(tax, "cbc:TaxAmount", amount["tax"], currencyID="EUR")
    subtotal = add(tax, "cac:TaxSubtotal")
    add(subtotal, "cbc:TaxableAmount", amount["net"], currencyID="EUR")
    add(subtotal, "cbc:TaxAmount", amount["tax"], currencyID="EUR")
    category = add(subtotal, "cac:TaxCategory")
    add(category, "cbc:ID", "S")
    add(category, "cbc:Percent", "19")
    add(add(category, "cac:TaxScheme"), "cbc:ID", "VAT")
    total = add(root, "cac:LegalMonetaryTotal")
    for key, value in (
        ("LineExtensionAmount", amount["net"]),
        ("TaxExclusiveAmount", amount["net"]),
        ("TaxInclusiveAmount", amount["gross"]),
        ("PayableAmount", amount["gross"]),
    ):
        add(total, f"cbc:{key}", money(value), currencyID="EUR")
    for i, line in enumerate(data.lines, 1):
        entry = add(root, "cac:CreditNoteLine" if credit else "cac:InvoiceLine")
        add(entry, "cbc:ID", i)
        add(
            entry,
            "cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity",
            format(line.quantity, "f"),
            unitCode=line.unit,
        )
        add(
            entry,
            "cbc:LineExtensionAmount",
            money(line.quantity * line.unit_price),
            currencyID="EUR",
        )
        item = add(entry, "cac:Item")
        add(item, "cbc:Name", line.description)
        category = add(item, "cac:ClassifiedTaxCategory")
        add(category, "cbc:ID", "S")
        add(category, "cbc:Percent", "19")
        add(add(category, "cac:TaxScheme"), "cbc:ID", "VAT")
        add(
            add(entry, "cac:Price"),
            "cbc:PriceAmount",
            format(line.unit_price, "f"),
            currencyID="EUR",
        )
    return bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


async def validate(xml: bytes) -> tuple[dict[str, object], bytes]:
    url = get_settings().invoice_validator_url
    if not url:
        raise HTTPException(
            503, "XRechnungsprüfung ist nicht eingerichtet. Es wurde keine Rechnung finalisiert."
        )
    if len(xml) > 512_000:
        raise HTTPException(422, "Rechnung überschreitet das unterstützte Dateilimit.")
    try:
        async with (
            httpx.AsyncClient(timeout=35, follow_redirects=False, trust_env=False) as client,
            client.stream(
                "POST",
                url.rstrip("/") + "/invoice.xml",
                content=xml,
                headers={"Content-Type": "application/xml"},
            ) as response,
        ):
            if response.status_code not in (200, 406):
                raise HTTPException(503, "Die Rechnungsprüfung ist momentan nicht verfügbar.")
            report = bytearray()
            async for chunk in response.aiter_bytes():
                report.extend(chunk)
                if len(report) > 4_000_000:
                    raise HTTPException(503, "Prüfbericht überschreitet das unterstützte Limit.")
            code = response.status_code
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Die Rechnungsprüfung konnte nicht abgeschlossen werden.") from exc
    raw = bytes(report)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise HTTPException(503, "Ungültiger Prüfbericht.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise HTTPException(503, "Der Prüfdienst lieferte keinen XML-Prüfbericht.") from exc
    ns = {"v": "http://www.xoev.de/de/validator/varl/1"}
    if (
        root.tag != f"{{{ns['v']}}}report"
        or root.findtext("v:engine/v:name", namespaces=ns) != "KoSIT Validator 1.6.3"
    ):
        raise HTTPException(503, "Unbekannter Prüfdienst oder unerwartete Validatorversion.")
    accepted = root.find("v:assessment/v:accept", ns) is not None
    if (code == 200) != accepted:
        raise HTTPException(503, "Widersprüchliche Antwort der Rechnungsprüfung.")
    checksum = root.findtext("v:documentIdentification/v:documentHash/v:hashValue", namespaces=ns)
    algorithm = root.findtext(
        "v:documentIdentification/v:documentHash/v:hashAlgorithm", namespaces=ns
    )
    if (
        algorithm != "SHA-256"
        or checksum != base64.b64encode(hashlib.sha256(xml).digest()).decode()
    ):
        raise HTTPException(503, "Prüfbericht gehört nicht zu diesem Rechnungsartefakt.")
    errors = list(
        dict.fromkeys(
            e.attrib.get("code", e.attrib.get("id", "unbekannt"))
            for e in root.iter()
            if (e.tag.endswith("}failed-assert") and "id" in e.attrib)
            or (e.tag == f"{{{ns['v']}}}message" and e.attrib.get("level") == "error")
        )
    )[:50]
    return {
        "status": "valid" if code == 200 else "invalid",
        "validator": "KoSIT 1.6.3",
        "rules": RULES,
        "errors": errors,
        "sha256": hashlib.sha256(xml).hexdigest(),
    }, raw
