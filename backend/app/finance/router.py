from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.branding import own_customer
from app.companies.workspace_access import workspace_admin, workspace_user
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
from app.finance.schemas import (
    PERMISSIONS,
    CreditInput,
    Decision,
    EntityInput,
    EntityRead,
    EntityUpdate,
    EventRead,
    GrantInput,
    GrantRead,
    InvoiceCreate,
    InvoiceInput,
    InvoiceRead,
    InvoiceUpdate,
    totals,
)
from app.users.models import User

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
HR = Annotated[User, Depends(workspace_user)]
Admin = Annotated[User, Depends(workspace_admin)]


async def access(
    db: AsyncSession, user: User, entity_id: uuid.UUID, permission: str = "read", lock: bool = False
) -> tuple[LegalEntity, list[str]]:
    await own_customer(db, user)
    query = (
        select(LegalEntity)
        .where(LegalEntity.id == entity_id, LegalEntity.tenant_id == user.tenant_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    entity = await db.scalar(query)
    if entity is None:
        raise HTTPException(404, "Rechnungsaussteller nicht gefunden.")
    grant = await db.scalar(
        select(FinanceGrant)
        .where(FinanceGrant.entity_id == entity.id, FinanceGrant.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    if grant is None or permission not in grant.permissions:
        raise HTTPException(
            403, "Für diesen Rechnungsaussteller fehlt das erforderliche Finanzrecht."
        )
    return entity, grant.permissions


async def owned_invoice(
    db: AsyncSession,
    user: User,
    invoice_id: uuid.UUID,
    permission: str = "read",
    lock: bool = False,
) -> tuple[Invoice, LegalEntity]:
    entity_id = await db.scalar(
        select(Invoice.entity_id).where(
            Invoice.id == invoice_id, Invoice.tenant_id == user.tenant_id
        )
    )
    if entity_id is None:
        raise HTTPException(404, "Rechnung nicht gefunden.")
    entity, _ = await access(db, user, entity_id, permission, lock)
    query = (
        select(Invoice).where(Invoice.id == invoice_id).execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    invoice = (await db.scalars(query)).one()
    return invoice, entity


def entity_read(entity: LegalEntity, permissions: list[str]) -> EntityRead:
    return EntityRead(**entity.data, id=entity.id, version=entity.version, permissions=permissions)


def record(
    db: AsyncSession,
    entity: LegalEntity,
    user: User,
    action: str,
    note: str = "",
    invoice: Invoice | None = None,
) -> None:
    db.add(
        FinanceEvent(
            created_at=datetime.now(UTC),
            entity_id=entity.id,
            invoice_id=invoice.id if invoice else None,
            actor_id=user.id,
            action=action,
            note=note,
        )
    )


def version(invoice: Invoice, data: Decision | InvoiceUpdate) -> None:
    if invoice.version != data.version:
        raise HTTPException(409, "Rechnung wurde geändert. Bitte neu laden und prüfen.")


def current_entity(invoice: Invoice, entity: LegalEntity) -> None:
    if invoice.entity_version != entity.version:
        raise HTTPException(
            409,
            "Ausstellerdaten wurden geändert. Rechnung zur Bearbeitung zurückgeben und erneut speichern.",
        )


def set_payload(invoice: Invoice, entity: LegalEntity, data: InvoiceInput, user: User) -> None:
    invoice.payload = {
        "seller": entity.data,
        "invoice": data.model_dump(mode="json"),
        "totals": {k: str(v) for k, v in totals(data).items()},
    }
    invoice.payload_hash = xrechnung.digest(invoice.payload)
    invoice.entity_version = entity.version
    invoice.total = totals(data)["gross"]
    invoice.issue_date = data.issue_date
    invoice.buyer_name = data.buyer.name
    invoice.service_reference = data.service_reference
    invoice.prepared_by = user.id
    invoice.approved_by = None
    invoice.approved_grant_version = None
    invoice.validation = None
    invoice.validation_report = None


@router.get(
    "/entities",
    response_model=list[EntityRead],
    status_code=200,
    summary="Freigegebene Rechnungsaussteller",
)
async def entities(user: HR, db: DB, response: Response) -> list[EntityRead]:
    await own_customer(db, user)
    response.headers["Cache-Control"] = "no-store"
    rows = (
        await db.execute(
            select(LegalEntity, FinanceGrant.permissions)
            .join(FinanceGrant, FinanceGrant.entity_id == LegalEntity.id)
            .where(LegalEntity.tenant_id == user.tenant_id, FinanceGrant.user_id == user.id)
            .order_by(LegalEntity.name)
        )
    ).all()
    return [entity_read(e, p) for e, p in rows if "read" in p]


@router.post(
    "/entities",
    response_model=EntityRead,
    status_code=201,
    summary="Rechnungsaussteller und eigene Finanzverwaltung anlegen",
)
async def create_entity(data: EntityInput, user: Admin, db: DB) -> EntityRead:
    await own_customer(db, user)
    entity = LegalEntity(
        tenant_id=user.tenant_id, name=data.name, data=data.model_dump(mode="json")
    )
    db.add(entity)
    await db.flush()
    db.add(FinanceGrant(entity_id=entity.id, user_id=user.id, permissions=PERMISSIONS))
    record(db, entity, user, "entity_created")
    await db.flush()
    return entity_read(entity, PERMISSIONS)


@router.put(
    "/entities/{entity_id}",
    response_model=EntityRead,
    status_code=200,
    summary="Ausstellerdaten versioniert ändern",
)
async def update_entity(entity_id: uuid.UUID, data: EntityUpdate, user: HR, db: DB) -> EntityRead:
    entity, permissions = await access(db, user, entity_id, "manage", True)
    if entity.version != data.version:
        raise HTTPException(409, "Ausstellerdaten wurden geändert. Bitte neu laden.")
    if entity.data["invoice_prefix"] != data.invoice_prefix and await db.scalar(
        select(Invoice.id)
        .where(Invoice.entity_id == entity_id, Invoice.number.is_not(None))
        .limit(1)
    ):
        raise HTTPException(409, "Ein verwendetes Rechnungspräfix kann nicht geändert werden.")
    entity.data = data.model_dump(mode="json", exclude={"version"})
    entity.name = data.name
    entity.version += 1
    record(db, entity, user, "entity_updated", f"Version {entity.version}")
    await db.flush()
    return entity_read(entity, permissions)


@router.get(
    "/entities/{entity_id}/grants",
    response_model=list[GrantRead],
    status_code=200,
    summary="Finanzrechte der eigenen Firmenkollegen",
)
async def grants(entity_id: uuid.UUID, user: HR, db: DB) -> list[GrantRead]:
    await access(db, user, entity_id, "manage")
    people = (
        await db.scalars(
            select(User)
            .where(
                User.tenant_id == user.tenant_id,
                User.role.in_(["admin", "recruiter"]),
                User.is_active.is_(True),
            )
            .order_by(User.full_name)
        )
    ).all()
    saved = {
        g.user_id: g
        for g in (
            await db.scalars(select(FinanceGrant).where(FinanceGrant.entity_id == entity_id))
        ).all()
    }
    return [
        GrantRead(
            user_id=p.id,
            name=p.full_name or "Firmenmitglied",
            permissions=saved[p.id].permissions if p.id in saved else [],
            version=saved[p.id].version if p.id in saved else 0,
        )
        for p in people
    ]


@router.put(
    "/entities/{entity_id}/grants",
    response_model=GrantRead,
    status_code=200,
    summary="Finanzrechte ausdrücklich vergeben oder widerrufen",
)
async def put_grant(entity_id: uuid.UUID, data: GrantInput, user: HR, db: DB) -> GrantRead:
    entity, _ = await access(db, user, entity_id, "manage", True)
    target = await db.scalar(
        select(User).where(
            User.id == data.user_id,
            User.tenant_id == user.tenant_id,
            User.role.in_(["admin", "recruiter"]),
            User.is_active.is_(True),
        )
    )
    if target is None:
        raise HTTPException(404, "Aktives Firmenmitglied nicht gefunden.")
    permissions: list[str] = sorted(set([*data.permissions, "read"])) if data.permissions else []
    if target.id == user.id and "manage" not in permissions:
        raise HTTPException(409, "Die eigene Finanzverwaltung kann hier nicht entzogen werden.")
    grant = await db.scalar(
        select(FinanceGrant).where(
            FinanceGrant.entity_id == entity_id, FinanceGrant.user_id == target.id
        )
    )
    if (grant.version if grant else 0) != data.version:
        raise HTTPException(409, "Finanzrechte wurden geändert. Bitte neu laden.")
    if grant is None:
        grant = FinanceGrant(entity_id=entity_id, user_id=target.id, permissions=permissions)
        db.add(grant)
    else:
        grant.permissions = permissions
        grant.version += 1
    record(
        db,
        entity,
        user,
        "grants_changed",
        f"Mitglied {target.id}: {', '.join(permissions) or 'widerrufen'}",
    )
    await db.flush()
    return GrantRead(
        user_id=target.id,
        name=target.full_name or "Firmenmitglied",
        permissions=permissions,
        version=grant.version,
    )


@router.get(
    "/invoices",
    response_model=list[InvoiceRead],
    status_code=200,
    summary="Rechnungen eines freigegebenen Ausstellers",
)
async def invoices(
    entity_id: uuid.UUID,
    user: HR,
    db: DB,
    response: Response,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[InvoiceRead]:
    await access(db, user, entity_id)
    response.headers["Cache-Control"] = "no-store"
    rows = await db.scalars(
        select(Invoice)
        .where(Invoice.entity_id == entity_id, Invoice.tenant_id == user.tenant_id)
        .order_by(Invoice.created_at.desc(), Invoice.id)
        .offset(offset)
        .limit(limit)
    )
    return [InvoiceRead.model_validate(i) for i in rows]


@router.post(
    "/entities/{entity_id}/invoices",
    response_model=InvoiceRead,
    status_code=201,
    summary="Rechnungsentwurf mit nachvollziehbaren Beträgen anlegen",
)
async def create_invoice(
    entity_id: uuid.UUID, data: InvoiceCreate, user: HR, db: DB, response: Response
) -> InvoiceRead:
    # Across issuers, retries cannot create a second document under the same request key.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"invoice:{user.tenant_id}:{data.request_key}"},
    )
    entity, _ = await access(db, user, entity_id, "prepare", True)
    initial = data.model_dump(mode="json", exclude={"request_key"})
    fingerprint = xrechnung.digest({"entity_id": str(entity_id), "invoice": initial})
    existing = await db.scalar(
        select(Invoice).where(
            Invoice.tenant_id == user.tenant_id, Invoice.request_key == data.request_key
        )
    )
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(
                409, "Anfrageschlüssel wurde bereits mit anderen Rechnungsdaten verwendet."
            )
        response.status_code = 200
        return InvoiceRead.model_validate(existing)
    invoice = Invoice(
        tenant_id=user.tenant_id,
        entity_id=entity_id,
        request_key=data.request_key,
        request_hash=fingerprint,
    )
    set_payload(invoice, entity, InvoiceInput.model_validate(initial), user)
    db.add(invoice)
    await db.flush()
    record(db, entity, user, "draft_created", invoice=invoice)
    return InvoiceRead.model_validate(invoice)


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceRead,
    status_code=200,
    summary="Rechnungsstand mit Prüfstatus anzeigen",
)
async def get_invoice(invoice_id: uuid.UUID, user: HR, db: DB, response: Response) -> InvoiceRead:
    invoice, _ = await owned_invoice(db, user, invoice_id)
    response.headers["Cache-Control"] = "no-store"
    return InvoiceRead.model_validate(invoice)


@router.put(
    "/invoices/{invoice_id}",
    response_model=InvoiceRead,
    status_code=200,
    summary="Rechnungsentwurf bearbeiten",
)
async def edit_invoice(invoice_id: uuid.UUID, data: InvoiceUpdate, user: HR, db: DB) -> InvoiceRead:
    invoice, entity = await owned_invoice(db, user, invoice_id, "prepare", True)
    version(invoice, data)
    if invoice.status != "draft" or invoice.kind != "invoice":
        raise HTTPException(409, "Nur gewöhnliche Rechnungsentwürfe sind hier bearbeitbar.")
    set_payload(
        invoice, entity, InvoiceInput.model_validate(data.model_dump(exclude={"version"})), user
    )
    invoice.version += 1
    record(db, entity, user, "draft_updated", invoice=invoice)
    await db.flush()
    return InvoiceRead.model_validate(invoice)


@router.post(
    "/invoices/{invoice_id}/submit",
    response_model=InvoiceRead,
    status_code=200,
    summary="Rechnung zur Finanzprüfung vorlegen",
)
async def submit(invoice_id: uuid.UUID, data: Decision, user: HR, db: DB) -> InvoiceRead:
    invoice, entity = await owned_invoice(db, user, invoice_id, "prepare", True)
    version(invoice, data)
    current_entity(invoice, entity)
    if invoice.status != "draft":
        raise HTTPException(409, "Nur Entwürfe können zur Prüfung vorgelegt werden.")
    invoice.status = "in_review"
    invoice.version += 1
    record(db, entity, user, "submitted", data.note, invoice)
    await db.flush()
    return InvoiceRead.model_validate(invoice)


@router.post(
    "/invoices/{invoice_id}/approve",
    response_model=InvoiceRead,
    status_code=200,
    summary="Exakten Rechnungsstand fachlich freigeben",
)
async def approve(invoice_id: uuid.UUID, data: Decision, user: HR, db: DB) -> InvoiceRead:
    invoice, entity = await owned_invoice(db, user, invoice_id, "approve", True)
    version(invoice, data)
    current_entity(invoice, entity)
    if invoice.status != "in_review":
        raise HTTPException(409, "Die Rechnung befindet sich nicht in Prüfung.")
    if entity.data["four_eyes"] and invoice.prepared_by == user.id:
        raise HTTPException(403, "Diese Rechnung muss eine andere berechtigte Person prüfen.")
    if invoice.payload_hash != xrechnung.digest(invoice.payload):
        raise HTTPException(409, "Der gespeicherte Rechnungsstand ist inkonsistent.")
    invoice.approved_by = user.id
    approval_grant = (
        await db.scalars(
            select(FinanceGrant).where(
                FinanceGrant.entity_id == entity.id, FinanceGrant.user_id == user.id
            )
        )
    ).one()
    invoice.approved_grant_version = approval_grant.version
    invoice.status = "approved"
    invoice.version += 1
    record(db, entity, user, "approved", data.note, invoice)
    await db.flush()
    return InvoiceRead.model_validate(invoice)


@router.post(
    "/invoices/{invoice_id}/return",
    response_model=InvoiceRead,
    status_code=200,
    summary="Rechnung zur Bearbeitung zurückgeben und Freigabe aufheben",
)
async def return_draft(invoice_id: uuid.UUID, data: Decision, user: HR, db: DB) -> InvoiceRead:
    invoice, entity = await owned_invoice(db, user, invoice_id, "read", True)
    _, permissions = await access(db, user, entity.id)
    if not {"prepare", "approve"}.intersection(permissions):
        raise HTTPException(403, "Ein Vorbereitungs- oder Prüfrecht ist erforderlich.")
    version(invoice, data)
    if invoice.status not in {"in_review", "approved"}:
        raise HTTPException(409, "Dieser Beleg kann nicht zur Bearbeitung zurückgegeben werden.")
    invoice.status = "draft"
    invoice.approved_by = None
    invoice.approved_grant_version = None
    invoice.validation = None
    invoice.validation_report = None
    # Full credits retain the original commercial snapshot; require a fresh approval.
    if invoice.kind == "credit_note":
        invoice.entity_version = entity.version
    invoice.version += 1
    record(db, entity, user, "returned", data.note, invoice)
    await db.flush()
    return InvoiceRead.model_validate(invoice)


@router.post(
    "/invoices/{invoice_id}/finalize",
    response_model=InvoiceRead,
    status_code=200,
    summary="Freigegebene Rechnung nummerieren und als XRechnung prüfen",
)
async def finalize(invoice_id: uuid.UUID, data: Decision, user: HR, db: DB) -> InvoiceRead:
    invoice, entity = await owned_invoice(db, user, invoice_id, "issue", True)
    # A lost response can be retried without allocating another number.
    if invoice.status in {"finalized", "cancelled"}:
        return InvoiceRead.model_validate(invoice)
    version(invoice, data)
    current_entity(invoice, entity)
    if invoice.status != "approved" or invoice.payload_hash != xrechnung.digest(invoice.payload):
        raise HTTPException(409, "Eine unveränderte freigegebene Rechnung ist erforderlich.")
    reviewer = await db.scalar(
        select(User)
        .join(FinanceGrant, FinanceGrant.user_id == User.id)
        .where(
            User.id == invoice.approved_by,
            User.tenant_id == user.tenant_id,
            User.is_active.is_(True),
            User.role.in_(["admin", "recruiter"]),
            FinanceGrant.entity_id == entity.id,
        )
    )
    reviewer_grant = await db.scalar(
        select(FinanceGrant).where(
            FinanceGrant.entity_id == entity.id, FinanceGrant.user_id == invoice.approved_by
        )
    )
    if (
        reviewer is None
        or reviewer_grant is None
        or "approve" not in reviewer_grant.permissions
        or reviewer_grant.version != invoice.approved_grant_version
    ):
        raise HTTPException(409, "Die Finanzfreigabe ist nicht mehr gültig. Erneut prüfen lassen.")
    if invoice.kind == "invoice" and await db.scalar(
        select(BilledService.id).where(
            BilledService.entity_id == entity.id,
            BilledService.reference == invoice.service_reference,
        )
    ):
        raise HTTPException(409, "Diese Leistungsreferenz wurde bereits abgerechnet.")
    seq = await db.scalar(
        select(InvoiceSequence).where(
            InvoiceSequence.entity_id == entity.id, InvoiceSequence.year == invoice.issue_date.year
        )
    )
    if seq is None:
        seq = InvoiceSequence(entity_id=entity.id, year=invoice.issue_date.year, next_number=1)
        db.add(seq)
    number = f"{entity.data['invoice_prefix']}-{invoice.issue_date.year}-{seq.next_number:06d}"
    xml = xrechnung.generate(invoice.payload, number, invoice.kind == "credit_note")
    validation, report = await xrechnung.validate(xml)
    invoice.validation = validation
    invoice.validation_report = report
    invoice.version += 1
    if validation["status"] != "valid":
        record(db, entity, user, "validation_failed", data.note, invoice)
        await db.flush()
        return InvoiceRead.model_validate(invoice)
    invoice.artifact = xml
    invoice.artifact_hash = hashlib.sha256(xml).hexdigest()
    invoice.number = number
    invoice.status = "finalized"
    seq.next_number += 1
    if invoice.kind == "invoice":
        db.add(
            BilledService(
                entity_id=entity.id, reference=invoice.service_reference, invoice_id=invoice.id
            )
        )
    else:
        original = await db.scalar(
            select(Invoice)
            .where(Invoice.id == invoice.original_id, Invoice.entity_id == entity.id)
            .with_for_update()
        )
        if original is None or original.status != "finalized":
            raise HTTPException(409, "Ursprungsrechnung ist nicht mehr stornierbar.")
        original.status = "cancelled"
        original.version += 1
        record(db, entity, user, "cancelled", f"Stornobeleg {number}", original)
    record(db, entity, user, "finalized", data.note, invoice)
    await db.flush()
    return InvoiceRead.model_validate(invoice)


@router.post(
    "/invoices/{invoice_id}/credit",
    response_model=InvoiceRead,
    status_code=201,
    summary="Vollständigen Stornobeleg zur ursprünglichen Rechnung vorbereiten",
)
async def credit(
    invoice_id: uuid.UUID, data: CreditInput, user: HR, db: DB, response: Response
) -> InvoiceRead:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"invoice:{user.tenant_id}:{data.request_key}"},
    )
    original, entity = await owned_invoice(db, user, invoice_id, "prepare", True)
    fingerprint = xrechnung.digest(
        {
            "original_id": str(invoice_id),
            **data.model_dump(mode="json", exclude={"version", "request_key"}),
        }
    )
    existing = await db.scalar(
        select(Invoice).where(
            Invoice.tenant_id == user.tenant_id, Invoice.request_key == data.request_key
        )
    )
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(409, "Anfrageschlüssel wurde bereits anders verwendet.")
        response.status_code = 200
        return InvoiceRead.model_validate(existing)
    version(original, data)
    if (
        original.status != "finalized"
        or original.kind != "invoice"
        or data.issue_date < original.issue_date
    ):
        raise HTTPException(
            409, "Eine finalisierte Rechnung und ein gültiges Stornodatum sind erforderlich."
        )
    if await db.scalar(select(Invoice.id).where(Invoice.original_id == original.id)):
        raise HTTPException(409, "Für diese Rechnung existiert bereits ein Stornobeleg.")
    source = InvoiceInput.model_validate(original.payload["invoice"])
    source = InvoiceInput.model_validate(
        {**source.model_dump(), "issue_date": data.issue_date, "due_date": data.issue_date}
    )
    invoice = Invoice(
        tenant_id=user.tenant_id,
        entity_id=entity.id,
        request_key=data.request_key,
        request_hash=fingerprint,
        kind="credit_note",
        original_id=original.id,
    )
    set_payload(invoice, entity, source, user)
    invoice.payload = {
        **invoice.payload,
        "seller": original.payload["seller"],
        "original_number": original.number,
        "original_date": original.issue_date.isoformat(),
    }
    invoice.payload_hash = xrechnung.digest(invoice.payload)
    db.add(invoice)
    await db.flush()
    record(db, entity, user, "credit_draft_created", data.note, invoice)
    return InvoiceRead.model_validate(invoice)


@router.get(
    "/invoices/{invoice_id}/events",
    response_model=list[EventRead],
    status_code=200,
    summary="Finanzprüfungen und Rechnungsverlauf",
)
async def events(invoice_id: uuid.UUID, user: HR, db: DB) -> list[EventRead]:
    await owned_invoice(db, user, invoice_id)
    rows = await db.scalars(
        select(FinanceEvent)
        .where(FinanceEvent.invoice_id == invoice_id)
        .order_by(FinanceEvent.created_at, FinanceEvent.id)
    )
    return [EventRead.model_validate(e) for e in rows]


@router.get(
    "/invoices/{invoice_id}/download",
    response_model=None,
    status_code=200,
    summary="Gespeicherte XRechnung oder KoSIT-Prüfbericht herunterladen",
)
async def download(invoice_id: uuid.UUID, user: HR, db: DB, report: bool = False) -> Response:
    invoice, _ = await owned_invoice(db, user, invoice_id, "export")
    content = invoice.validation_report if report else invoice.artifact
    if content is None or not report and invoice.status not in {"finalized", "cancelled"}:
        raise HTTPException(409, "Das angeforderte Artefakt ist noch nicht verfügbar.")
    filename = f"{invoice.number or invoice.id}{'-pruefbericht' if report else ''}.xml"
    return Response(
        content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )
