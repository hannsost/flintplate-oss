"""Recorded physical cash and authenticated adapter tenders, with exact source splits.

This ledger records received money; it does not charge cards or fiscalize receipts.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.cash_models import CashEntry, CashRegister, CashSession
from app.gastro.cash_schemas import (
    BalanceLine,
    BalanceRead,
    CashPaymentInput,
    CloseInput,
    CountInput,
    EntryRead,
    ExternalRefundInput,
    MovementInput,
    OpenSession,
    ReconciliationRead,
    RefundInput,
    RegisterInput,
    RegisterRead,
    SessionRead,
)
from app.gastro.models import (
    Device,
    GuestAccount,
    LoyaltyEntry,
    Membership,
    Order,
    Venue,
    Voucher,
    VoucherEntry,
)
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import OrderRead, PaymentInput

router = APIRouter(dependencies=[Depends(private_response)])


def command_hash(kind: str, target: uuid.UUID, data: BaseModel) -> str:
    return hashlib.sha256(
        json.dumps([kind, str(target), data.model_dump(mode="json")], sort_keys=True).encode()
    ).hexdigest()


def legacy_command_hash(kind: str, target: uuid.UUID, data: BaseModel) -> str | None:
    """Match only a persisted pre-085 command with absent correction fields."""
    added = {"cancellation_id", "cancellation_version", "confirmed"}
    if data.model_fields_set & added:
        return None
    original = data.model_dump(mode="json", exclude=added)
    return hashlib.sha256(
        json.dumps([kind, str(target), original], sort_keys=True).encode()
    ).hexdigest()


async def prior_entry(
    db: AsyncSession,
    venue_id: uuid.UUID,
    key: uuid.UUID,
    fingerprint: str,
    legacy_fingerprint: str | None = None,
) -> CashEntry | None:
    entry = (
        await db.execute(
            select(CashEntry).where(CashEntry.venue_id == venue_id, CashEntry.request_key == key)
        )
    ).scalar_one_or_none()
    if entry is not None and entry.request_hash not in {fingerprint, legacy_fingerprint}:
        raise HTTPException(409, "Vorgangs-ID wurde bereits mit anderen Kassendaten verwendet.")
    return entry


async def session_for(
    db: AsyncSession,
    venue_id: uuid.UUID,
    session_id: uuid.UUID,
    actor_id: uuid.UUID,
    role: str,
    *,
    open_only: bool = True,
) -> CashSession:
    session = (
        await db.execute(
            select(CashSession)
            .where(CashSession.id == session_id, CashSession.venue_id == venue_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if session is None or (role != "manager" and session.operator_id != actor_id):
        raise HTTPException(404, "Eigene Schichtkasse nicht gefunden.")
    if open_only and session.status != "open":
        raise HTTPException(409, "Die Schichtkasse ist bereits gezählt oder geschlossen.")
    return session


async def drawer_balance(db: AsyncSession, session_id: uuid.UUID) -> int:
    from app.gastro.payer_tip_models import PayerTipEntry

    additive = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(PayerTipEntry.amount_cents), 0)).where(
                    PayerTipEntry.session_id == session_id
                )
            )
        ).scalar_one()
    )
    return additive + int(
        (
            await db.execute(
                select(func.coalesce(func.sum(CashEntry.amount_cents), 0)).where(
                    CashEntry.session_id == session_id, CashEntry.method == "cash"
                )
            )
        ).scalar_one()
    )


async def order_entries(db: AsyncSession, order: Order) -> list[CashEntry]:
    return list(
        (
            await db.execute(
                select(CashEntry)
                .where(CashEntry.venue_id == order.venue_id, CashEntry.order_id == order.id)
                .order_by(CashEntry.created_at, CashEntry.id)
            )
        ).scalars()
    )


@dataclass
class Unit:
    line_id: str
    unit: int
    name: str
    kind: str
    gross: int
    tax: int
    paid: int = 0
    cancelled: bool = False

    @property
    def key(self) -> tuple[str, int]:
        return self.line_id, self.unit

    @property
    def remaining(self) -> int:
        return 0 if self.cancelled else max(0, self.gross - self.paid)


def units_for(
    order: Order,
    entries: list[CashEntry],
    *,
    virtual_voucher: bool = True,
    apply_cancellations: bool = True,
) -> list[Unit]:
    units: list[Unit] = []
    for index, line in enumerate(order.lines):
        line_id = str(line.get("line_id") or uuid.uuid5(order.id, f"line:{index}"))
        quantity, gross, tax = (
            int(str(line["quantity"])),
            int(str(line["total_cents"])),
            int(str(line["tax_cents"])),
        )
        for unit in range(quantity):
            units.append(
                Unit(
                    line_id,
                    unit,
                    str(line["name"]),
                    str(line.get("kind", "product")),
                    gross * (unit + 1) // quantity - gross * unit // quantity,
                    tax * (unit + 1) // quantity - tax * unit // quantity,
                )
            )
    if order.tip_cents:
        units.append(Unit("tip", 0, "Trinkgeld", "tip", order.tip_cents, 0))
    index_by_key = {unit.key: unit for unit in units}
    for entry in entries:
        if entry.kind != "sale":
            continue
        for allocation in entry.allocations:
            key = str(allocation["line_id"]), int(str(allocation["unit"]))
            if key in index_by_key:
                index_by_key[key].paid += int(str(allocation["amount_cents"]))
    if (
        virtual_voucher
        and order.voucher_cents
        and not any(entry.kind == "sale" and entry.method == "voucher" for entry in entries)
    ):
        for allocation in allocate(
            order.voucher_cents, [unit for unit in units if unit.kind != "tip"]
        ):
            index_by_key[(str(allocation["line_id"]), int(str(allocation["unit"])))].paid += int(
                str(allocation["amount_cents"])
            )
    if apply_cancellations:
        from app.gastro.cancellation_money import cancelled_keys

        cancelled = cancelled_keys(order)
        for active_unit in units:
            active_unit.cancelled = active_unit.key in cancelled
    return units


def allocate(amount: int, units: list[Unit]) -> list[dict[str, JsonValue]]:
    """Largest remainder for cents; cumulative per-unit tax boundaries conserve tax."""
    active = [unit for unit in units if unit.remaining]
    total = sum(unit.remaining for unit in active)
    if amount < 0 or amount > total:
        raise HTTPException(422, "Betrag übersteigt den offenen Rest.")
    if not amount:
        return []
    cents = [amount * unit.remaining // total for unit in active]
    remainder = amount - sum(cents)
    ranks = sorted(
        range(len(active)), key=lambda i: (-(amount * active[i].remaining % total), active[i].key)
    )
    for index in ranks[:remainder]:
        cents[index] += 1
    return [
        {
            "line_id": unit.line_id,
            "unit": unit.unit,
            "name": unit.name,
            "kind": unit.kind,
            "amount_cents": value,
            "tax_cents": unit.tax * (unit.paid + value) // unit.gross
            - unit.tax * unit.paid // unit.gross,
        }
        for unit, value in zip(active, cents, strict=True)
        if value
    ]


def balance_read(order: Order, entries: list[CashEntry]) -> BalanceRead:
    from app.gastro.cancellation_money import cancellation_version, refund_claims

    units = units_for(order, entries)
    # Historic adapter settlements predate this ledger; do not reopen their bills.
    legacy_paid = order.paid_at is not None and not any(entry.kind == "sale" for entry in entries)
    historical_cancelled = (
        order.status == "cancelled"
        and order.paid_at is None
        and not order.cancellation_units
        and not any(entry.kind == "sale" for entry in entries)
    )
    lines: dict[str, BalanceLine] = {}
    for unit in units:
        if unit.kind == "tip":
            continue
        row = lines.setdefault(
            unit.line_id,
            BalanceLine(
                line_id=uuid.UUID(unit.line_id),
                name=unit.name,
                kind=unit.kind,
                remaining_quantity=0,
                remaining_cents=0,
            ),
        )
        if unit.remaining and not legacy_paid and not historical_cancelled:
            row.remaining_quantity += 1
            row.remaining_cents += unit.remaining
        if unit.cancelled:
            row.cancelled_quantity += 1
            row.cancelled_cents += unit.gross
    remaining = 0 if legacy_paid or historical_cancelled else sum(unit.remaining for unit in units)
    actual_paid = sum(
        entry.amount_cents
        for entry in entries
        if entry.kind == "sale" and entry.method != "voucher"
    )
    claims = refund_claims(order, entries)
    cancelled_total = sum(row.gross_cents for row in order.cancellation_units)
    return BalanceRead(
        order_id=order.id,
        version=order.version,
        total_cents=order.total_cents,
        voucher_cents=order.voucher_cents,
        tip_cents=order.tip_cents,
        paid_cents=(
            (order.total_cents - order.voucher_cents + order.tip_cents)
            if legacy_paid
            else actual_paid
        ),
        remaining_cents=remaining,
        remaining_tip_cents=(
            0
            if legacy_paid or historical_cancelled
            else sum(unit.remaining for unit in units if unit.kind == "tip")
        ),
        refunded_cents=-sum(entry.amount_cents for entry in entries if entry.kind == "refund"),
        lines=list(lines.values()),
        entries=[EntryRead.model_validate(entry) for entry in entries],
        corrected_total_cents=(
            0 if historical_cancelled else order.total_cents + order.tip_cents - cancelled_total
        ),
        cancelled_cents=cancelled_total,
        unpaid_credit_cents=sum(row.unpaid_credit_cents for row in order.cancellation_units),
        refund_due_cents=sum(row.remaining_cents for row in claims),
        refund_claims=claims,
        cancellation_version=cancellation_version(order),
        historical_cancelled=historical_cancelled,
    )


@router.get(
    "/venues/{venue_id}/cash/registers",
    response_model=list[RegisterRead],
    status_code=200,
    summary="Bargeldkassen des Betriebs",
)
async def registers(venue_id: uuid.UUID, user: Actor, db: DB) -> list[CashRegister]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return list(
        (
            await db.execute(
                select(CashRegister)
                .where(CashRegister.venue_id == venue_id)
                .order_by(CashRegister.name)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/cash/registers",
    response_model=RegisterRead,
    status_code=201,
    summary="Bargeldkasse benennen",
)
async def create_register(
    venue_id: uuid.UUID, data: RegisterInput, user: Actor, db: DB
) -> CashRegister:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    prior = (
        await db.execute(
            select(CashRegister).where(
                CashRegister.venue_id == venue_id, CashRegister.name == data.name
            )
        )
    ).scalar_one_or_none()
    if prior:
        return prior
    register = CashRegister(venue_id=venue_id, name=data.name)
    db.add(register)
    await db.flush()
    svc.event(db, venue_id, "cash.register_created", register.id, {"name": register.name}, user.id)
    return register


@router.get(
    "/venues/{venue_id}/cash/sessions",
    response_model=list[SessionRead],
    status_code=200,
    summary="Eigene und freigegebene Schichtkassen",
)
async def sessions(venue_id: uuid.UUID, user: Actor, db: DB) -> list[CashSession]:
    _, role = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    query = select(CashSession).where(CashSession.venue_id == venue_id)
    if role != "manager":
        query = query.where(CashSession.operator_id == user.id)
    return list(
        (await db.execute(query.order_by(CashSession.created_at.desc()).limit(100))).scalars()
    )


@router.post(
    "/venues/{venue_id}/cash/sessions",
    response_model=SessionRead,
    status_code=201,
    summary="Persönliche Schichtkasse mit gezähltem Anfangsbestand öffnen",
)
async def open_session(venue_id: uuid.UUID, data: OpenSession, user: Actor, db: DB) -> CashSession:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = svc.digest(data)
    prior = (
        await db.execute(
            select(CashSession).where(
                CashSession.venue_id == venue_id, CashSession.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != fingerprint:
            raise HTTPException(409, "Öffnungs-ID bereits anders verwendet.")
        return prior
    register = (
        await db.execute(
            select(CashRegister)
            .where(CashRegister.id == data.register_id, CashRegister.venue_id == venue_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if register is None:
        raise HTTPException(404, "Bargeldkasse nicht gefunden.")
    member = (
        await db.execute(
            select(Membership.id).where(
                Membership.venue_id == venue_id,
                Membership.user_id == data.operator_id,
                Membership.active.is_(True),
                Membership.role.in_(svc.SERVICE),
            )
        )
    ).first()
    if not member:
        raise HTTPException(404, "Aktive Serviceperson dieses Betriebs erforderlich.")
    if (
        await db.execute(
            select(CashSession.id).where(
                CashSession.register_id == register.id, CashSession.status.in_(["open", "counted"])
            )
        )
    ).first():
        raise HTTPException(409, "Diese Kasse hat bereits eine offene Schicht.")
    session = CashSession(
        venue_id=venue_id,
        register_id=register.id,
        operator_id=data.operator_id,
        request_key=data.request_key,
        request_hash=fingerprint,
    )
    db.add(session)
    await db.flush()
    db.add(
        CashEntry(
            venue_id=venue_id,
            session_id=session.id,
            kind="opening",
            method="cash",
            amount_cents=data.opening_cents,
            currency=venue.currency,
            actor_id=user.id,
            request_key=uuid.uuid5(data.request_key, "opening"),
            request_hash=fingerprint,
        )
    )
    svc.event(
        db,
        venue_id,
        "cash.session_opened",
        session.id,
        {
            "opening_cents": data.opening_cents,
            "operator_id": str(data.operator_id),
            "register_id": str(register.id),
        },
        user.id,
    )
    await db.flush()
    return session


@router.post(
    "/venues/{venue_id}/cash/sessions/{session_id}/movements",
    response_model=EntryRead,
    status_code=201,
    summary="Begründete Bareinlage oder Entnahme buchen",
)
async def movement(
    venue_id: uuid.UUID, session_id: uuid.UUID, data: MovementInput, user: Actor, db: DB
) -> CashEntry:
    venue, role = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = command_hash("movement", session_id, data)
    prior = await prior_entry(db, venue_id, data.request_key, fingerprint)
    if prior:
        return prior
    session = await session_for(db, venue_id, session_id, user.id, role)
    if await drawer_balance(db, session.id) + data.amount_cents < 0:
        raise HTTPException(422, "Entnahme übersteigt den Kassenbestand.")
    entry = CashEntry(
        venue_id=venue_id,
        session_id=session.id,
        kind="movement",
        method="cash",
        amount_cents=data.amount_cents,
        currency=venue.currency,
        reason=data.reason,
        actor_id=user.id,
        request_key=data.request_key,
        request_hash=fingerprint,
    )
    db.add(entry)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "cash.movement",
        entry.id,
        {"session_id": str(session.id), "amount_cents": data.amount_cents, "reason": data.reason},
        user.id,
    )
    return entry


@router.post(
    "/venues/{venue_id}/cash/sessions/{session_id}/count",
    response_model=SessionRead,
    status_code=200,
    summary="Blind gezählten Bestand festhalten und Kasse für Zahlungen sperren",
)
async def count_session(
    venue_id: uuid.UUID, session_id: uuid.UUID, data: CountInput, user: Actor, db: DB
) -> CashSession:
    _, role = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    session = await session_for(db, venue_id, session_id, user.id, role, open_only=False)
    fingerprint = svc.digest(data)
    if session.count_request_key == data.request_key:
        if session.count_request_hash != fingerprint:
            raise HTTPException(409, "Zählungs-ID bereits anders verwendet.")
        return session
    svc.check_version(session.version, data.version)
    if session.status != "open":
        raise HTTPException(409, "Diese Kasse wurde bereits gezählt.")
    session.expected_cents = await drawer_balance(db, session.id)
    session.counted_cents = data.counted_cents
    session.difference_cents = data.counted_cents - session.expected_cents
    session.count_reason = data.reason
    session.count_request_key = data.request_key
    session.count_request_hash = fingerprint
    session.status = "counted"
    session.version += 1
    svc.event(
        db,
        venue_id,
        "cash.counted",
        session.id,
        {
            "counted_cents": data.counted_cents,
            "expected_cents": session.expected_cents,
            "difference_cents": session.difference_cents,
            "reason": data.reason,
        },
        user.id,
    )
    await db.flush()
    return session


@router.post(
    "/venues/{venue_id}/cash/sessions/{session_id}/close",
    response_model=SessionRead,
    status_code=200,
    summary="Gezählte Schichtkasse mit Differenzbegründung abschließen",
)
async def close_session(
    venue_id: uuid.UUID, session_id: uuid.UUID, data: CloseInput, user: Actor, db: DB
) -> CashSession:
    _, role = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    session = await session_for(db, venue_id, session_id, user.id, role, open_only=False)
    if session.status == "closed" and data.version in {session.version, session.version - 1}:
        return session
    svc.check_version(session.version, data.version)
    if session.status != "counted":
        raise HTTPException(409, "Vor Abschluss den Bargeldbestand blind zählen.")
    if session.difference_cents and len(data.reason.strip()) < 3:
        raise HTTPException(422, "Die Kassendifferenz muss begründet werden.")
    session.count_reason = data.reason or session.count_reason
    session.status = "closed"
    session.closed_at = datetime.now(UTC)
    session.closed_by = user.id
    session.version += 1
    svc.event(
        db,
        venue_id,
        "cash.closed",
        session.id,
        {
            "counted_cents": session.counted_cents,
            "expected_cents": session.expected_cents,
            "difference_cents": session.difference_cents,
            "reason": session.count_reason,
        },
        user.id,
    )
    await db.flush()
    return session


@router.get(
    "/venues/{venue_id}/orders/{order_id}/balance",
    response_model=BalanceRead,
    status_code=200,
    summary="Offene Beträge, Positionen und bestätigte Teilzahlungen",
)
async def balance(venue_id: uuid.UUID, order_id: uuid.UUID, user: Actor, db: DB) -> BalanceRead:
    from app.gastro.cancellation_money import pending_checkout

    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    result = balance_read(order, await order_entries(db, order))
    result.checkout_blocked = await pending_checkout(db, order)
    return result


async def ledger_lock(db: AsyncSession, venue_id: uuid.UUID) -> None:
    # Independent of Venue row locks: device callbacks already hold their order.
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(venue_id), 789))))


def voucher_tender(order: Order, entries: list[CashEntry]) -> CashEntry:
    units = [
        unit
        for unit in units_for(order, entries, virtual_voucher=False, apply_cancellations=False)
        if unit.kind != "tip"
    ]
    return CashEntry(
        id=uuid.uuid5(order.request_key, "voucher-tender"),
        venue_id=order.venue_id,
        order_id=order.id,
        kind="sale",
        method="voucher",
        amount_cents=order.voucher_cents,
        currency=order.currency,
        allocations=allocate(order.voucher_cents, units),
        request_key=uuid.uuid5(order.request_key, "voucher-tender"),
        request_hash=hashlib.sha256(f"{order.id}:{order.voucher_cents}".encode()).hexdigest(),
    )


async def materialize_voucher(db: AsyncSession, order: Order, entries: list[CashEntry]) -> None:
    if not order.voucher_cents or any(
        entry.kind == "sale" and entry.method == "voucher" for entry in entries
    ):
        return
    entry = voucher_tender(order, entries)
    db.add(entry)
    await db.flush()
    entries.append(entry)
    svc.event(
        db,
        order.venue_id,
        "payment.voucher_confirmed",
        order.id,
        {"entry_id": str(entry.id), "amount_cents": order.voucher_cents},
    )


async def finish_sale(
    db: AsyncSession, order: Order, entry: CashEntry, entries: list[CashEntry]
) -> Order:
    db.add(entry)
    await db.flush()
    entries.append(entry)
    remaining = sum(unit.remaining for unit in units_for(order, entries))
    order.payment_status = "paid" if remaining == 0 else "partial"
    if not remaining:
        from app.gastro.benefits import earn_points

        await earn_points(db, order)
        order.status = "settled"
        order.paid_at = datetime.now(UTC)
        order.payment_reference = entry.external_reference or f"cash-ledger:{entry.id}"
    from app.gastro.cancellation_money import project_payment_status

    project_payment_status(order, entries)
    order.version += 1
    svc.event(
        db,
        order.venue_id,
        "payment.confirmed" if not remaining else "payment.partially_confirmed",
        order.id,
        {
            "entry_id": str(entry.id),
            "amount_cents": entry.amount_cents,
            "method": entry.method,
            "remaining_cents": remaining,
            "allocations": cast(JsonValue, entry.allocations),
            "payer": entry.payer,
        },
        entry.actor_id,
        entry.device_id,
    )
    await db.flush()
    return order


def payable(order: Order) -> None:
    cancelled_with_tip = (
        order.status == "cancelled" and order.cancellation_units and order.tip_cents
    )
    if (order.status != "served" and not cancelled_with_tip) or order.paid_at is not None:
        raise HTTPException(
            409, "Nur servierte, noch nicht vollständig bezahlte Bons können kassiert werden."
        )


async def confirm_external_payment(
    db: AsyncSession, venue: Venue, order: Order, data: PaymentInput, device: Device
) -> Order:
    """Called only after device authentication and while holding the order lock.

    A reference asserts an already collected external tender; no card is charged.
    The caller retains its DeviceReceipt and adapter-specific event handling.
    """
    if device.kind != "pos" or device.venue_id != venue.id or "payments:write" not in device.scopes:
        raise HTTPException(403, "Autorisierter Kassenadapter erforderlich.")
    await ledger_lock(db, venue.id)
    fingerprint = command_hash("external-payment", order.id, data)
    if await prior_entry(
        db,
        venue.id,
        data.request_key,
        fingerprint,
        legacy_command_hash("external-payment", order.id, data),
    ):
        return order
    from app.gastro.cancellation_money import assert_adapter_version, assert_checkout_reconciled

    await assert_checkout_reconciled(db, order)
    assert_adapter_version(order, data.cancellation_version)
    payable(order)
    if not order.pos_requested:
        raise HTTPException(409, "Der Bon wurde noch nicht an die Kasse übergeben.")
    reference = data.reference.strip()
    if not reference or data.currency != order.currency:
        raise HTTPException(
            422, "Gültige externe Zahlungsreferenz und passende Währung erforderlich."
        )
    if (
        await db.execute(
            select(CashEntry.id).where(
                CashEntry.venue_id == venue.id, CashEntry.external_reference == reference
            )
        )
    ).first():
        raise HTTPException(
            409, "Diese externe Zahlung wurde bereits einem Kassenvorgang zugeordnet."
        )
    entries = await order_entries(db, order)
    await materialize_voucher(db, order, entries)
    units = units_for(order, entries)
    if order.cancellation_units and not any(unit.remaining for unit in units):
        raise HTTPException(
            409, "Der korrigierte Bon hat keine offene Forderung; keine neue Zahlung buchen."
        )
    if not data.amount_cents and any(unit.remaining > 0 for unit in units):
        raise HTTPException(422, "Eine offene Rechnung benötigt einen positiven Teilbetrag.")
    allocations = allocate(data.amount_cents, units)
    if data.cancellation_version is not None:
        for row in allocations:
            row["cancellation_version"] = data.cancellation_version
    entry = CashEntry(
        venue_id=venue.id,
        order_id=order.id,
        kind="sale",
        method="external",
        amount_cents=data.amount_cents,
        currency=order.currency,
        allocations=allocations,
        device_id=device.id,
        external_reference=reference,
        request_key=data.request_key,
        request_hash=fingerprint,
    )
    return await finish_sale(db, order, entry, entries)


@router.post(
    "/venues/{venue_id}/orders/{order_id}/cash-payments",
    response_model=OrderRead,
    status_code=200,
    summary="Tatsächlich erhaltenes Bargeld nach Betrag, Person oder Position buchen",
)
async def cash_payment(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: CashPaymentInput, user: Actor, db: DB
) -> Order:
    venue, role = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    session = await session_for(db, venue_id, data.session_id, user.id, role, open_only=False)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    await ledger_lock(db, venue_id)
    fingerprint = command_hash("cash-payment", order.id, data)
    if await prior_entry(db, venue_id, data.request_key, fingerprint):
        return order
    from app.gastro.cancellation_money import assert_checkout_reconciled

    await assert_checkout_reconciled(db, order)
    if session.status != "open":
        raise HTTPException(409, "Die Schichtkasse ist für weitere Zahlungen gesperrt.")
    svc.check_version(order.version, data.version)
    payable(order)
    if not order.pos_requested:
        await svc.handoff_checkout(db, order, user.id)
    entries = await order_entries(db, order)
    await materialize_voucher(db, order, entries)
    units = units_for(order, entries)
    remaining = sum(unit.remaining for unit in units)
    if order.cancellation_units and not remaining:
        raise HTTPException(
            409, "Der korrigierte Bon hat keine offene Forderung; keine neue Zahlung buchen."
        )
    if data.mode == "items":
        allocations: list[dict[str, JsonValue]] = []
        for selection in data.items:
            chosen = [
                unit for unit in units if unit.line_id == str(selection.line_id) and unit.remaining
            ]
            if len(chosen) < selection.quantity:
                raise HTTPException(
                    422, "Eine ausgewählte Position ist bereits bezahlt oder nicht vorhanden."
                )
            chosen = chosen[: selection.quantity]
            allocations.extend(allocate(sum(unit.remaining for unit in chosen), chosen))
        allocations.extend(allocate(data.tip_cents, [unit for unit in units if unit.kind == "tip"]))
        amount = sum(int(str(row["amount_cents"])) for row in allocations)
    else:
        amount = (
            ((remaining + (data.people or 1) - 1) // (data.people or 1))
            if data.mode == "equal"
            else (data.amount_cents or 0)
        )
        if not amount and remaining:
            raise HTTPException(422, "Ein positiver Teilbetrag ist erforderlich.")
        allocations = allocate(amount, units)
    received = data.received_cents if data.received_cents is not None else amount
    if received < amount:
        raise HTTPException(
            422, "Erhaltenes Bargeld reicht für den gewählten Teilbetrag nicht aus."
        )
    from app.gastro.cancellation_money import cancellation_version

    revision = cancellation_version(order)
    if revision is not None:
        for allocation in allocations:
            allocation["cancellation_version"] = revision
    entry = CashEntry(
        venue_id=venue.id,
        session_id=session.id,
        order_id=order.id,
        kind="sale",
        method="cash",
        amount_cents=amount,
        received_cents=received,
        change_cents=received - amount,
        currency=order.currency,
        allocations=allocations,
        payer=data.payer,
        actor_id=user.id,
        request_key=data.request_key,
        request_hash=fingerprint,
    )
    return await finish_sale(db, order, entry, entries)


async def refund_source(db: AsyncSession, venue_id: uuid.UUID, entry_id: uuid.UUID) -> CashEntry:
    source = (
        await db.execute(
            select(CashEntry).where(CashEntry.id == entry_id, CashEntry.venue_id == venue_id)
        )
    ).scalar_one_or_none()
    if source is None or source.kind != "sale" or source.order_id is None:
        raise HTTPException(404, "Bestätigte Originalzahlung nicht gefunden.")
    return source


def refund_allocations(
    source: CashEntry, previous: list[CashEntry], amount: int
) -> list[dict[str, JsonValue]]:
    units = [
        Unit(
            str(row["line_id"]),
            int(str(row["unit"])),
            str(row["name"]),
            str(row["kind"]),
            int(str(row["amount_cents"])),
            int(str(row["tax_cents"])),
        )
        for row in source.allocations
    ]
    by_key = {unit.key: unit for unit in units}
    for refund in previous:
        if refund.original_id != source.id:
            continue
        for row in refund.allocations:
            by_key[(str(row["line_id"]), int(str(row["unit"])))].paid += int(
                str(row["amount_cents"])
            )
    return allocate(amount, units)


async def finish_refund(
    db: AsyncSession, order: Order, source: CashEntry, entry: CashEntry
) -> CashEntry:
    refunded_tip = sum(
        int(str(row["amount_cents"])) for row in entry.allocations if row["kind"] == "tip"
    )
    if refunded_tip and order.tip_run_id is not None:
        raise HTTPException(
            409,
            "Bereits verteiltes Trinkgeld benötigt eine gesonderte Rückabwicklung der Verteilung.",
        )
    prior = await order_entries(db, order)
    if order.customer_id is not None:
        account = (
            await db.execute(
                select(GuestAccount).where(GuestAccount.id == order.customer_id).with_for_update()
            )
        ).scalar_one()
        earned = (
            await db.execute(select(LoyaltyEntry).where(LoyaltyEntry.order_id == order.id))
        ).scalar_one_or_none()
        if earned:
            eligible = sum(
                int(str(line["total_cents"]))
                for line in order.lines
                if line.get("kind", "product") in {"product", "activity"}
            )
            eligible -= sum(
                row.unpaid_credit_cents
                for row in order.cancellation_units
                if row.kind in {"product", "activity"}
            )
            refunded_goods = sum(
                int(str(allocation["amount_cents"]))
                for row in [*prior, entry]
                if row.kind == "refund"
                for allocation in row.allocations
                if allocation["kind"] in {"product", "activity"}
            )
            desired = max(0, eligible - refunded_goods) // 100
            already_reversed = -sum(row.points_delta for row in prior if row.kind == "refund")
            reversal = max(0, earned.points - desired - already_reversed)
            entry.points_delta = -reversal
            account.points -= reversal
    total_refunds = (
        -sum(row.amount_cents for row in prior if row.kind == "refund") - entry.amount_cents
    )
    db.add(entry)
    await db.flush()
    # The database validates the refund source before accepting Order's summary.
    order.tip_refunded_cents += refunded_tip
    order.payment_status = (
        "refunded"
        if total_refunds == sum(row.amount_cents for row in prior if row.kind == "sale")
        else "partially_refunded"
    )
    from app.gastro.cancellation_money import project_payment_status

    project_payment_status(order, [*prior, entry])
    order.version += 1
    svc.event(
        db,
        order.venue_id,
        "payment.refunded",
        order.id,
        {
            "entry_id": str(entry.id),
            "original_id": str(source.id),
            "amount_cents": -entry.amount_cents,
            "method": entry.method,
            "tip_cents": refunded_tip,
            "reason": entry.reason,
            "allocations": cast(JsonValue, entry.allocations),
        },
        entry.actor_id,
        entry.device_id,
    )
    await db.flush()
    return entry


async def restore_voucher(
    db: AsyncSession, order: Order, amount: int, key: uuid.UUID, actor_id: uuid.UUID
) -> None:
    rows = list(
        (
            await db.execute(
                select(VoucherEntry)
                .where(VoucherEntry.order_id == order.id)
                .order_by(VoucherEntry.voucher_id)
            )
        ).scalars()
    )
    owed: dict[uuid.UUID, int] = {}
    for row in rows:
        owed[row.voucher_id] = owed.get(row.voucher_id, 0) - row.amount_cents
    remaining = amount
    for voucher_id, available in owed.items():
        credit = min(max(available, 0), remaining)
        if not credit:
            continue
        voucher = (
            await db.execute(
                select(Voucher)
                .where(Voucher.id == voucher_id, Voucher.venue_id == order.venue_id)
                .with_for_update()
            )
        ).scalar_one()
        voucher.balance_cents += credit
        db.add(
            VoucherEntry(
                venue_id=order.venue_id,
                voucher_id=voucher_id,
                order_id=order.id,
                amount_cents=credit,
                request_key=uuid.uuid5(key, str(voucher_id)),
                request_hash=hashlib.sha256(f"{order.id}:{credit}".encode()).hexdigest(),
                kind="refund",
                actor_id=actor_id,
            )
        )
        remaining -= credit
    if remaining:
        raise HTTPException(409, "Gutscheinquellen können nicht vollständig zugeordnet werden.")


@router.post(
    "/venues/{venue_id}/cash/payments/{entry_id}/refunds",
    response_model=EntryRead,
    status_code=201,
    summary="Bargeld tatsächlich zurückgeben oder Gutschein zurückbuchen und Original referenzieren",
)
async def refund(
    venue_id: uuid.UUID, entry_id: uuid.UUID, data: RefundInput, user: Actor, db: DB
) -> CashEntry:
    venue, role = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    source = await refund_source(db, venue_id, entry_id)
    if source.method == "external":
        raise HTTPException(
            409,
            "Externe Zahlungen kann ausschließlich der Zahlungsadapter als zurückerstattet bestätigen.",
        )
    session = None
    if source.method == "cash":
        if data.session_id is None:
            raise HTTPException(
                422, "Offene Schichtkasse für die tatsächliche Barauszahlung erforderlich."
            )
        session = await session_for(db, venue_id, data.session_id, user.id, role, open_only=False)
    assert source.order_id is not None
    order = await svc.order_for_venue(db, venue_id, source.order_id, lock=True)
    await ledger_lock(db, venue_id)
    fingerprint = command_hash("refund", source.id, data)
    prior = await prior_entry(
        db, venue_id, data.request_key, fingerprint, legacy_command_hash("refund", source.id, data)
    )
    if prior:
        return prior
    from app.gastro.cancellation_money import (
        assert_checkout_reconciled,
        cancellation_refund_allocations,
    )

    if not data.confirmed:
        raise HTTPException(
            422,
            "Tatsächliche Auszahlung beziehungsweise Gutscheinrückbuchung ausdrücklich bestätigen.",
        )
    await assert_checkout_reconciled(db, order)
    allocations = cancellation_refund_allocations(
        order, source, await order_entries(db, order), data.cancellation_id, data.amount_cents
    )
    if session and (
        session.status != "open" or await drawer_balance(db, session.id) < data.amount_cents
    ):
        raise HTTPException(
            409, "Die Auszahlung benötigt eine offene Kasse mit ausreichendem Bargeld."
        )
    entry = CashEntry(
        venue_id=venue_id,
        session_id=session.id if session else None,
        order_id=order.id,
        original_id=source.id,
        kind="refund",
        method=source.method,
        amount_cents=-data.amount_cents,
        currency=venue.currency,
        allocations=allocations,
        reason=data.reason,
        actor_id=user.id,
        request_key=data.request_key,
        request_hash=fingerprint,
    )
    if source.method == "voucher":
        await restore_voucher(db, order, data.amount_cents, data.request_key, user.id)
    return await finish_refund(db, order, source, entry)


async def confirm_external_refund(
    db: AsyncSession, venue: Venue, data: ExternalRefundInput, device: Device
) -> CashEntry:
    if device.kind != "pos" or device.venue_id != venue.id or "payments:write" not in device.scopes:
        raise HTTPException(403, "Autorisierter Kassenadapter erforderlich.")
    source = await refund_source(db, venue.id, data.original_id)
    if source.method != "external":
        raise HTTPException(
            422, "Der Adapter darf nur eine externe Originalzahlung zurückerstatten."
        )
    assert source.order_id is not None
    order = await svc.order_for_venue(db, venue.id, source.order_id, lock=True)
    await ledger_lock(db, venue.id)
    fingerprint = command_hash("external-refund", source.id, data)
    prior = await prior_entry(
        db,
        venue.id,
        data.request_key,
        fingerprint,
        legacy_command_hash("external-refund", source.id, data),
    )
    if prior:
        return prior
    from app.gastro.cancellation_money import (
        assert_adapter_version,
        assert_checkout_reconciled,
        cancellation_refund_allocations,
    )

    if not data.confirmed:
        raise HTTPException(422, "Der Adapter muss die tatsächlich erfolgte Auszahlung bestätigen.")
    await assert_checkout_reconciled(db, order)
    assert_adapter_version(order, data.cancellation_version)
    if (
        await db.execute(
            select(CashEntry.id).where(
                CashEntry.venue_id == venue.id, CashEntry.external_reference == data.reference
            )
        )
    ).first():
        raise HTTPException(409, "Diese externe Erstattungsreferenz wurde bereits verwendet.")
    allocations = cancellation_refund_allocations(
        order, source, await order_entries(db, order), data.cancellation_id, data.amount_cents
    )
    if data.cancellation_version is not None:
        for row in allocations:
            row["cancellation_version"] = data.cancellation_version
    entry = CashEntry(
        venue_id=venue.id,
        order_id=order.id,
        original_id=source.id,
        kind="refund",
        method="external",
        amount_cents=-data.amount_cents,
        currency=venue.currency,
        allocations=allocations,
        reason=data.reason,
        device_id=device.id,
        external_reference=data.reference,
        request_key=data.request_key,
        request_hash=fingerprint,
    )
    return await finish_refund(db, order, source, entry)


@router.get(
    "/venues/{venue_id}/cash/reconciliation",
    response_model=ReconciliationRead,
    status_code=200,
    summary="Bestätigte Zahlarten, Retouren und Kassenunterschiede eines Betriebstages abstimmen",
)
async def reconciliation(venue_id: uuid.UUID, day: date, user: Actor, db: DB) -> ReconciliationRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    zone = ZoneInfo(venue.timezone)
    start = datetime.combine(day, time.min, zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
    rows = list(
        (
            await db.execute(
                select(CashEntry).where(
                    CashEntry.venue_id == venue.id,
                    CashEntry.created_at >= start,
                    CashEntry.created_at < end,
                    CashEntry.kind.in_(["sale", "refund"]),
                )
            )
        ).scalars()
    )
    receipts: dict[str, int] = {}
    refunds: dict[str, int] = {}
    tip_cents, tax_cents = 0, 0
    for row in rows:
        target = receipts if row.kind == "sale" else refunds
        target[row.method] = target.get(row.method, 0) + abs(row.amount_cents)
        sign = 1 if row.kind == "sale" else -1
        tip_cents += sign * sum(
            int(str(a["amount_cents"])) for a in row.allocations if a["kind"] == "tip"
        )
        tax_cents += sign * sum(int(str(a["tax_cents"])) for a in row.allocations)
    from app.gastro.payer_tip_models import PayerTipEntry

    additive_tips = (
        await db.execute(
            select(PayerTipEntry).where(
                PayerTipEntry.venue_id == venue.id,
                PayerTipEntry.created_at >= start,
                PayerTipEntry.created_at < end,
            )
        )
    ).scalars()
    for tip_entry in additive_tips:
        target = receipts if tip_entry.kind == "received" else refunds
        target["cash"] = target.get("cash", 0) + abs(tip_entry.amount_cents)
        tip_cents += tip_entry.amount_cents
    open_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(CashSession)
                .where(CashSession.venue_id == venue.id, CashSession.status != "closed")
            )
        ).scalar_one()
    )
    differences = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(CashSession.difference_cents), 0)).where(
                    CashSession.venue_id == venue.id,
                    CashSession.closed_at >= start,
                    CashSession.closed_at < end,
                )
            )
        ).scalar_one()
        or 0
    )
    return ReconciliationRead(
        day=day.isoformat(),
        receipts=receipts,
        refunds=refunds,
        tip_cents=tip_cents,
        tax_cents=tax_cents,
        open_sessions=open_count,
        differences_cents=differences,
    )
