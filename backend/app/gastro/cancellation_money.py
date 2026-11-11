"""Immutable cancellation claims, corrected receivables and explicit adapter acknowledgements.

Neither approval nor acknowledgement asserts a payment or sends a provider request.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.cancellation_money_models import CancellationCheckoutAck
from app.gastro.cancellation_projection import tip_line_id
from app.gastro.cash_models import CashEntry
from app.gastro.cash_schemas import CheckoutCorrectionInput, RefundClaimRead
from app.gastro.models import Device, Order, Venue

if TYPE_CHECKING:
    from app.gastro.cancellation_models import CancellationExecution, CancellationUnit


def selection_key(order: Order, line_id: str, unit: int) -> tuple[str, int]:
    return ("tip" if line_id == str(tip_line_id(order.id)) else line_id, unit)


def cancelled_keys(order: Order) -> set[tuple[str, int]]:
    return {selection_key(order, str(row.line_id), row.unit) for row in order.cancellation_units}


def cancellation_version(order: Order) -> int | None:
    return max((row.result_version for row in order.cancellation_executions), default=None)


def refund_claims(order: Order, entries: list[CashEntry]) -> list[RefundClaimRead]:
    claims: dict[tuple[uuid.UUID, uuid.UUID], RefundClaimRead] = {}
    returned: dict[tuple[str, str, str, int], int] = defaultdict(int)
    for entry in entries:
        if entry.kind == "refund":
            for row in entry.allocations:
                returned[
                    (
                        str(row.get("cancellation_id")),
                        str(entry.original_id),
                        str(row["line_id"]),
                        int(str(row["unit"])),
                    )
                ] += int(str(row["amount_cents"]))
    for unit in order.cancellation_units:
        key = selection_key(order, str(unit.line_id), unit.unit)
        for source in unit.refund_allocations:
            original_id = uuid.UUID(str(source["original_id"]))
            claim = claims.setdefault(
                (unit.execution_id, original_id),
                RefundClaimRead(
                    cancellation_id=unit.execution_id,
                    original_id=original_id,
                    method=str(source["method"]),
                    amount_cents=0,
                    tax_cents=0,
                    refunded_cents=0,
                    remaining_cents=0,
                    allocations=[],
                ),
            )
            amount, tax = int(str(source["amount_cents"])), int(str(source["tax_cents"]))
            paid = returned[(str(unit.execution_id), str(original_id), *key)]
            claim.amount_cents += amount
            claim.tax_cents += tax
            claim.refunded_cents += paid
            claim.remaining_cents += max(0, amount - paid)
            claim.allocations.append(
                {
                    "line_id": key[0],
                    "unit": key[1],
                    "amount_cents": amount,
                    "tax_cents": tax,
                    "refunded_cents": paid,
                }
            )
    return sorted(claims.values(), key=lambda row: (str(row.cancellation_id), str(row.original_id)))


async def checkout_required(db: AsyncSession, order: Order, entries: list[CashEntry]) -> bool:
    if not order.pos_requested:
        return False
    if any(row.kind == "sale" and row.method == "external" for row in entries):
        return True
    # Include revoked adapters: revocation cannot prove that an old terminal
    # stopped a previously dispatched payment operation.
    return (
        await db.execute(
            select(Device.id)
            .where(Device.venue_id == order.venue_id, Device.kind == "pos")
            .limit(1)
        )
    ).first() is not None


async def pending_checkout(db: AsyncSession, order: Order) -> bool:
    required = [
        row.id for row in order.cancellation_executions if row.checkout_reconciliation_required
    ]
    if not required:
        return False
    acknowledged = set(
        (
            await db.execute(
                select(CancellationCheckoutAck.execution_id).where(
                    CancellationCheckoutAck.venue_id == order.venue_id,
                    CancellationCheckoutAck.order_id == order.id,
                    CancellationCheckoutAck.execution_id.in_(required),
                )
            )
        ).scalars()
    )
    return any(key not in acknowledged for key in required)


async def assert_checkout_reconciled(db: AsyncSession, order: Order) -> None:
    if await pending_checkout(db, order):
        raise HTTPException(
            409,
            "Stornierter Kassenauftrag ist ungeklärt. Zuerst den autorisierten Adapter abgleichen; keine weitere Zahlung oder Auszahlung buchen.",
        )


def assert_adapter_version(order: Order, version: int | None) -> None:
    current = cancellation_version(order)
    if current is not None and version != current:
        raise HTTPException(
            409, "Der Adapter muss die aktuelle Stornoversion ausdrücklich bestätigen."
        )


async def preview_cancellation_money(
    db: AsyncSession, order: Order, selection: list[tuple[str, int]]
) -> dict[str, JsonValue]:
    from app.gastro import cash

    entries = await cash.order_entries(db, order)
    blockers: list[JsonValue] = []
    if order.paid_at is not None and not any(row.kind == "sale" for row in entries):
        blockers.append(
            "Historischer Zahlungsbeleg ohne zuordenbare Original-Sale-Positionen: zuerst dokumentiert abgleichen."
        )
    if order.voucher_cents and not any(
        row.kind == "sale" and row.method == "voucher" for row in entries
    ):
        entries.append(cash.voucher_tender(order, entries))
    units = {unit.key: unit for unit in cash.units_for(order, entries, virtual_voucher=False)}
    selected = {selection_key(order, str(line), index) for line, index in selection}
    if len(selected) != len(selection) or not selected or not selected.issubset(units):
        raise HTTPException(422, "Eindeutige bestehende Positionseinheiten erforderlich.")
    if selected & cancelled_keys(order):
        raise HTTPException(409, "Eine ausgewählte Einheit ist bereits storniert.")
    if ("tip", 0) in selected and order.tip_run_id is not None:
        blockers.append(
            "Bereits verteiltes Trinkgeld benötigt eine gesonderte Rückabwicklung der Verteilung."
        )
    rows: list[JsonValue] = []
    for key in sorted(selected):
        unit = units[key]
        paid = paid_tax = refunded = refunded_tax = 0
        allocations: list[JsonValue] = []
        for source in entries:
            if source.kind != "sale":
                continue
            for allocation in source.allocations:
                if (str(allocation["line_id"]), int(str(allocation["unit"]))) != key:
                    continue
                amount, tax = int(str(allocation["amount_cents"])), int(
                    str(allocation["tax_cents"])
                )
                prior_amount = prior_tax = 0
                for reversal in entries:
                    if reversal.kind == "refund" and reversal.original_id == source.id:
                        for previous in reversal.allocations:
                            if (str(previous["line_id"]), int(str(previous["unit"]))) == key:
                                prior_amount += int(str(previous["amount_cents"]))
                                prior_tax += int(str(previous["tax_cents"]))
                if not (0 <= prior_amount <= amount and 0 <= prior_tax <= tax):
                    raise HTTPException(
                        409, "Originalzahlung und Positionsrückzahlungen müssen abgeglichen werden."
                    )
                paid += amount
                paid_tax += tax
                refunded += prior_amount
                refunded_tax += prior_tax
                if amount > prior_amount:
                    allocations.append(
                        {
                            "original_id": str(source.id),
                            "method": source.method,
                            "amount_cents": amount - prior_amount,
                            "tax_cents": tax - prior_tax,
                        }
                    )
        if paid > unit.gross or paid_tax > unit.tax:
            raise HTTPException(
                409, "Die Originalzahlung überschreitet ihre Position; Abgleich erforderlich."
            )
        rows.append(
            {
                "line_id": str(tip_line_id(order.id)) if key[0] == "tip" else key[0],
                "unit": key[1],
                "gross_cents": unit.gross,
                "tax_cents": unit.tax,
                "name": unit.name,
                "kind": unit.kind,
                "unpaid_credit_cents": unit.gross - paid,
                "unpaid_tax_cents": unit.tax - paid_tax,
                "refund_due_cents": paid - refunded,
                "refund_tax_cents": paid_tax - refunded_tax,
                "already_refunded_cents": refunded,
                "already_refunded_tax_cents": refunded_tax,
                "refund_allocations": allocations,
            }
        )
    result: dict[str, JsonValue] = {
        "units": rows,
        "blockers": blockers,
        "checkout_reconciliation_required": await checkout_required(db, order, entries),
    }
    for field in (
        "gross_cents",
        "tax_cents",
        "unpaid_credit_cents",
        "unpaid_tax_cents",
        "refund_due_cents",
        "refund_tax_cents",
        "already_refunded_cents",
        "already_refunded_tax_cents",
    ):
        result[field] = sum(int(str(cast(dict[str, JsonValue], row)[field])) for row in rows)
    return result


def project_payment_status(order: Order, entries: list[CashEntry]) -> None:
    from app.gastro import cash

    if not order.cancellation_units:
        return
    units = cash.units_for(order, entries)
    remaining = sum(unit.remaining for unit in units)
    sales = sum(row.amount_cents for row in entries if row.kind == "sale")
    refunds = -sum(row.amount_cents for row in entries if row.kind == "refund")
    due = sum(row.remaining_cents for row in refund_claims(order, entries))
    if remaining:
        order.payment_status = (
            "partial" if sales else "requested" if order.pos_requested else "open"
        )
    elif due:
        order.payment_status = "refund_pending"
    elif all(unit.cancelled for unit in units):
        order.payment_status = "refunded" if refunds else "cancelled"
    else:
        order.payment_status = "paid" if order.paid_at is not None else "adjusted"


async def apply_cancellation_money(
    db: AsyncSession,
    order: Order,
    execution: CancellationExecution,
    units: list[CancellationUnit],
    actor_id: uuid.UUID,
) -> None:
    from app.gastro import cash

    await cash.ledger_lock(db, order.venue_id)
    entries = await cash.order_entries(db, order)
    # Materialization records a voucher already reserved on the original bill;
    # it neither charges a voucher again nor restores its balance.
    await cash.materialize_voucher(db, order, entries)
    await db.refresh(order, attribute_names=["cancellation_units", "cancellation_executions"])
    project_payment_status(order, entries)
    await db.flush()


def cancellation_refund_allocations(
    order: Order,
    source: CashEntry,
    entries: list[CashEntry],
    cancellation_id: uuid.UUID | None,
    amount: int,
) -> list[dict[str, JsonValue]]:
    from app.gastro import cash

    if cancellation_id is None:
        raise HTTPException(
            409,
            "Eine freigegebene positionsgenaue Stornierung ist für die Auszahlung erforderlich.",
        )
    claim = next(
        (
            row
            for row in refund_claims(order, entries)
            if row.cancellation_id == cancellation_id and row.original_id == source.id
        ),
        None,
    )
    if claim is None or amount > claim.remaining_cents:
        raise HTTPException(
            409,
            "Der Betrag übersteigt den offenen Anspruch dieses Stornos gegen die Originalzahlung.",
        )
    source_by_key = {
        (str(row["line_id"]), int(str(row["unit"]))): row for row in source.allocations
    }
    chosen = []
    for allocation in claim.allocations:
        key = str(allocation["line_id"]), int(str(allocation["unit"]))
        original = source_by_key[key]
        chosen.append(
            cash.Unit(
                *key,
                str(original["name"]),
                str(original["kind"]),
                int(str(allocation["amount_cents"])),
                int(str(allocation["tax_cents"])),
                int(str(allocation["refunded_cents"])),
            )
        )
    result = cash.allocate(amount, chosen)
    for row in result:
        row["cancellation_id"] = str(cancellation_id)
    return result


async def acknowledge_checkout(
    db: AsyncSession,
    venue: Venue,
    order_id: uuid.UUID,
    device: Device,
    data: CheckoutCorrectionInput,
) -> CancellationCheckoutAck:
    from app.gastro import cash
    from app.gastro import service as svc

    if device.kind != "pos" or device.venue_id != venue.id or "payments:write" not in device.scopes:
        raise HTTPException(403, "Autorisierter Kassenadapter erforderlich.")
    order = await svc.order_for_venue(db, venue.id, order_id, lock=True)
    fingerprint = cash.command_hash("checkout-correction", order.id, data)
    prior = (
        await db.execute(
            select(CancellationCheckoutAck).where(
                CancellationCheckoutAck.venue_id == venue.id,
                CancellationCheckoutAck.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.device_id != device.id or prior.request_hash != fingerprint:
            raise HTTPException(409, "Abgleich-ID wurde bereits anders verwendet.")
        return prior
    svc.check_version(order.version, data.version)
    assert_adapter_version(order, data.cancellation_version)
    execution = next(
        (
            row
            for row in order.cancellation_executions
            if row.result_version == data.cancellation_version
        ),
        None,
    )
    if execution is None:
        raise HTTPException(409, "Keine passende aktuelle Stornoversion vorhanden.")
    state = cash.balance_read(order, await cash.order_entries(db, order))
    if (data.remaining_cents, data.cancelled_cents) != (
        state.remaining_cents,
        state.cancelled_cents,
    ):
        raise HTTPException(
            409, "Der Adapterabgleich stimmt nicht mit der aktuellen Forderung überein."
        )
    if (
        await db.execute(
            select(CancellationCheckoutAck.id).where(
                CancellationCheckoutAck.execution_id == execution.id
            )
        )
    ).first():
        raise HTTPException(
            409, "Diese Kassenkorrektur wurde bereits abgeglichen; Originalvorgang erneut senden."
        )
    # Acknowledging the latest correction explicitly covers all previous
    # dispatches; persist one immutable acknowledgement for each pending one.
    acknowledged = set(
        (
            await db.execute(
                select(CancellationCheckoutAck.execution_id).where(
                    CancellationCheckoutAck.order_id == order.id
                )
            )
        ).scalars()
    )
    result: CancellationCheckoutAck | None = None
    for current in sorted(order.cancellation_executions, key=lambda row: row.result_version):
        if current.id in acknowledged:
            continue
        ack = CancellationCheckoutAck(
            venue_id=venue.id,
            order_id=order.id,
            execution_id=current.id,
            device_id=device.id,
            request_key=(
                data.request_key
                if current.id == execution.id
                else uuid.uuid5(data.request_key, str(current.id))
            ),
            request_hash=fingerprint,
            reference=data.reference,
            order_version=order.version,
            cancellation_version=data.cancellation_version,
            remaining_cents=data.remaining_cents,
            cancelled_cents=data.cancelled_cents,
        )
        db.add(ack)
        if current.id == execution.id:
            result = ack
    assert result is not None
    await db.flush()
    svc.event(
        db,
        venue.id,
        "pos.cancellation_reconciled",
        order.id,
        {
            "ack_id": str(result.id),
            "cancellation_version": data.cancellation_version,
            "reference": data.reference,
            "remaining_cents": data.remaining_cents,
        },
        device_id=device.id,
    )
    return result
