"""Financial invariants, permissions, immutable artifacts and real KoSIT compatibility."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.config import get_settings
from app.database import get_db
from app.finance import xrechnung
from app.finance.models import (
    BilledService,
    FinanceEvent,
    FinanceGrant,
    Invoice,
    InvoiceSequence,
    LegalEntity,
)
from app.finance.schemas import EntityInput, InvoiceInput, totals
from app.main import app
from app.security import create_access_token
from app.users.models import User
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.utils import auth_headers


def seller() -> dict:
    return {
        "name": "Synthetische Personal GmbH",
        "street": "Teststraße 1",
        "postal_code": "10115",
        "city": "Berlin",
        "email": "finance@example.com",
        "vat_id": "DE123456789",
        "contact_name": "Testkontakt",
        "phone": "+49 30 123456",
        "iban": "DE89370400440532013000",
        "invoice_prefix": "RE",
        "four_eyes": True,
    }


def draft() -> dict:
    return {
        "buyer": {
            "name": "Testkunde GmbH",
            "street": "Testweg 2",
            "postal_code": "10117",
            "city": "Berlin",
            "email": "buyer@example.com",
        },
        "buyer_reference": "TEST-REFERENZ",
        "service_reference": "AUFTRAG-2026-09",
        "issue_date": "2026-09-10",
        "due_date": "2026-09-24",
        "service_start": "2026-09-01",
        "service_end": "2026-09-10",
        "lines": [
            {
                "description": "Personalbereitstellung & Test <Position>",
                "quantity": "8.5",
                "unit_price": "32.75",
            }
        ],
    }


def test_decimal_calculation_uses_line_then_category_rounding() -> None:
    assert totals(InvoiceInput.model_validate(draft())) == {
        "net": Decimal("278.38"),
        "tax": Decimal("52.89"),
        "gross": Decimal("331.27"),
    }
    data = draft()
    data["lines"] = [{"description": "Pauschale", "quantity": "1", "unit_price": "0.03"}] * 2
    assert totals(InvoiceInput.model_validate(data)) == {
        "net": Decimal("0.06"),
        "tax": Decimal("0.01"),
        "gross": Decimal("0.07"),
    }
    data["lines"] = [{"description": "Pauschale", "quantity": "3", "unit_price": "0.335"}]
    assert totals(InvoiceInput.model_validate(data))["net"] == Decimal("1.01")


@pytest.mark.parametrize(
    "patch",
    [
        {"currency": "USD"},
        {"due_date": "2026-01-01"},
        {"service_end": "2025-01-01"},
        {"lines": []},
        {"tenant_id": str(uuid.uuid4())},
    ],
)
def test_invoice_rejects_unsupported_or_inconsistent_payload(patch: dict) -> None:
    with pytest.raises(ValidationError):
        InvoiceInput.model_validate({**draft(), **patch})


@pytest.mark.parametrize(
    "patch",
    [
        {"quantity": "NaN"},
        {"quantity": "0"},
        {"unit_price": "-1"},
        {"vat_rate": 0},
        {"vat_rate": 7},
        {"description": "bad\x00text"},
        {"unit_price": "0.000001", "quantity": "0.0001"},
    ],
)
def test_invalid_lines_are_never_silently_coerced_to_taxable_invoices(patch: dict) -> None:
    data = draft()
    data["lines"][0].update(patch)
    with pytest.raises(ValidationError):
        InvoiceInput.model_validate(data)


def test_issuer_requires_supported_country_vat_and_valid_iban() -> None:
    assert EntityInput.model_validate(seller()).iban == "DE89370400440532013000"
    for patch in (
        {"iban": "DE00370400440532013000"},
        {"vat_id": "123"},
        {"country": "FR"},
        {"invoice_prefix": '../evil"'},
        {"email": "not-an-email"},
    ):
        with pytest.raises(ValidationError):
            EntityInput.model_validate({**seller(), **patch})


@pytest.fixture
async def finance_workspace(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> tuple[dict, dict, dict, HRWorkspace]:
    hr_workspace.hr.role = "admin"
    reviewer = User(
        email=f"finance-review-{uuid.uuid4().hex}@example.com",
        hashed_password="unused",
        full_name="Finanzprüfung",
        role="recruiter",
        tenant_id=hr_workspace.hr.tenant_id,
    )
    db_session.add(reviewer)
    await db_session.flush()
    entity = body(
        await client.post("/finance/entities", headers=hr_workspace.headers(), json=seller()), 201
    )
    headers = auth_headers(create_access_token({"sub": reviewer.email}))
    return (
        entity,
        {"id": str(reviewer.id), "headers": headers},
        hr_workspace.headers(),
        hr_workspace,
    )


async def grant(
    client: AsyncClient,
    entity: dict,
    owner: dict,
    reviewer: dict,
    permissions: list[str],
    version: int = 0,
) -> dict:
    return body(
        await client.put(
            f"/finance/entities/{entity['id']}/grants",
            headers=owner,
            json={"user_id": reviewer["id"], "permissions": permissions, "version": version},
        )
    )


async def create(client: AsyncClient, entity: dict, owner: dict, **overrides: object) -> dict:
    return body(
        await client.post(
            f"/finance/entities/{entity['id']}/invoices",
            headers=owner,
            json={**draft(), "request_key": str(uuid.uuid4()), **overrides},
        ),
        201,
    )


async def decision(
    client: AsyncClient, invoice: dict, headers: dict, action: str, status: int = 200
) -> dict:
    return body(
        await client.post(
            f"/finance/invoices/{invoice['id']}/{action}",
            headers=headers,
            json={"version": invoice["version"], "note": "Synthetischer fachlicher Prüfvermerk"},
        ),
        status,
    )


@pytest.fixture
def format_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(xml: bytes) -> tuple[dict, bytes]:
        return {
            "status": "valid",
            "rules": xrechnung.RULES,
            "validator": "KoSIT 1.6.3",
            "errors": [],
            "sha256": hashlib.sha256(xml).hexdigest(),
        }, b"<synthetic-test-report/>"

    monkeypatch.setattr(xrechnung, "validate", fake)


async def approved(
    client: AsyncClient, entity: dict, owner: dict, reviewer: dict, **overrides: object
) -> dict:
    invoice = await create(client, entity, owner, **overrides)
    invoice = await decision(client, invoice, owner, "submit")
    return await decision(client, invoice, reviewer["headers"], "approve")


async def test_finance_workflow_permissions_and_immutable_download(
    client: AsyncClient, finance_workspace: tuple, format_valid: None
) -> None:
    entity, reviewer, owner, workspace = finance_workspace
    assert body(await client.get("/finance/entities", headers=reviewer["headers"])) == []
    invoice = await create(client, entity, owner)
    assert invoice["total"] == "331.27" and invoice["number"] is None
    assert (
        await client.get(f"/finance/invoices/{invoice['id']}", headers=reviewer["headers"])
    ).status_code == 403
    assert (
        await client.get(
            f"/finance/invoices/{invoice['id']}", headers=workspace.headers("other_hr")
        )
    ).status_code == 404
    assert (
        await client.get("/finance/entities", headers=workspace.headers("worker"))
    ).status_code == 403
    invoice = await decision(client, invoice, owner, "submit")
    await decision(client, invoice, owner, "approve", 403)
    await decision(client, invoice, reviewer["headers"], "approve", 403)
    await grant(client, entity, owner, reviewer, ["approve"])
    invoice = await decision(client, invoice, reviewer["headers"], "approve")
    initial = invoice
    final = await decision(client, invoice, owner, "finalize")
    assert final["number"] == "RE-2026-000001" and final["status"] == "finalized"
    retry = await decision(client, initial, owner, "finalize")
    assert retry["number"] == final["number"] and retry["version"] == final["version"]
    export = await client.get(f"/finance/invoices/{final['id']}/download", headers=owner)
    assert (
        export.status_code == 200
        and hashlib.sha256(export.content).hexdigest() == final["artifact_hash"]
    )
    assert b"&amp; Test &lt;Position&gt;" in export.content
    assert export.headers["cache-control"] == "no-store"
    assert (
        await client.get(f"/finance/invoices/{final['id']}/download", headers=reviewer["headers"])
    ).status_code == 403
    assert (
        await client.put(
            f"/finance/invoices/{final['id']}",
            headers=owner,
            json={**draft(), "version": final["version"]},
        )
    ).status_code == 409
    await decision(client, final, owner, "return", 409)
    history = body(await client.get(f"/finance/invoices/{final['id']}/events", headers=owner))
    assert [e["action"] for e in history] == ["draft_created", "submitted", "approved", "finalized"]


async def test_draft_idempotency_update_versions_and_scoped_grants(
    client: AsyncClient, finance_workspace: tuple
) -> None:
    entity, reviewer, owner, workspace = finance_workspace
    key = str(uuid.uuid4())
    payload = {**draft(), "request_key": key}
    url = f"/finance/entities/{entity['id']}/invoices"
    invoice = body(await client.post(url, headers=owner, json=payload), 201)
    assert body(await client.post(url, headers=owner, json=payload))["id"] == invoice["id"]
    assert (
        await client.post(url, headers=owner, json={**payload, "service_reference": "OTHER"})
    ).status_code == 409
    edit = {**draft(), "version": invoice["version"], "service_reference": "UPDATED"}
    saved = body(await client.put(f"/finance/invoices/{invoice['id']}", headers=owner, json=edit))
    assert saved["payload_hash"] != invoice["payload_hash"]
    assert (
        await client.put(f"/finance/invoices/{invoice['id']}", headers=owner, json=edit)
    ).status_code == 409
    assert (
        await client.get(f"/finance/invoices/{invoice['id']}/download", headers=owner)
    ).status_code == 409
    members = body(await client.get(f"/finance/entities/{entity['id']}/grants", headers=owner))
    assert reviewer["id"] in [g["user_id"] for g in members]
    assert (
        await client.put(
            f"/finance/entities/{entity['id']}/grants",
            headers=owner,
            json={"user_id": str(workspace.other_hr.id), "permissions": ["read"], "version": 0},
        )
    ).status_code == 404
    g = await grant(client, entity, owner, reviewer, ["read", "export"])
    assert g["version"] == 1
    assert (
        await client.put(
            f"/finance/entities/{entity['id']}/grants",
            headers=owner,
            json={"user_id": reviewer["id"], "permissions": [], "version": 0},
        )
    ).status_code == 409
    await grant(client, entity, owner, reviewer, [], 1)
    assert body(await client.get("/finance/entities", headers=reviewer["headers"])) == []


async def test_issuer_changes_and_revoked_approver_block_finalization(
    client: AsyncClient, finance_workspace: tuple, format_valid: None
) -> None:
    entity, reviewer, owner, _ = finance_workspace
    await grant(client, entity, owner, reviewer, ["approve"])
    invoice = await approved(client, entity, owner, reviewer)
    changed = {**seller(), "version": 1, "street": "Geänderter Testweg 9"}
    body(await client.put(f"/finance/entities/{entity['id']}", headers=owner, json=changed))
    await decision(client, invoice, owner, "finalize", 409)
    invoice = await decision(client, invoice, owner, "return")
    await decision(client, invoice, owner, "submit", 409)
    invoice = body(
        await client.put(
            f"/finance/invoices/{invoice['id']}",
            headers=owner,
            json={**draft(), "version": invoice["version"]},
        )
    )
    invoice = await decision(client, invoice, owner, "submit")
    invoice = await decision(client, invoice, reviewer["headers"], "approve")
    await grant(client, entity, owner, reviewer, [], 1)
    await decision(client, invoice, owner, "finalize", 409)
    await grant(client, entity, owner, reviewer, ["approve"], 2)
    await decision(client, invoice, owner, "finalize", 409)
    invoice = await decision(client, invoice, owner, "return")
    invoice = await decision(client, invoice, owner, "submit")
    invoice = await decision(client, invoice, reviewer["headers"], "approve")
    final = await decision(client, invoice, owner, "finalize")
    assert final["payload"]["seller"]["street"] == changed["street"]
    assert (
        await client.put(
            f"/finance/entities/{entity['id']}",
            headers=owner,
            json={**changed, "version": 2, "invoice_prefix": "NEW"},
        )
    ).status_code == 409


async def test_failed_validation_keeps_number_available_and_duplicate_service_is_blocked(
    client: AsyncClient, finance_workspace: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    entity, reviewer, owner, _ = finance_workspace
    await grant(client, entity, owner, reviewer, ["approve"])
    invoice = await approved(client, entity, owner, reviewer)

    async def invalid(xml: bytes) -> tuple[dict, bytes]:
        return {"status": "invalid", "errors": ["BR-TEST"]}, b"<invalid/>"

    monkeypatch.setattr(xrechnung, "validate", invalid)
    failed = await decision(client, invoice, owner, "finalize")
    assert (
        failed["status"] == "approved"
        and failed["number"] is None
        and failed["artifact_hash"] is None
    )
    assert (
        await client.get(f"/finance/invoices/{invoice['id']}/download?report=true", headers=owner)
    ).content == b"<invalid/>"

    async def valid(xml: bytes) -> tuple[dict, bytes]:
        return {"status": "valid"}, b"<valid/>"

    monkeypatch.setattr(xrechnung, "validate", valid)
    final = await decision(client, failed, owner, "finalize")
    assert final["number"] == "RE-2026-000001"
    duplicate = await approved(client, entity, owner, reviewer)
    await decision(client, duplicate, owner, "finalize", 409)
    other = await approved(client, entity, owner, reviewer, service_reference="AUFTRAG-2026-10")
    assert (await decision(client, other, owner, "finalize"))["number"] == "RE-2026-000002"


async def test_full_credit_preserves_original_and_requires_own_review(
    client: AsyncClient, finance_workspace: tuple, format_valid: None
) -> None:
    entity, reviewer, owner, _ = finance_workspace
    await grant(client, entity, owner, reviewer, ["approve"])
    invoice = await approved(client, entity, owner, reviewer)
    invoice = await decision(client, invoice, owner, "finalize")
    original = (
        await client.get(f"/finance/invoices/{invoice['id']}/download", headers=owner)
    ).content
    data = {
        "version": invoice["version"],
        "note": "Testauftrag vollständig aufgehoben",
        "issue_date": "2026-09-11",
        "request_key": str(uuid.uuid4()),
    }
    url = f"/finance/invoices/{invoice['id']}/credit"
    assert (
        await client.post(url, headers=owner, json={**data, "issue_date": "2101-01-01"})
    ).status_code == 422
    credit = body(await client.post(url, headers=owner, json=data), 201)
    assert body(await client.post(url, headers=owner, json=data))["id"] == credit["id"]
    assert (
        await client.post(url, headers=owner, json={**data, "request_key": str(uuid.uuid4())})
    ).status_code == 409
    assert (
        credit["total"] == invoice["total"]
        and credit["payload"]["original_number"] == invoice["number"]
    )
    credit = await decision(client, credit, owner, "submit")
    await decision(client, credit, owner, "approve", 403)
    credit = await decision(client, credit, reviewer["headers"], "approve")
    credit = await decision(client, credit, owner, "finalize")
    assert credit["number"] == "RE-2026-000002"
    assert (
        body(await client.get(f"/finance/invoices/{invoice['id']}", headers=owner))["status"]
        == "cancelled"
    )
    assert (
        await client.get(f"/finance/invoices/{invoice['id']}/download", headers=owner)
    ).content == original
    assert (
        b"CreditNote"
        in (await client.get(f"/finance/invoices/{credit['id']}/download", headers=owner)).content
    )
    assert (
        await client.post(
            f"/finance/invoices/{credit['id']}/credit",
            headers=owner,
            json={**data, "version": credit["version"], "request_key": str(uuid.uuid4())},
        )
    ).status_code == 409


async def test_self_review_is_explicit_and_still_needs_approval(
    client: AsyncClient, finance_workspace: tuple, format_valid: None
) -> None:
    entity, _, owner, _ = finance_workspace
    body(
        await client.put(
            f"/finance/entities/{entity['id']}",
            headers=owner,
            json={**seller(), "four_eyes": False, "version": 1},
        )
    )
    invoice = await create(client, entity, owner)
    await decision(client, invoice, owner, "finalize", 409)
    invoice = await decision(client, invoice, owner, "submit")
    invoice = await decision(client, invoice, owner, "approve")
    assert (await decision(client, invoice, owner, "finalize"))["status"] == "finalized"


async def test_payload_tampering_invalidates_approval(
    client: AsyncClient, finance_workspace: tuple, db_session: AsyncSession
) -> None:
    entity, reviewer, owner, _ = finance_workspace
    await grant(client, entity, owner, reviewer, ["approve"])
    invoice = await approved(client, entity, owner, reviewer)
    row = await db_session.scalar(select(Invoice).where(Invoice.id == uuid.UUID(invoice["id"])))
    row.payload = {**row.payload, "totals": {"gross": "0.01"}}
    await db_session.flush()
    await decision(client, invoice, owner, "finalize", 409)


async def test_reviewer_can_return_without_becoming_the_preparer(
    client: AsyncClient, finance_workspace: tuple
) -> None:
    entity, reviewer, owner, _ = finance_workspace
    await grant(client, entity, owner, reviewer, ["approve"])
    invoice = await create(client, entity, owner)
    preparer = invoice["prepared_by"]
    invoice = await decision(client, invoice, owner, "submit")
    invoice = await decision(client, invoice, reviewer["headers"], "return")
    assert invoice["prepared_by"] == preparer and invoice["status"] == "draft"
    assert (
        await client.put(
            f"/finance/invoices/{invoice['id']}",
            headers=reviewer["headers"],
            json={**draft(), "version": invoice["version"]},
        )
    ).status_code == 403
    invoice = await decision(client, invoice, owner, "submit")
    await decision(client, invoice, owner, "approve", 403)
    assert (await decision(client, invoice, reviewer["headers"], "approve"))["status"] == "approved"


async def test_real_kosit_accepts_invoice_and_credit_and_rejects_invalid_xml() -> None:
    if not get_settings().invoice_validator_url:
        pytest.skip("Real local KoSIT service is not configured in this environment")
    data = InvoiceInput.model_validate(draft())
    payload = {
        "seller": EntityInput.model_validate(seller()).model_dump(mode="json"),
        "invoice": data.model_dump(mode="json"),
        "original_number": "RE-2026-000001",
        "original_date": "2026-09-10",
    }
    for credit in (False, True):
        xml = xrechnung.generate(payload, "RE-2026-000002" if credit else "RE-2026-000001", credit)
        if credit:
            assert b"Zahlbar bis" not in xml
            assert b"Stornierung der Rechnung RE-2026-000001" in xml
        else:
            assert b"Zahlbar bis 2026-09-24" in xml
        result, report = await xrechnung.validate(xml)
        assert result["status"] == "valid" and result["sha256"] == hashlib.sha256(xml).hexdigest()
        assert b"KoSIT Validator 1.6.3" in report
    xml = xrechnung.generate(payload, "RE-2026-000003").replace(
        b"<cbc:BuyerReference>TEST-REFERENZ</cbc:BuyerReference>", b""
    )
    result, _ = await xrechnung.validate(xml)
    assert result["status"] == "invalid" and result["errors"]


@pytest.mark.parametrize(
    "mode",
    [
        "unavailable",
        "invalid_xml",
        "wrong_engine",
        "wrong_hash",
        "contradictory",
        "huge",
        "dtd",
        "timeout",
    ],
)
async def test_validator_fails_closed_on_untrustworthy_response(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(get_settings(), "invoice_validator_url", "http://local-test")
    xml = b"<invoice/>"
    checksum = base64.b64encode(hashlib.sha256(xml).digest()).decode()

    def respond(request: httpx.Request) -> httpx.Response:
        if mode == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        response = f'<report xmlns="http://www.xoev.de/de/validator/varl/1"><engine><name>{"other" if mode == "wrong_engine" else "KoSIT Validator 1.6.3"}</name></engine><documentIdentification><documentHash><hashAlgorithm>SHA-256</hashAlgorithm><hashValue>{"wrong" if mode == "wrong_hash" else checksum}</hashValue></documentHash></documentIdentification><assessment><accept/></assessment></report>'
        if mode == "invalid_xml":
            response = "not xml"
        if mode == "dtd":
            response = '<!DOCTYPE x [<!ENTITY bad "test">]>' + response
        if mode == "huge":
            response = "x" * 4_000_001
        return httpx.Response(
            503 if mode == "unavailable" else 406 if mode == "contradictory" else 200,
            content=response,
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        xrechnung.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(HTTPException) as exc:
        await xrechnung.validate(xml)
    assert exc.value.status_code == 503


async def test_missing_validator_and_oversize_input_are_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "invoice_validator_url", "")
    with pytest.raises(HTTPException) as exc:
        await xrechnung.validate(b"<invoice/>")
    assert exc.value.status_code == 503
    monkeypatch.setattr(get_settings(), "invoice_validator_url", "http://local-test")
    with pytest.raises(HTTPException) as exc:
        await xrechnung.validate(b"x" * 512_001)
    assert exc.value.status_code == 422


async def test_concurrent_retries_and_number_allocation_use_real_transactions(
    client: AsyncClient, format_valid: None
) -> None:
    # Separate committed test sessions exercise real PostgreSQL row locks.
    # All records remain in the isolated test schema and are removed below.
    tenant_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    email = f"concurrent-finance-{owner_id.hex}@example.com"
    old_dependency = app.dependency_overrides[get_db]

    async def committed_db():
        async with TestSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async with TestSessionLocal() as session:
        session.add(
            Customer(
                id=tenant_id, name="Concurrent finance test", slug=tenant_id.hex, status="active"
            )
        )
        await session.flush()
        session.add(
            User(
                id=owner_id,
                tenant_id=tenant_id,
                email=email,
                hashed_password="unused",
                full_name="Test Owner",
                role="admin",
            )
        )
        await session.commit()
    app.dependency_overrides[get_db] = committed_db
    headers = auth_headers(create_access_token({"sub": email}))
    try:
        entity = body(
            await client.post(
                "/finance/entities", headers=headers, json={**seller(), "four_eyes": False}
            ),
            201,
        )
        payload = {**draft(), "request_key": str(uuid.uuid4())}
        url = f"/finance/entities/{entity['id']}/invoices"
        attempts = await asyncio.gather(
            *(client.post(url, headers=headers, json=payload) for _ in range(2))
        )
        assert sorted(r.status_code for r in attempts) == [200, 201]
        assert attempts[0].json()["id"] == attempts[1].json()["id"]
        first = attempts[0].json()
        second = await create(client, entity, headers, service_reference="CONCURRENT-SECOND")
        ready = []
        for invoice in (first, second):
            invoice = await decision(client, invoice, headers, "submit")
            ready.append(await decision(client, invoice, headers, "approve"))
        results = await asyncio.gather(
            decision(client, ready[0], headers, "finalize"),
            decision(client, ready[1], headers, "finalize"),
            decision(client, ready[0], headers, "finalize"),
        )
        assert {r["number"] for r in results} == {"RE-2026-000001", "RE-2026-000002"}
        assert results[0]["number"] == results[2]["number"]
    finally:
        app.dependency_overrides[get_db] = old_dependency
        async with TestSessionLocal() as session:
            issuer_ids = select(LegalEntity.id).where(LegalEntity.tenant_id == tenant_id)
            for model in (FinanceEvent, BilledService, FinanceGrant, InvoiceSequence, Invoice):
                await session.execute(delete(model).where(model.entity_id.in_(issuer_ids)))
            await session.execute(delete(LegalEntity).where(LegalEntity.tenant_id == tenant_id))
            await session.execute(delete(User).where(User.id == owner_id))
            await session.execute(delete(Customer).where(Customer.id == tenant_id))
            await session.commit()
