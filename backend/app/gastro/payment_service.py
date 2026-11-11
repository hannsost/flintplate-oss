"""Bounded original-unit selections and actual cash group confirmation."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import cast

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import cash
from app.gastro import service as svc
from app.gastro.cancellation_money import pending_checkout
from app.gastro.cash_models import CashEntry
from app.gastro.cash_schemas import EntryRead
from app.gastro.models import Membership, Order, Venue
from app.gastro.payer_tip_models import PayerTipEntry
from app.gastro.payment_models import PaymentGroup, PaymentGroupEntry
from app.gastro.payment_schemas import (
    PaymentAllocationRead,
    PaymentBalanceInput,
    PaymentBalanceRead,
    PaymentBlocker,
    PaymentGroupInput,
    PaymentGroupRead,
    PaymentOrderRead,
    PaymentQuoteInput,
    PaymentQuoteRead,
    PaymentScope,
    PaymentUnitRead,
)
from app.gastro.service_contexts import assignment_map, tab_for
from app.gastro.service_models import (
    GuestTab,
    ServiceRoundChild,
    ServiceUnitAssignment,
    ServiceVisit,
)

UnitKey = tuple[uuid.UUID, str, int]
MAX_ORDERS = 50
MAX_UNITS = 1000
MAX_MATRIX = 10000


def digest(value: JsonValue) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def spread(amount: int, weights: list[int]) -> list[int]:
    """Stable input order wins equal remainders; no synthetic price or tax base."""
    total = sum(weights)
    if amount < 0 or amount > total or any(weight < 0 for weight in weights):
        raise HTTPException(422, "Teilbetrag übersteigt die ausgewählten offenen Centanteile.")
    if not amount:
        return [0] * len(weights)
    result = [amount * weight // total for weight in weights]
    for index in sorted(range(len(weights)), key=lambda i: (-(amount * weights[i] % total), i))[
        : amount - sum(result)
    ]:
        result[index] += 1
    return result


def row_key(row: dict[str, JsonValue]) -> UnitKey:
    return uuid.UUID(str(row["order_id"])), str(row["line_id"]), int(str(row["unit"]))


@dataclass
class Source:
    orders: dict[uuid.UUID, Order]
    entries: dict[uuid.UUID, list[CashEntry]]
    units: dict[UnitKey, PaymentUnitRead]
    order_reads: list[PaymentOrderRead]
    blockers: list[PaymentBlocker]
    source_hash: str
    has_more: bool = False

    def snapshot(self, keys: list[UnitKey]) -> list[dict[str, JsonValue]]:
        return [self.units[key].model_dump(mode="json") for key in keys]


async def scope_tabs(
    db: AsyncSession, venue_id: uuid.UUID, scope: PaymentScope
) -> set[uuid.UUID] | None:
    if scope.visit_id is not None:
        if not (
            await db.execute(
                select(ServiceVisit.id).where(
                    ServiceVisit.venue_id == venue_id, ServiceVisit.id == scope.visit_id
                )
            )
        ).first():
            raise HTTPException(404, "Besuch nicht gefunden.")
        return set(
            (
                await db.execute(
                    select(GuestTab.id).where(
                        GuestTab.venue_id == venue_id, GuestTab.visit_id == scope.visit_id
                    )
                )
            ).scalars()
        )
    if scope.guest_tab_ids:
        tabs = set(
            (
                await db.execute(
                    select(GuestTab.id).where(
                        GuestTab.venue_id == venue_id, GuestTab.id.in_(scope.guest_tab_ids)
                    )
                )
            ).scalars()
        )
        if tabs != set(scope.guest_tab_ids):
            raise HTTPException(404, "Gastkontext nicht gefunden.")
        return tabs
    return None


async def load_source(
    db: AsyncSession,
    venue: Venue,
    scope: PaymentScope,
    *,
    selected_ids: set[uuid.UUID] | None = None,
    before: uuid.UUID | None = None,
    limit: int = MAX_ORDERS,
    page: bool = False,
    lock: bool = False,
) -> Source:
    tabs = await scope_tabs(db, venue.id, scope)
    latest = (
        select(
            ServiceUnitAssignment.order_id,
            ServiceUnitAssignment.line_id,
            ServiceUnitAssignment.unit,
            ServiceUnitAssignment.guest_tab_id,
        )
        .where(ServiceUnitAssignment.venue_id == venue.id)
        .distinct(
            ServiceUnitAssignment.order_id,
            ServiceUnitAssignment.line_id,
            ServiceUnitAssignment.unit,
        )
        .order_by(
            ServiceUnitAssignment.order_id,
            ServiceUnitAssignment.line_id,
            ServiceUnitAssignment.unit,
            ServiceUnitAssignment.version.desc(),
        )
        .subquery()
    )
    query = select(Order.id).where(Order.venue_id == venue.id)
    if tabs is not None:
        query = query.where(
            or_(
                Order.id.in_(select(latest.c.order_id).where(latest.c.guest_tab_id.in_(tabs))),
                Order.id.in_(
                    select(ServiceRoundChild.order_id).where(
                        ServiceRoundChild.venue_id == venue.id,
                        ServiceRoundChild.guest_tab_id.in_(tabs),
                    )
                ),
            )
        )
    elif scope.order_ids:
        query = query.where(Order.id.in_(scope.order_ids))
    else:
        raise HTTPException(422, "Besuch, Gäste oder Originalbons auswählen.")
    if selected_ids is not None:
        query = query.where(Order.id.in_(selected_ids))
    if before is not None:
        query = query.where(Order.id < before)
    ids = list((await db.execute(query.order_by(Order.id.desc()).limit(limit + 1))).scalars())
    more = len(ids) > limit
    if more and not page:
        raise HTTPException(
            409,
            "Mehr als 50 Originalbons: bitte Gäste oder konkrete Positionen in kleineren Zahlgruppen wählen.",
        )
    ids = ids[:limit]
    if selected_ids is not None and set(ids) != selected_ids:
        raise HTTPException(
            404, "Eine ausgewählte Originalposition gehört nicht zum gewählten Bereich."
        )
    if scope.order_ids and not page and selected_ids is None and set(ids) != set(scope.order_ids):
        raise HTTPException(404, "Originalbon nicht gefunden.")
    orders = {
        order_id: await svc.order_for_venue(db, venue.id, order_id, lock=lock)
        for order_id in sorted(ids)
    }
    assignments = await assignment_map(db, venue.id, list(orders))
    children = {
        child.order_id: child.guest_tab_id
        for child in (
            await db.execute(
                select(ServiceRoundChild).where(
                    ServiceRoundChild.venue_id == venue.id, ServiceRoundChild.order_id.in_(ids)
                )
            )
        ).scalars()
    }
    guest_ids = {row.guest_tab_id for row in assignments.values()} | set(children.values())
    guests = {
        tab.id: tab
        for tab in (
            await db.execute(
                select(GuestTab).where(GuestTab.venue_id == venue.id, GuestTab.id.in_(guest_ids))
            )
        ).scalars()
    }
    entries: dict[uuid.UUID, list[CashEntry]] = {}
    units: dict[UnitKey, PaymentUnitRead] = {}
    reads: list[PaymentOrderRead] = []
    blockers: list[PaymentBlocker] = []
    for order_id in ids:
        order = orders[order_id]
        entries[order_id] = await cash.order_entries(db, order)
        balance = cash.balance_read(order, entries[order_id])
        blocked = await pending_checkout(db, order)
        reads.append(
            PaymentOrderRead(
                order_id=order.id,
                number=order.number,
                version=order.version,
                cancellation_version=balance.cancellation_version,
                payment_status=order.payment_status,
                fulfillment_status=order.fulfillment_status,
                remaining_cents=balance.remaining_cents,
                refund_due_cents=balance.refund_due_cents,
                checkout_blocked=blocked,
            )
        )
        if order.currency != venue.currency:
            blockers.append(
                PaymentBlocker(
                    code="currency_mismatch",
                    message="Originalbon hat eine andere Währung; gesonderter Abgleich erforderlich.",
                    order_id=order.id,
                )
            )
        if blocked:
            blockers.append(
                PaymentBlocker(
                    code="checkout_reconciliation",
                    message="Offene Checkout-Korrektur: authentifizierten Adapterabgleich abwarten.",
                    order_id=order.id,
                )
            )
        if balance.remaining_cents:
            try:
                cash.payable(order)
            except HTTPException:
                blockers.append(
                    PaymentBlocker(
                        code="not_served",
                        message="Dieser Originalbon ist noch nicht vollständig serviert und zahlbar.",
                        order_id=order.id,
                    )
                )
        for unit in cash.units_for(order, entries[order_id]):
            assignment = assignments.get((order.id, unit.line_id, unit.unit))
            tab_id = (
                assignment.guest_tab_id
                if assignment
                else children.get(order.id) if unit.kind == "tip" else None
            )
            if tabs is not None and tab_id not in tabs:
                continue
            tab = guests.get(tab_id) if tab_id else None
            remaining = unit.remaining if balance.remaining_cents else 0
            row = PaymentUnitRead(
                order_id=order.id,
                order_number=order.number,
                line_id=unit.line_id,
                unit=unit.unit,
                name=unit.name,
                kind=unit.kind,
                gross_cents=unit.gross,
                tax_cents=unit.tax,
                paid_cents=unit.paid,
                remaining_cents=remaining,
                cancelled=unit.cancelled,
                guest_tab_id=tab_id,
                guest_label=(
                    (tab.label or ("Gemeinsam" if tab.kind == "shared" else f"Gast {tab.number}"))
                    if tab
                    else "Nicht zugeordnet"
                ),
                assignment_id=assignment.id if assignment else None,
                assignment_version=assignment.version if assignment else None,
            )
            units[(order.id, unit.line_id, unit.unit)] = row
    if len(units) > MAX_UNITS:
        raise HTTPException(
            409, "Mehr als 1000 Originaleinheiten: kleinere Bon-/Gastauswahl wählen."
        )
    fingerprint = digest(
        cast(
            JsonValue,
            {
                "orders": [r.model_dump(mode="json") for r in reads],
                "units": [u.model_dump(mode="json") for u in units.values()],
            },
        )
    )
    return Source(orders, entries, units, reads, blockers, fingerprint, more)


async def balance(db: AsyncSession, venue: Venue, data: PaymentBalanceInput) -> PaymentBalanceRead:
    source = await load_source(
        db, venue, data.scope, before=data.before_order_id, limit=data.limit, page=True
    )
    return PaymentBalanceRead(
        currency=venue.currency,
        source_hash=source.source_hash,
        orders=source.order_reads,
        units=list(source.units.values()),
        remaining_cents=sum(u.remaining_cents for u in source.units.values()),
        refund_due_cents=sum(o.refund_due_cents for o in source.order_reads),
        blockers=source.blockers,
        has_more=source.has_more,
        next_before_order_id=source.order_reads[-1].order_id if source.has_more else None,
    )


@dataclass
class Quote:
    read: PaymentQuoteRead
    source: Source
    part_allocations: dict[uuid.UUID, list[dict[str, JsonValue]]] = field(default_factory=dict)


async def preview(
    db: AsyncSession,
    venue: Venue,
    data: PaymentQuoteInput,
    actor_id: uuid.UUID,
    *,
    lock: bool = False,
) -> Quote:
    part_allocations: dict[uuid.UUID, list[dict[str, JsonValue]]] = {}
    if data.mode == "tip_only":
        source = Source({}, {}, {}, [], [], digest([]))
        caps: dict[UnitKey, int] = {}
    elif data.mode == "parts":
        from app.gastro.equal_split_service import part_selection

        source, caps, part_allocations = await part_selection(
            db, venue, data.part_ids, data.amount_cents, lock=lock
        )
    else:
        selected = {row.order_id for row in data.units} if data.mode == "units" else None
        source = await load_source(db, venue, data.scope, selected_ids=selected, lock=lock)
        caps = {
            key: unit.remaining_cents for key, unit in source.units.items() if unit.remaining_cents
        }
        if data.mode == "units":
            caps = {}
            for selection in data.units:
                key = selection.order_id, selection.line_id, selection.unit
                unit = source.units.get(key)
                if unit is None or not unit.remaining_cents:
                    raise HTTPException(
                        409, "Ausgewählte Einheit ist nicht mehr offen oder nicht zugeordnet."
                    )
                amount = (
                    selection.amount_cents
                    if selection.amount_cents is not None
                    else unit.remaining_cents
                )
                if amount > unit.remaining_cents:
                    raise HTTPException(409, "Ausgewählter Centanteil wurde inzwischen bezahlt.")
                caps[key] = amount
        if data.mode == "amount":
            keys = sorted(caps)
            caps = {
                key: amount
                for key, amount in zip(
                    keys, spread(data.amount_cents or 0, [caps[k] for k in keys]), strict=True
                )
                if amount
            }
    allocations: list[PaymentAllocationRead] = []
    for key in sorted(caps):
        amount = caps[key]
        if not amount:
            continue
        unit = source.units[key]
        if amount > unit.remaining_cents:
            raise HTTPException(
                409, "Plananteil übersteigt die tatsächlich noch offene Originalforderung."
            )
        allocations.append(
            PaymentAllocationRead(
                order_id=key[0],
                line_id=key[1],
                unit=key[2],
                name=unit.name,
                kind=unit.kind,
                amount_cents=amount,
                tax_cents=unit.tax_cents * (unit.paid_cents + amount) // unit.gross_cents
                - unit.tax_cents * unit.paid_cents // unit.gross_cents,
            )
        )
    if len({r.order_id for r in allocations}) > MAX_ORDERS or len(allocations) > MAX_UNITS:
        raise HTTPException(422, "Zahlgruppe überschreitet die Bon-/Einheitengrenze.")
    payer_label = data.payer_label
    if data.payer_tab_id is not None:
        tab = await tab_for(db, venue.id, data.payer_tab_id)
        payer_label = payer_label or tab.label[:80] or f"Gast {tab.number}"
    recipient_id = (data.recipient_id or actor_id) if data.new_tip_cents else None
    if (
        recipient_id is not None
        and not (
            await db.execute(
                select(Membership.id).where(
                    Membership.venue_id == venue.id,
                    Membership.user_id == recipient_id,
                    Membership.active.is_(True),
                )
            )
        ).first()
    ):
        raise HTTPException(404, "Trinkgeldempfänger arbeitet nicht in diesem Betrieb.")
    selected_ids = {row.order_id for row in allocations}
    blockers = [b for b in source.blockers if b.order_id in selected_ids]
    amount = sum(row.amount_cents for row in allocations)
    if not amount and data.new_tip_cents and data.mode != "tip_only":
        blockers.append(
            PaymentBlocker(
                code="tip_only_required",
                message="Ohne offene Bonforderung ausdrücklich Nur-Trinkgeld mit Gastkontext wählen.",
            )
        )
    if not amount and not data.new_tip_cents:
        blockers.append(
            PaymentBlocker(code="nothing_due", message="Keine offene Zahlung ausgewählt.")
        )
    quote_hash = digest(
        cast(
            JsonValue,
            {
                "input": data.model_dump(mode="json"),
                "source_hash": source.source_hash,
                "allocations": [row.model_dump(mode="json") for row in allocations],
                "recipient_id": str(recipient_id) if recipient_id else None,
                "payer_label": payer_label,
                "parts": {str(key): rows for key, rows in part_allocations.items()},
            },
        )
    )
    read = PaymentQuoteRead(
        quote_hash=quote_hash,
        source_hash=source.source_hash,
        currency=venue.currency,
        orders=source.order_reads,
        allocations=allocations,
        receipt_amount_cents=amount,
        new_tip_cents=data.new_tip_cents,
        amount_cents=amount + data.new_tip_cents,
        selected_remaining_cents=sum(u.remaining_cents for u in source.units.values()),
        payer_tab_id=data.payer_tab_id,
        payer_label=payer_label,
        recipient_id=recipient_id,
        blockers=blockers,
    )
    return Quote(read, source, part_allocations)


async def group_read(db: AsyncSession, group: PaymentGroup) -> PaymentGroupRead:
    from app.gastro.equal_split_models import EqualSplitPartPayment

    entries = list(
        (
            await db.execute(
                select(CashEntry)
                .join(PaymentGroupEntry, PaymentGroupEntry.entry_id == CashEntry.id)
                .where(PaymentGroupEntry.group_id == group.id)
                .order_by(CashEntry.order_id)
            )
        ).scalars()
    )
    tip_id = (
        await db.execute(
            select(PayerTipEntry.id).where(
                PayerTipEntry.payment_group_id == group.id, PayerTipEntry.kind == "received"
            )
        )
    ).scalar_one_or_none()
    parts = list(
        (
            await db.execute(
                select(EqualSplitPartPayment).where(EqualSplitPartPayment.group_id == group.id)
            )
        ).scalars()
    )
    return PaymentGroupRead(
        id=group.id,
        created_at=group.created_at,
        session_id=group.session_id,
        currency=group.currency,
        payer_tab_id=group.payer_tab_id,
        payer_label=group.payer_label,
        receipt_amount_cents=group.receipt_amount_cents,
        new_tip_cents=group.new_tip_cents,
        amount_cents=group.amount_cents,
        received_cents=group.received_cents,
        change_cents=group.change_cents,
        quote_hash=group.quote_hash,
        allocations=[PaymentAllocationRead.model_validate(a) for a in group.allocations],
        entries=[EntryRead.model_validate(e) for e in entries],
        tip_entry_id=tip_id,
        part_payments=[
            {
                "part_id": str(p.part_id),
                "amount_cents": p.amount_cents,
                "allocations": cast(JsonValue, p.allocations),
            }
            for p in parts
        ],
    )


async def confirm(
    db: AsyncSession, venue: Venue, role: str, actor_id: uuid.UUID, data: PaymentGroupInput
) -> PaymentGroupRead:
    fingerprint = cash.command_hash("payment-group", venue.id, data)
    prior = (
        await db.execute(
            select(PaymentGroup).where(
                PaymentGroup.venue_id == venue.id, PaymentGroup.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != fingerprint:
            raise HTTPException(409, "Vorgangs-ID wurde mit anderen Zahlungsdaten verwendet.")
        return await group_read(db, prior)
    session = await cash.session_for(db, venue.id, data.session_id, actor_id, role)
    await cash.ledger_lock(db, venue.id)
    quote = await preview(db, venue, data.quote, actor_id, lock=True)
    if quote.read.quote_hash != data.quote_hash:
        raise HTTPException(409, "Zahlungsquellen haben sich geändert; neue Vorschau erforderlich.")
    if quote.read.blockers:
        raise HTTPException(409, quote.read.blockers[0].message)
    if data.received_cents < quote.read.amount_cents:
        raise HTTPException(422, "Erhaltenes Bargeld reicht nicht für diesen Vorgang.")
    for selected_order_id in {row.order_id for row in quote.read.allocations}:
        cash.payable(quote.source.orders[selected_order_id])
    group = PaymentGroup(
        id=uuid.uuid4(),
        venue_id=venue.id,
        session_id=session.id,
        actor_id=actor_id,
        payer_tab_id=data.quote.payer_tab_id,
        payer_label=quote.read.payer_label,
        currency=venue.currency,
        receipt_amount_cents=quote.read.receipt_amount_cents,
        new_tip_cents=data.quote.new_tip_cents,
        amount_cents=quote.read.amount_cents,
        received_cents=data.received_cents,
        change_cents=data.received_cents - quote.read.amount_cents,
        request_key=data.request_key,
        request_hash=fingerprint,
        quote_hash=data.quote_hash,
        source_hash=quote.read.source_hash,
        source_snapshot=[
            {
                **quote.source.units[(row.order_id, row.line_id, row.unit)].model_dump(mode="json"),
                "selected_cents": row.amount_cents,
            }
            for row in quote.read.allocations
        ],
        quote=data.quote.model_dump(mode="json"),
        allocations=[row.model_dump(mode="json") for row in quote.read.allocations],
    )
    db.add(group)
    await db.flush()
    child_ids: dict[uuid.UUID, uuid.UUID] = {}
    for order_id in sorted({row.order_id for row in quote.read.allocations}):
        order = quote.source.orders[order_id]
        if not order.pos_requested:
            await svc.handoff_checkout(db, order, actor_id)
        entries = quote.source.entries[order_id]
        await cash.materialize_voucher(db, order, entries)
        allocations = [
            row.model_dump(mode="json", exclude={"order_id"})
            for row in quote.read.allocations
            if row.order_id == order_id
        ]
        entry = CashEntry(
            id=uuid.uuid5(group.id, str(order_id)),
            venue_id=venue.id,
            session_id=session.id,
            order_id=order_id,
            kind="sale",
            method="cash",
            amount_cents=sum(int(str(a["amount_cents"])) for a in allocations),
            received_cents=None,
            change_cents=None,
            currency=venue.currency,
            allocations=allocations,
            payer=quote.read.payer_label,
            actor_id=actor_id,
            request_key=uuid.uuid5(data.request_key, str(order_id)),
            request_hash=fingerprint,
        )
        await cash.finish_sale(db, order, entry, entries)
        db.add(
            PaymentGroupEntry(
                venue_id=venue.id, group_id=group.id, order_id=order_id, entry_id=entry.id
            )
        )
        child_ids[order_id] = entry.id
    if data.quote.new_tip_cents:
        db.add(
            PayerTipEntry(
                venue_id=venue.id,
                payment_group_id=group.id,
                session_id=session.id,
                kind="received",
                amount_cents=data.quote.new_tip_cents,
                currency=venue.currency,
                actor_id=actor_id,
                payer_tab_id=data.quote.payer_tab_id,
                payer_label=quote.read.payer_label,
                recipient_id=quote.read.recipient_id,
                request_key=uuid.uuid5(data.request_key, "payer-tip"),
                request_hash=fingerprint,
                reason="Tatsächlich erhaltenes zusätzliches Trinkgeld.",
            )
        )
    if quote.part_allocations:
        from app.gastro.equal_split_models import EqualSplitPartPayment

        for part_id, rows in quote.part_allocations.items():
            allocations = [
                {**row, "entry_id": str(child_ids[uuid.UUID(str(row["order_id"]))])} for row in rows
            ]
            db.add(
                EqualSplitPartPayment(
                    venue_id=venue.id,
                    group_id=group.id,
                    part_id=part_id,
                    amount_cents=sum(int(str(row["amount_cents"])) for row in rows),
                    allocations=allocations,
                )
            )
    svc.event(
        db,
        venue.id,
        "payment.group_confirmed",
        group.id,
        {
            "receipt_amount_cents": group.receipt_amount_cents,
            "new_tip_cents": group.new_tip_cents,
            "amount_cents": group.amount_cents,
            "session_id": str(session.id),
            "order_ids": [str(order_id) for order_id in child_ids],
        },
        actor_id,
    )
    await db.flush()
    return await group_read(db, group)
