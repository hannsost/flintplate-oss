"""Immutable equal-share budgets with provenance-aware remaining projections."""

from __future__ import annotations

import uuid
from typing import Literal, cast

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import cash
from app.gastro import service as svc
from app.gastro.equal_split_models import (
    EqualSplitPart,
    EqualSplitPartPayment,
    EqualSplitPlan,
    EqualSplitPlanAction,
)
from app.gastro.equal_split_schemas import (
    EqualActionInput,
    EqualPartRead,
    EqualPlanInput,
    EqualPlanRead,
)
from app.gastro.models import Venue
from app.gastro.payment_schemas import PaymentBlocker, PaymentQuoteInput, PaymentScope, UnitAmount
from app.gastro.payment_service import (
    MAX_MATRIX,
    Source,
    UnitKey,
    load_source,
    preview,
    row_key,
    spread,
)
from app.gastro.service_contexts import tab_for


async def plan_for(db: AsyncSession, venue_id: uuid.UUID, plan_id: uuid.UUID) -> EqualSplitPlan:
    plan = (
        await db.execute(
            select(EqualSplitPlan).where(
                EqualSplitPlan.id == plan_id, EqualSplitPlan.venue_id == venue_id
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, "Aufteilungsplan nicht gefunden.")
    return plan


async def plan_state(
    db: AsyncSession, venue: Venue, plan: EqualSplitPlan, *, lock: bool = False
) -> tuple[EqualPlanRead, Source, dict[uuid.UUID, dict[UnitKey, int]]]:
    parts = list(
        (
            await db.execute(
                select(EqualSplitPart)
                .where(EqualSplitPart.plan_id == plan.id)
                .order_by(EqualSplitPart.ordinal)
            )
        ).scalars()
    )
    payments = list(
        (
            await db.execute(
                select(EqualSplitPartPayment).where(
                    EqualSplitPartPayment.part_id.in_([part.id for part in parts])
                )
            )
        ).scalars()
    )
    action = (
        await db.execute(
            select(EqualSplitPlanAction).where(EqualSplitPlanAction.plan_id == plan.id)
        )
    ).scalar_one_or_none()
    source = await load_source(
        db,
        venue,
        PaymentScope(order_ids=sorted({row_key(row)[0] for row in plan.source_snapshot})),
        lock=lock,
    )
    original = {row_key(row): row for row in plan.source_snapshot}
    own_paid: dict[UnitKey, int] = {}
    budgets = {
        part.id: {row_key(row): int(str(row["amount_cents"])) for row in part.unit_budgets}
        for part in parts
    }
    for payment in payments:
        for row in payment.allocations:
            key, amount = row_key(row), int(str(row["amount_cents"]))
            own_paid[key] = own_paid.get(key, 0) + amount
            budgets[payment.part_id][key] -= amount
    comparable = (
        "gross_cents",
        "tax_cents",
        "cancelled",
        "assignment_id",
        "assignment_version",
        "guest_tab_id",
    )
    stale = False
    for key, before in original.items():
        current = source.units.get(key)
        if current is None:
            stale = True
            continue
        now = current.model_dump(mode="json")
        if any(
            before.get(field) != now.get(field) for field in comparable
        ) or current.paid_cents != int(str(before["paid_cents"])) + own_paid.get(key, 0):
            stale = True
        if current.remaining_cents != max(0, current.gross_cents - current.paid_cents):
            stale = True
    blockers = list(source.blockers)
    if stale:
        blockers.append(
            PaymentBlocker(
                code="plan_stale",
                message="Fremde Zahlung, Storno oder Gastzuordnung hat die Planquelle geändert; Rest bewusst neu aufteilen.",
            )
        )
    reads = [
        EqualPartRead(
            id=part.id,
            ordinal=part.ordinal,
            payer_tab_id=part.payer_tab_id,
            label=part.label,
            target_cents=part.target_cents,
            paid_cents=part.target_cents - sum(budgets[part.id].values()),
            remaining_cents=sum(budgets[part.id].values()),
            unit_budgets=[UnitAmount.model_validate(row) for row in part.unit_budgets],
        )
        for part in parts
    ]
    remaining = sum(p.remaining_cents for p in reads)
    status: str = "stale" if stale else "paid" if not remaining else "open"
    if action:
        status = "superseded" if action.action == "supersede" else "abandoned"
    result = EqualPlanRead(
        id=plan.id,
        root_plan_id=plan.root_plan_id,
        revision=plan.revision,
        created_at=plan.created_at,
        currency=plan.currency,
        source_hash=plan.source_hash,
        source_scope=PaymentQuoteInput.model_validate(plan.selection).scope,
        source_order_ids=sorted({row_key(row)[0] for row in plan.source_snapshot}),
        total_cents=plan.total_cents,
        paid_cents=plan.total_cents - remaining,
        remaining_cents=remaining,
        status=cast("LiteralPlanStatus", status),
        next_plan_id=action.next_plan_id if action else None,
        parts=reads,
        blockers=blockers,
    )
    return result, source, budgets


LiteralPlanStatus = Literal["open", "paid", "stale", "abandoned", "superseded"]


async def part_selection(
    db: AsyncSession,
    venue: Venue,
    part_ids: list[uuid.UUID],
    amount: int | None,
    *,
    lock: bool = False,
) -> tuple[Source, dict[UnitKey, int], dict[uuid.UUID, list[dict[str, JsonValue]]]]:
    parts = list(
        (
            await db.execute(
                select(EqualSplitPart)
                .where(EqualSplitPart.venue_id == venue.id, EqualSplitPart.id.in_(part_ids))
                .order_by(EqualSplitPart.ordinal)
            )
        ).scalars()
    )
    if {p.id for p in parts} != set(part_ids) or len({p.plan_id for p in parts}) != 1:
        raise HTTPException(404, "Offene Anteile eines einzigen Plans wählen.")
    plan = await plan_for(db, venue.id, parts[0].plan_id)
    state, source, budgets = await plan_state(db, venue, plan, lock=lock)
    if state.status != "open":
        raise HTTPException(
            409, "Aufteilungsplan ist bezahlt, veraltet oder beendet; Rest bewusst neu planen."
        )
    weights = [sum(budgets[p.id].values()) for p in parts]
    if any(weight <= 0 for weight in weights):
        raise HTTPException(409, "Ausgewählter Plananteil ist bereits vollständig bezahlt.")
    values = spread(sum(weights) if amount is None else amount, weights)
    caps: dict[UnitKey, int] = {}
    contributions: dict[uuid.UUID, list[dict[str, JsonValue]]] = {}
    for part, value in zip(parts, values, strict=True):
        keys = sorted(budgets[part.id])
        rows: list[dict[str, JsonValue]] = []
        for key, cents in zip(
            keys, spread(value, [budgets[part.id][key] for key in keys]), strict=True
        ):
            if cents:
                caps[key] = caps.get(key, 0) + cents
                rows.append(
                    {
                        "order_id": str(key[0]),
                        "line_id": key[1],
                        "unit": key[2],
                        "amount_cents": cents,
                    }
                )
        if rows:
            contributions[part.id] = rows
    return source, caps, contributions


async def create_plan(
    db: AsyncSession, venue: Venue, actor_id: uuid.UUID, data: EqualPlanInput
) -> EqualPlanRead:
    fingerprint = cash.command_hash("equal-plan", venue.id, data)
    prior = (
        await db.execute(
            select(EqualSplitPlan).where(
                EqualSplitPlan.venue_id == venue.id, EqualSplitPlan.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != fingerprint:
            raise HTTPException(409, "Vorgangs-ID gehört zu einer anderen Aufteilung.")
        return (await plan_state(db, venue, prior))[0]
    quote = await preview(db, venue, data.selection, actor_id, lock=True)
    if quote.read.quote_hash != data.quote_hash or quote.read.blockers:
        raise HTTPException(409, "Aufteilung benötigt eine aktuelle zahlbare Vorschau.")
    previous = await plan_for(db, venue.id, data.supersedes_id) if data.supersedes_id else None
    if (
        previous
        and (
            await db.execute(
                select(EqualSplitPlanAction.id).where(EqualSplitPlanAction.plan_id == previous.id)
            )
        ).first()
    ):
        raise HTTPException(409, "Dieser Plan hat bereits einen Abschluss oder Nachfolger.")
    if previous:
        original_keys = {row_key(row) for row in previous.source_snapshot}
        if not {(r.order_id, r.line_id, r.unit) for r in quote.read.allocations}.issubset(
            original_keys
        ):
            raise HTTPException(
                422, "Restplan darf nur Originaleinheiten des vorherigen Plans enthalten."
            )
    plan_id = uuid.uuid4()
    plan = EqualSplitPlan(
        id=plan_id,
        venue_id=venue.id,
        root_plan_id=previous.root_plan_id if previous else plan_id,
        supersedes_id=previous.id if previous else None,
        revision=previous.revision + 1 if previous else 1,
        actor_id=actor_id,
        request_key=data.request_key,
        request_hash=fingerprint,
        currency=venue.currency,
        total_cents=quote.read.receipt_amount_cents,
        source_hash=quote.read.source_hash,
        source_snapshot=[
            {
                **quote.source.units[(r.order_id, r.line_id, r.unit)].model_dump(mode="json"),
                "selected_cents": r.amount_cents,
            }
            for r in quote.read.allocations
        ],
        selection=data.selection.model_dump(mode="json"),
        reason=data.reason,
    )
    db.add(plan)
    await db.flush()
    keys = [(r.order_id, r.line_id, r.unit) for r in quote.read.allocations]
    caps = [r.amount_cents for r in quote.read.allocations]
    count = len(data.participants)
    cells = 0
    for ordinal, participant in enumerate(data.participants):
        label = participant.label
        if participant.payer_tab_id is not None:
            tab = await tab_for(db, venue.id, participant.payer_tab_id)
            label = label or tab.label[:80] or f"Gast {tab.number}"
        target = plan.total_cents // count + int(ordinal < plan.total_cents % count)
        amounts = spread(target, caps)
        rows: list[dict[str, JsonValue]] = [
            {"order_id": str(key[0]), "line_id": key[1], "unit": key[2], "amount_cents": cents}
            for key, cents in zip(keys, amounts, strict=True)
            if cents
        ]
        cells += len(rows)
        if cells > MAX_MATRIX:
            raise HTTPException(
                422, "Aufteilung überschreitet 10000 belegte Person-/Einheitsanteile."
            )
        caps = [before - paid for before, paid in zip(caps, amounts, strict=True)]
        db.add(
            EqualSplitPart(
                venue_id=venue.id,
                plan_id=plan.id,
                ordinal=ordinal,
                payer_tab_id=participant.payer_tab_id,
                label=label or f"Person {ordinal + 1}",
                target_cents=target,
                unit_budgets=rows,
            )
        )
    if previous:
        db.add(
            EqualSplitPlanAction(
                venue_id=venue.id,
                plan_id=previous.id,
                next_plan_id=plan.id,
                actor_id=actor_id,
                action="supersede",
                reason=data.reason,
                request_key=uuid.uuid5(data.request_key, "supersede"),
                request_hash=fingerprint,
            )
        )
    svc.event(
        db,
        venue.id,
        "payment.equal_plan_created",
        plan.id,
        {"total_cents": plan.total_cents, "participants": count, "revision": plan.revision},
        actor_id,
    )
    await db.flush()
    return (await plan_state(db, venue, plan))[0]


async def abandon(
    db: AsyncSession, venue: Venue, actor_id: uuid.UUID, plan_id: uuid.UUID, data: EqualActionInput
) -> EqualPlanRead:
    plan = await plan_for(db, venue.id, plan_id)
    fingerprint = cash.command_hash("equal-action", plan.id, data)
    prior = (
        await db.execute(
            select(EqualSplitPlanAction).where(
                EqualSplitPlanAction.venue_id == venue.id,
                EqualSplitPlanAction.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != fingerprint:
            raise HTTPException(409, "Vorgangs-ID gehört zu einem anderen Planabschluss.")
        return (await plan_state(db, venue, plan))[0]
    if (
        await db.execute(
            select(EqualSplitPlanAction.id).where(EqualSplitPlanAction.plan_id == plan.id)
        )
    ).first():
        raise HTTPException(409, "Plan ist bereits beendet.")
    db.add(
        EqualSplitPlanAction(
            venue_id=venue.id,
            plan_id=plan.id,
            actor_id=actor_id,
            action="abandon",
            reason=data.reason,
            request_key=data.request_key,
            request_hash=fingerprint,
        )
    )
    svc.event(
        db, venue.id, "payment.equal_plan_abandoned", plan.id, {"reason": data.reason}, actor_id
    )
    await db.flush()
    return (await plan_state(db, venue, plan))[0]
