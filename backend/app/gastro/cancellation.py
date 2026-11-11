"""Reviewed unit cancellations; an approval never asserts a cash payout."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import JsonValue
from sqlalchemy import exists, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.cancellation_models import (
    CancellationAcknowledgement,
    CancellationDecision,
    CancellationExecution,
    CancellationRequest,
    CancellationUnit,
)
from app.gastro.cancellation_projection import (
    line_key,
    remaining_lines,
    tip_line_id,
    update_fulfillment,
)
from app.gastro.cancellation_schemas import (
    CancellationAckInput,
    CancellationAckRead,
    CancellationCreateInput,
    CancellationDecisionInput,
    CancellationDecisionRead,
    CancellationExecutionRead,
    CancellationLineRead,
    CancellationPreviewInput,
    CancellationPreviewRead,
    CancellationRequestRead,
)
from app.gastro.models import Order
from app.gastro.reporting import ReportingDB
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])


def selection_data(data: CancellationPreviewInput) -> CancellationPreviewInput:
    return CancellationPreviewInput.model_validate(
        {
            key: value
            for key, value in data.model_dump(mode="json").items()
            if key in CancellationPreviewInput.model_fields
        }
    )


async def preview_for(
    db: AsyncSession, order: Order, data: CancellationPreviewInput
) -> CancellationPreviewRead:
    from app.gastro.cancellation_money import preview_cancellation_money

    svc.check_version(order.version, data.version)
    if order.status == "cancelled" and not order.cancellation_units:
        raise HTTPException(409, "Dieser historische Bon wurde bereits vollständig storniert.")
    available = {str(line["line_id"]): line for line in remaining_lines(order)}
    requested = {str(line.line_id): line.quantity for line in data.lines}
    if data.whole_order:
        requested = {key: int(str(line["quantity"])) for key, line in available.items()}
    originals = {line_key(order, index, line): line for index, line in enumerate(order.lines)}
    indices = {line_key(order, index, line): index for index, line in enumerate(order.lines)}
    cancelled = {(str(unit.line_id), unit.unit) for unit in order.cancellation_units}
    selection: list[tuple[str, int]] = []
    lines: list[CancellationLineRead] = []
    warnings: list[str] = []
    for key, quantity in requested.items():
        if key not in available or quantity > int(str(available[key]["quantity"])):
            raise HTTPException(409, "Die ausgewählte Positionsmenge ist nicht mehr verfügbar.")
        line = originals[key]
        count = int(str(line["quantity"]))
        chosen = [unit for unit in range(count) if (key, unit) not in cancelled][:quantity]
        selection.extend((key, unit) for unit in chosen)
        gross, tax = int(str(line["total_cents"])), int(str(line["tax_cents"]))
        state = str(line.get("preparation_status", "sent"))
        kind = str(line.get("kind", "product"))
        prepared = kind == "product" and state in {"preparing", "ready", "served"}
        lines.append(
            CancellationLineRead(
                line_index=indices[key],
                line_id=uuid.UUID(key),
                name=str(line["name"]),
                quantity=quantity,
                units=chosen,
                preparation_status=state,
                station=str(line.get("station", "kitchen")),
                kind=kind,
                gross_cents=sum(
                    gross * (unit + 1) // count - gross * unit // count for unit in chosen
                ),
                tax_cents=sum(tax * (unit + 1) // count - tax * unit // count for unit in chosen),
                stock_effect="consumption_retained" if prepared else "not_consumed",
            )
        )
        if (
            prepared
            and "Bereits produzierte Ware wird nicht automatisch zurückgelagert oder nochmals als Schwund ausgebucht."
            not in warnings
        ):
            warnings.append(
                "Bereits produzierte Ware wird nicht automatisch zurückgelagert oder nochmals als Schwund ausgebucht."
            )
        if kind in {"deposit", "packaging"}:
            warnings.append(f"{line['name']}: Geldkorrektur bestätigt keine physische Rückgabe.")
    if data.include_tip:
        tip_id = tip_line_id(order.id)
        if not order.tip_cents or (str(tip_id), 0) in cancelled:
            raise HTTPException(409, "Kein noch unkorrigiertes Trinkgeld vorhanden.")
        selection.append((str(tip_id), 0))
        lines.append(
            CancellationLineRead(
                line_id=tip_id,
                name="Trinkgeld",
                quantity=1,
                units=[0],
                preparation_status="served",
                station="service",
                kind="tip",
                gross_cents=order.tip_cents,
                tax_cents=0,
                stock_effect="not_consumed",
            )
        )
    if not selection:
        raise HTTPException(409, "Keine noch unkorrigierten Positionen vorhanden.")
    money = await preview_cancellation_money(db, order, selection)
    payload = {
        "order_id": str(order.id),
        "order_number": order.number,
        "order_version": order.version,
        "lines": [line.model_dump(mode="json") for line in lines],
        "gross_cents": sum(line.gross_cents for line in lines),
        "tax_cents": sum(line.tax_cents for line in lines),
        "money": money,
        "warnings": warnings,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {"preview": payload, "selection": data.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return CancellationPreviewRead.model_validate({**payload, "preview_hash": fingerprint})


async def execution_read(
    db: AsyncSession, execution: CancellationExecution
) -> CancellationExecutionRead:
    read = CancellationExecutionRead.model_validate(execution)
    ack = (
        await db.execute(
            select(CancellationAcknowledgement).where(
                CancellationAcknowledgement.execution_id == execution.id
            )
        )
    ).scalar_one_or_none()
    if ack:
        read.acknowledgement = CancellationAckRead.model_validate(ack)
    return read


async def request_read(db: AsyncSession, request: CancellationRequest) -> CancellationRequestRead:
    read = CancellationRequestRead.model_validate(request)
    decision = (
        await db.execute(
            select(CancellationDecision).where(CancellationDecision.request_id == request.id)
        )
    ).scalar_one_or_none()
    if decision:
        read.decision = CancellationDecisionRead.model_validate(decision)
    execution = (
        await db.execute(
            select(CancellationExecution).where(CancellationExecution.request_id == request.id)
        )
    ).scalar_one_or_none()
    if execution:
        read.execution = await execution_read(db, execution)
    return read


async def execute(
    db: AsyncSession,
    order: Order,
    request: CancellationRequest,
    decision: CancellationDecision,
    preview: CancellationPreviewRead,
) -> CancellationExecution:
    from app.gastro.cancellation_money import apply_cancellation_money

    blockers = preview.money.get("blockers", [])
    if blockers:
        raise HTTPException(
            409, {"message": "Die Stornofolgen müssen zuerst geklärt werden.", "blockers": blockers}
        )
    original = {
        "lines": order.lines,
        "total_cents": order.total_cents,
        "subtotal_cents": order.subtotal_cents,
        "discount_cents": order.discount_cents,
        "voucher_cents": order.voucher_cents,
        "tip_cents": order.tip_cents,
        "status": order.status,
        "fulfillment_status": order.fulfillment_status,
        "payment_status": order.payment_status,
        "pos_requested": order.pos_requested,
    }
    execution = CancellationExecution(
        id=uuid.uuid4(),
        venue_id=order.venue_id,
        order_id=order.id,
        request_id=request.id,
        decision_id=decision.id,
        actor_id=decision.actor_id,
        order_number=order.number,
        reason_code=request.reason_code,
        note=request.note,
        order_version=order.version,
        result_version=order.version + 1,
        lines=[line.model_dump(mode="json") for line in preview.lines],
        money=preview.money,
        original_snapshot=original,
        checkout_reconciliation_required=bool(
            preview.money.get("checkout_reconciliation_required", False)
        ),
        kitchen_required=any(line.kind == "product" for line in preview.lines),
    )
    order.cancellation_executions.append(execution)
    db.add(execution)
    # Both the financial hook and unit FK insertion need a durable-in-transaction ID.
    await db.flush()
    unit_rows = preview.money.get("units")
    if not isinstance(unit_rows, list):
        raise HTTPException(409, "Die Zahlungszuordnung der Stornierung ist unvollständig.")
    units: list[CancellationUnit] = []
    amounts = (
        "gross_cents",
        "tax_cents",
        "unpaid_credit_cents",
        "unpaid_tax_cents",
        "refund_due_cents",
        "refund_tax_cents",
        "already_refunded_cents",
        "already_refunded_tax_cents",
    )
    for raw in unit_rows:
        if not isinstance(raw, dict):
            raise HTTPException(409, "Ungültige Zahlungszuordnung.")
        unit = CancellationUnit(
            venue_id=order.venue_id,
            order_id=order.id,
            execution_id=execution.id,
            line_id=uuid.UUID(str(raw["line_id"])),
            unit=int(str(raw["unit"])),
            kind=str(raw["kind"]),
            name=str(raw["name"]),
            refund_allocations=raw["refund_allocations"],
            **{key: int(str(raw[key])) for key in amounts},
        )
        units.append(unit)
        order.cancellation_units.append(unit)
    await db.flush()
    await apply_cancellation_money(db, order, execution, units, decision.actor_id)
    update_fulfillment(order)
    order.version = execution.result_version
    prepared: list[dict[str, JsonValue]] = []
    source = {line_key(order, index, line): line for index, line in enumerate(order.lines)}
    for line in preview.lines:
        if line.stock_effect == "consumption_retained":
            prepared.append(
                {
                    **source[str(line.line_id)],
                    "quantity": line.quantity,
                    "total_cents": line.gross_cents,
                    "tax_cents": line.tax_cents,
                    "cancellation_id": str(execution.id),
                    "stock_effect": "consumption_retained",
                }
            )
    if prepared:
        svc.event(
            db,
            order.venue_id,
            "production.prepared_cancelled",
            order.id,
            {
                "reason": request.note,
                "lines": cast(JsonValue, prepared),
                "execution_id": str(execution.id),
            },
            decision.actor_id,
        )
    svc.event(
        db,
        order.venue_id,
        "order.cancellation_executed",
        order.id,
        {
            "request_id": str(request.id),
            "decision_id": str(decision.id),
            "execution_id": str(execution.id),
            "version": order.version,
            "lines": cast(JsonValue, execution.lines),
            "money": preview.money,
            "self_approved": decision.self_approved,
            "reason_code": request.reason_code,
            "reason": request.note,
        },
        decision.actor_id,
    )
    if order.fulfillment_status == "cancelled":
        svc.event(
            db,
            order.venue_id,
            "order.status_changed",
            order.id,
            {
                "status": "cancelled",
                "version": order.version,
                "reason": request.note,
                "execution_id": str(execution.id),
            },
            decision.actor_id,
        )
    await db.flush()
    return execution


async def create_request(
    db: AsyncSession,
    order: Order,
    data: CancellationCreateInput,
    actor_id: uuid.UUID,
    *,
    manager: bool,
    source: str = "staff",
) -> CancellationRequestRead:
    if data.approve and not manager:
        raise HTTPException(403, "Nur die Betriebsleitung darf Stornierungen freigeben.")
    prior = (
        await db.execute(
            select(CancellationRequest).where(
                CancellationRequest.venue_id == order.venue_id,
                CancellationRequest.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    fingerprint = svc.digest(data)
    if prior:
        if (
            prior.order_id != order.id
            or prior.requester_id != actor_id
            or prior.request_hash != fingerprint
            or prior.source != source
        ):
            raise HTTPException(409, "Diese Vorgangs-ID wurde bereits anders verwendet.")
        return await request_read(db, prior)
    selection = selection_data(data)
    preview = await preview_for(db, order, selection)
    if preview.preview_hash != data.preview_hash:
        raise HTTPException(409, "Die Stornovorschau wurde inzwischen geändert. Bitte neu prüfen.")
    request = CancellationRequest(
        id=uuid.uuid4(),
        venue_id=order.venue_id,
        order_id=order.id,
        order_number=order.number,
        requester_id=actor_id,
        original_actor_id=order.actor_id,
        request_key=data.request_key,
        request_hash=fingerprint,
        order_version=order.version,
        reason_code=data.reason_code,
        note=data.note,
        source=source,
        selection=selection.model_dump(mode="json"),
        preview=preview.model_dump(mode="json"),
    )
    db.add(request)
    await db.flush()
    svc.event(
        db,
        order.venue_id,
        "order.cancellation_requested",
        order.id,
        {
            "request_id": str(request.id),
            "version": order.version,
            "reason_code": data.reason_code,
            "reason": data.note,
            "preview_hash": preview.preview_hash,
        },
        actor_id,
    )
    if data.approve:
        decision = CancellationDecision(
            id=uuid.uuid4(),
            venue_id=order.venue_id,
            request_id=request.id,
            actor_id=actor_id,
            request_key=uuid.uuid5(data.request_key, "self-approval"),
            request_hash=fingerprint,
            decision="approve",
            note=data.note,
            self_approved=True,
        )
        db.add(decision)
        await db.flush()
        svc.event(
            db,
            order.venue_id,
            "order.cancellation_decided",
            order.id,
            {
                "request_id": str(request.id),
                "decision_id": str(decision.id),
                "decision": "approve",
                "self_approved": True,
                "source": source,
            },
            actor_id,
        )
        await execute(db, order, request, decision, preview)
    return await request_read(db, request)


@router.post(
    "/venues/{venue_id}/orders/{order_id}/cancellations/preview",
    response_model=CancellationPreviewRead,
    status_code=200,
    summary="Positionsgenaue Stornofolgen ohne Buchung prüfen",
)
async def preview_cancellation(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: CancellationPreviewInput, user: Actor, db: DB
) -> CancellationPreviewRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    return await preview_for(db, order, data)


@router.post(
    "/venues/{venue_id}/orders/{order_id}/cancellations",
    response_model=CancellationRequestRead,
    status_code=201,
    summary="Storno beantragen oder als Betriebsleitung ausdrücklich freigeben",
)
async def request_cancellation(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: CancellationCreateInput, user: Actor, db: DB
) -> CancellationRequestRead:
    _, role = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    return await create_request(db, order, data, user.id, manager=role == "manager")


@router.get(
    "/venues/{venue_id}/orders/{order_id}/cancellations",
    response_model=list[CancellationRequestRead],
    status_code=200,
    summary="Stornoanträge, Entscheidungen und Belege eines Bons",
)
async def order_cancellations(
    venue_id: uuid.UUID,
    order_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    limit: int = Query(default=50, ge=1, le=100),
    before: uuid.UUID | None = None,
) -> list[CancellationRequestRead]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    await svc.order_for_venue(db, venue_id, order_id)
    query = select(CancellationRequest).where(
        CancellationRequest.venue_id == venue_id, CancellationRequest.order_id == order_id
    )
    if before:
        cursor = (
            await db.execute(
                select(CancellationRequest).where(
                    CancellationRequest.id == before,
                    CancellationRequest.venue_id == venue_id,
                    CancellationRequest.order_id == order_id,
                )
            )
        ).scalar_one_or_none()
        if cursor is None:
            raise HTTPException(404, "Seitengrenze nicht gefunden.")
        query = query.where(
            tuple_(CancellationRequest.created_at, CancellationRequest.id)
            < (cursor.created_at, cursor.id)
        )
    rows = (
        (
            await db.execute(
                query.order_by(
                    CancellationRequest.created_at.desc(), CancellationRequest.id.desc()
                ).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [await request_read(db, row) for row in rows]


@router.get(
    "/venues/{venue_id}/cancellations",
    response_model=list[CancellationRequestRead],
    status_code=200,
    summary="Betriebliche Freigabeliste mit stabiler Seitennavigation",
)
async def list_cancellations(
    venue_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    pending_only: bool = True,
    limit: int = Query(default=50, ge=1, le=100),
    before: uuid.UUID | None = None,
) -> list[CancellationRequestRead]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    query = select(CancellationRequest).where(CancellationRequest.venue_id == venue_id)
    if pending_only:
        query = query.where(
            ~exists(
                select(CancellationDecision.id).where(
                    CancellationDecision.request_id == CancellationRequest.id
                )
            )
        )
    if before:
        cursor = (
            await db.execute(
                select(CancellationRequest).where(
                    CancellationRequest.id == before, CancellationRequest.venue_id == venue_id
                )
            )
        ).scalar_one_or_none()
        if cursor is None:
            raise HTTPException(404, "Seitengrenze nicht gefunden.")
        query = query.where(
            tuple_(CancellationRequest.created_at, CancellationRequest.id)
            < (cursor.created_at, cursor.id)
        )
    rows = (
        (
            await db.execute(
                query.order_by(
                    CancellationRequest.created_at.desc(), CancellationRequest.id.desc()
                ).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [await request_read(db, row) for row in rows]


@router.post(
    "/venues/{venue_id}/orders/{order_id}/cancellations/{request_id}/decision",
    response_model=CancellationRequestRead,
    status_code=201,
    summary="Geprüften Stornoantrag ausdrücklich freigeben oder ablehnen",
)
async def decide_cancellation(
    venue_id: uuid.UUID,
    order_id: uuid.UUID,
    request_id: uuid.UUID,
    data: CancellationDecisionInput,
    user: Actor,
    db: DB,
) -> CancellationRequestRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    request = (
        await db.execute(
            select(CancellationRequest).where(
                CancellationRequest.id == request_id,
                CancellationRequest.venue_id == venue_id,
                CancellationRequest.order_id == order.id,
            )
        )
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(404, "Stornoantrag nicht gefunden.")
    fingerprint = svc.digest(data)
    prior = (
        await db.execute(
            select(CancellationDecision).where(
                CancellationDecision.venue_id == venue_id,
                CancellationDecision.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if prior:
        if (
            prior.request_id != request.id
            or prior.actor_id != user.id
            or prior.request_hash != fingerprint
        ):
            raise HTTPException(409, "Diese Entscheidungs-ID wurde bereits anders verwendet.")
        return await request_read(db, request)
    if (
        await db.execute(
            select(CancellationDecision.id).where(CancellationDecision.request_id == request.id)
        )
    ).first():
        raise HTTPException(409, "Über diesen Antrag wurde bereits entschieden.")
    if data.version != request.order_version or data.preview_hash != request.preview.get(
        "preview_hash"
    ):
        raise HTTPException(409, "Die Entscheidung gehört nicht zum geprüften Antrag.")
    preview = CancellationPreviewRead.model_validate(request.preview)
    if data.decision == "approve":
        preview = await preview_for(
            db, order, CancellationPreviewInput.model_validate(request.selection)
        )
        if preview.preview_hash != data.preview_hash:
            raise HTTPException(
                409, "Zahlungs- oder Küchenstand geändert. Neuen Stornoantrag prüfen."
            )
    decision = CancellationDecision(
        id=uuid.uuid4(),
        venue_id=venue_id,
        request_id=request.id,
        actor_id=user.id,
        request_key=data.request_key,
        request_hash=fingerprint,
        decision=data.decision,
        note=data.note,
        self_approved=data.decision == "approve"
        and (user.id == request.requester_id or user.id == request.original_actor_id),
    )
    db.add(decision)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "order.cancellation_decided",
        order.id,
        {
            "request_id": str(request.id),
            "decision_id": str(decision.id),
            "decision": data.decision,
            "self_approved": decision.self_approved,
            "reason": data.note,
        },
        user.id,
    )
    if data.decision == "approve":
        await execute(db, order, request, decision, preview)
    return await request_read(db, request)


@router.get(
    "/venues/{venue_id}/cancellations/kitchen",
    response_model=list[CancellationExecutionRead],
    status_code=200,
    summary="Stornobelege für die Küche einschließlich noch unquittierter Hinweise",
)
async def kitchen_cancellations(
    venue_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    unacknowledged: bool = True,
    limit: int = Query(default=100, ge=1, le=100),
    before: uuid.UUID | None = None,
) -> list[CancellationExecutionRead]:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    query = select(CancellationExecution).where(
        CancellationExecution.venue_id == venue_id, CancellationExecution.kitchen_required.is_(True)
    )
    if unacknowledged:
        query = query.where(
            ~exists(
                select(CancellationAcknowledgement.id).where(
                    CancellationAcknowledgement.execution_id == CancellationExecution.id
                )
            )
        )
    if before:
        cursor = (
            await db.execute(
                select(CancellationExecution).where(
                    CancellationExecution.id == before, CancellationExecution.venue_id == venue_id
                )
            )
        ).scalar_one_or_none()
        if cursor is None:
            raise HTTPException(404, "Seitengrenze nicht gefunden.")
        query = query.where(
            tuple_(CancellationExecution.created_at, CancellationExecution.id)
            < (cursor.created_at, cursor.id)
        )
    rows = (
        (
            await db.execute(
                query.order_by(
                    CancellationExecution.created_at.desc(), CancellationExecution.id.desc()
                ).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [await execution_read(db, row) for row in rows]


@router.post(
    "/venues/{venue_id}/cancellations/{execution_id}/ack",
    response_model=CancellationAckRead,
    status_code=201,
    summary="Stornobeleg durch Küche oder Service nachvollziehbar quittieren",
)
async def acknowledge_cancellation(
    venue_id: uuid.UUID, execution_id: uuid.UUID, data: CancellationAckInput, user: Actor, db: DB
) -> CancellationAckRead:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    execution = (
        await db.execute(
            select(CancellationExecution).where(
                CancellationExecution.id == execution_id, CancellationExecution.venue_id == venue_id
            )
        )
    ).scalar_one_or_none()
    if execution is None or not execution.kitchen_required:
        raise HTTPException(404, "Küchenstornobeleg nicht gefunden.")
    fingerprint = hashlib.sha256(f"{execution_id}:{svc.digest(data)}".encode()).hexdigest()
    prior = (
        await db.execute(
            select(CancellationAcknowledgement).where(
                CancellationAcknowledgement.venue_id == venue_id,
                CancellationAcknowledgement.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if prior:
        if (
            prior.execution_id != execution.id
            or prior.actor_id != user.id
            or prior.request_hash != fingerprint
        ):
            raise HTTPException(409, "Diese Quittierungs-ID wurde bereits anders verwendet.")
        return CancellationAckRead.model_validate(prior)
    if (
        await db.execute(
            select(CancellationAcknowledgement.id).where(
                CancellationAcknowledgement.execution_id == execution.id
            )
        )
    ).first():
        raise HTTPException(409, "Der Stornobeleg wurde bereits quittiert.")
    acknowledgement = CancellationAcknowledgement(
        venue_id=venue_id,
        execution_id=execution.id,
        actor_id=user.id,
        request_key=data.request_key,
        request_hash=fingerprint,
    )
    db.add(acknowledgement)
    svc.event(
        db,
        venue_id,
        "order.cancellation_acknowledged",
        execution.order_id,
        {"execution_id": str(execution.id)},
        user.id,
    )
    await db.flush()
    return CancellationAckRead.model_validate(acknowledgement)


async def legacy_cancel(
    db: AsyncSession,
    order: Order,
    *,
    version: int,
    reason: str,
    actor_id: uuid.UUID | None,
    role: str,
) -> Order:
    """Keep the old whole-order endpoint, with the same durable approval evidence."""
    if role != "manager" or actor_id is None:
        raise HTTPException(403, "Stornierungen erfordern die Betriebsleitung.")
    if len(reason.strip()) < 3:
        raise HTTPException(422, "Bitte einen aussagekräftigen Stornogrund angeben.")
    key = uuid.uuid5(order.id, f"legacy-cancel:{actor_id}:{version}:{reason.strip()}")
    existing = (
        await db.execute(
            select(CancellationRequest.id).where(
                CancellationRequest.venue_id == order.venue_id,
                CancellationRequest.request_key == key,
                CancellationRequest.requester_id == actor_id,
            )
        )
    ).first()
    if existing:
        return order
    if order.voucher_cents and not order.pos_requested:
        raise HTTPException(409, "Gutscheinzahlung vor der Stornierung zurückbuchen.")
    selection = CancellationPreviewInput(
        version=version, whole_order=True, reason_code="other", note=reason.strip()
    )
    preview = await preview_for(db, order, selection)
    data = CancellationCreateInput(
        **selection.model_dump(), request_key=key, preview_hash=preview.preview_hash, approve=True
    )
    await create_request(db, order, data, actor_id, manager=True, source="legacy")
    return order


async def guest_cancel(db: AsyncSession, order: Order, actor_id: uuid.UUID) -> None:
    """No aggregate-status loophole: every remaining product must be unstarted."""
    from app.gastro.benefits import release_order_vouchers
    from app.gastro.cash_models import CashEntry

    if order.status == "cancelled":
        return
    has_payment = (
        await db.execute(
            select(CashEntry.id)
            .where(CashEntry.order_id == order.id, CashEntry.kind == "sale")
            .limit(1)
        )
    ).first()
    if (
        order.pos_requested
        or order.paid_at is not None
        or has_payment
        or order.status != "sent"
        or any(
            line.get("kind", "product") == "product"
            and line.get("preparation_status", "sent") != "sent"
            for line in remaining_lines(order)
        )
    ):
        raise HTTPException(
            409, "Zubereitung oder Abrechnung hat begonnen. Bitte beim Service ein Storno anfragen."
        )
    await release_order_vouchers(db, order, actor_id)
    selection = CancellationPreviewInput(
        version=order.version,
        whole_order=True,
        reason_code="guest_request",
        note="Vom Gast vor Zubereitungsbeginn zurückgenommen",
    )
    preview = await preview_for(db, order, selection)
    data = CancellationCreateInput(
        **selection.model_dump(),
        request_key=uuid.uuid5(order.id, f"guest-cancel:{actor_id}"),
        preview_hash=preview.preview_hash,
        approve=True,
    )
    await create_request(db, order, data, actor_id, manager=True, source="guest")
