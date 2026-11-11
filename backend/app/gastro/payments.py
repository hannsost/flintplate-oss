"""Staff cash group, equal-plan and additive-tip API. No external charge transport."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from app.gastro import service as svc
from app.gastro.equal_split_models import EqualSplitPlan
from app.gastro.equal_split_schemas import EqualActionInput, EqualPlanInput, EqualPlanRead
from app.gastro.equal_split_service import abandon, create_plan, plan_for, plan_state
from app.gastro.payer_tip_models import PayerTipEntry
from app.gastro.payer_tip_schemas import PayerTipRead, PayerTipReturnInput
from app.gastro.payer_tip_service import read_tip, return_tip
from app.gastro.payment_models import PaymentGroup
from app.gastro.payment_schemas import (
    PaymentBalanceInput,
    PaymentBalanceRead,
    PaymentGroupInput,
    PaymentGroupRead,
    PaymentQuoteInput,
    PaymentQuoteRead,
)
from app.gastro.payment_service import balance, confirm, group_read, preview
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])


@router.post(
    "/venues/{venue_id}/payment-groups/balance",
    response_model=PaymentBalanceRead,
    status_code=200,
    summary="Originaleinheiten und Gästeanteile seitenweise anzeigen",
)
async def payment_balance(
    venue_id: uuid.UUID, data: PaymentBalanceInput, user: Actor, db: DB
) -> PaymentBalanceRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return await balance(db, venue, data)


@router.post(
    "/venues/{venue_id}/payment-groups/preview",
    response_model=PaymentQuoteRead,
    status_code=200,
    summary="Exakte Originalcentanteile vor tatsächlicher Barzahlung prüfen",
)
async def payment_preview(
    venue_id: uuid.UUID, data: PaymentQuoteInput, user: Actor, db: DB
) -> PaymentQuoteRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return (await preview(db, venue, data, user.id)).read


@router.post(
    "/venues/{venue_id}/payment-groups/cash",
    response_model=PaymentGroupRead,
    status_code=201,
    summary="Eine tatsächlich erhaltene Barzahlung atomar auf Originalbons buchen",
)
async def payment_cash(
    venue_id: uuid.UUID, data: PaymentGroupInput, user: Actor, db: DB
) -> PaymentGroupRead:
    venue, role = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    return await confirm(db, venue, role, user.id, data)


@router.get(
    "/venues/{venue_id}/payment-groups",
    response_model=list[PaymentGroupRead],
    status_code=200,
    summary="Unveränderliche Zahlgruppen lesen",
)
async def payment_groups(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    before_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[PaymentGroupRead]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    query = select(PaymentGroup).where(PaymentGroup.venue_id == venue_id)
    if before_id:
        query = query.where(PaymentGroup.id < before_id)
    return [
        await group_read(db, group)
        for group in (
            await db.execute(query.order_by(PaymentGroup.id.desc()).limit(limit))
        ).scalars()
    ]


@router.get(
    "/venues/{venue_id}/payment-groups/export",
    response_model=None,
    status_code=200,
    summary="Originalgruppen und zusätzliche Trinkgeldbelege eines Tages exportieren",
)
async def payment_export(
    venue_id: uuid.UUID, day: date, user: Actor, db: DB, format: Literal["json", "csv"] = "json"
) -> Response:
    import json

    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    zone = ZoneInfo(venue.timezone)
    start = datetime.combine(day, time.min, zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
    groups = [
        await group_read(db, group)
        for group in (
            await db.execute(
                select(PaymentGroup)
                .where(
                    PaymentGroup.venue_id == venue_id,
                    PaymentGroup.created_at >= start,
                    PaymentGroup.created_at < end,
                )
                .order_by(PaymentGroup.created_at, PaymentGroup.id)
            )
        ).scalars()
    ]
    tips = [
        await read_tip(db, entry)
        for entry in (
            await db.execute(
                select(PayerTipEntry)
                .where(
                    PayerTipEntry.venue_id == venue_id,
                    PayerTipEntry.created_at >= start,
                    PayerTipEntry.created_at < end,
                )
                .order_by(PayerTipEntry.created_at, PayerTipEntry.id)
            )
        ).scalars()
    ]
    if format == "json":
        return Response(
            json.dumps(
                {
                    "day": day.isoformat(),
                    "currency": venue.currency,
                    "groups": [g.model_dump(mode="json") for g in groups],
                    "payer_tips": [t.model_dump(mode="json") for t in tips],
                }
            ),
            media_type="application/json",
            headers={"Cache-Control": "private, no-store"},
        )
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        [
            "record_kind",
            "id",
            "group_id",
            "order_id",
            "original_id",
            "amount_cents",
            "received_cents",
            "change_cents",
            "currency",
        ]
    )
    for group in groups:
        writer.writerow(
            [
                "group_header",
                group.id,
                group.id,
                "",
                "",
                group.amount_cents,
                group.received_cents,
                group.change_cents,
                group.currency,
            ]
        )
        for entry in group.entries:
            writer.writerow(
                [
                    "original_sale",
                    entry.id,
                    group.id,
                    entry.order_id,
                    "",
                    entry.amount_cents,
                    "",
                    "",
                    group.currency,
                ]
            )
    for tip in tips:
        writer.writerow(
            [
                "payer_tip_" + tip.kind,
                tip.id,
                tip.payment_group_id,
                "",
                tip.original_id or "",
                tip.amount_cents,
                "",
                "",
                tip.currency,
            ]
        )
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="flintplate-groups-{day.isoformat()}.csv"',
        },
    )


@router.get(
    "/venues/{venue_id}/payment-groups/{group_id}",
    response_model=PaymentGroupRead,
    status_code=200,
    summary="Originalbeleg einer Zahlgruppe lesen",
)
async def payment_group(
    venue_id: uuid.UUID, group_id: uuid.UUID, user: Actor, db: DB
) -> PaymentGroupRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    group = (
        await db.execute(
            select(PaymentGroup).where(
                PaymentGroup.venue_id == venue_id, PaymentGroup.id == group_id
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(404, "Zahlgruppe nicht gefunden.")
    return await group_read(db, group)


@router.post(
    "/venues/{venue_id}/equal-split-plans",
    response_model=EqualPlanRead,
    status_code=201,
    summary="Gleichteilung mit festen Personenbudgets speichern",
)
async def equal_create(
    venue_id: uuid.UUID, data: EqualPlanInput, user: Actor, db: DB
) -> EqualPlanRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    return await create_plan(db, venue, user.id, data)


@router.get(
    "/venues/{venue_id}/equal-split-plans",
    response_model=list[EqualPlanRead],
    status_code=200,
    summary="Gespeicherte Aufteilungspläne fortsetzen",
)
async def equal_list(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    before_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[EqualPlanRead]:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    query = select(EqualSplitPlan).where(EqualSplitPlan.venue_id == venue_id)
    if before_id:
        query = query.where(EqualSplitPlan.id < before_id)
    return [
        (await plan_state(db, venue, plan))[0]
        for plan in (
            await db.execute(query.order_by(EqualSplitPlan.id.desc()).limit(limit))
        ).scalars()
    ]


@router.get(
    "/venues/{venue_id}/equal-split-plans/{plan_id}",
    response_model=EqualPlanRead,
    status_code=200,
    summary="Feste Plananteile und tatsächliche Zahlungen lesen",
)
async def equal_read(venue_id: uuid.UUID, plan_id: uuid.UUID, user: Actor, db: DB) -> EqualPlanRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return (await plan_state(db, venue, await plan_for(db, venue_id, plan_id)))[0]


@router.post(
    "/venues/{venue_id}/equal-split-plans/{plan_id}/actions",
    response_model=EqualPlanRead,
    status_code=201,
    summary="Aufteilungsplan bewusst schließen ohne Geld zu bewegen",
)
async def equal_action(
    venue_id: uuid.UUID, plan_id: uuid.UUID, data: EqualActionInput, user: Actor, db: DB
) -> EqualPlanRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    return await abandon(db, venue, user.id, plan_id, data)


@router.get(
    "/venues/{venue_id}/payer-tips",
    response_model=list[PayerTipRead],
    status_code=200,
    summary="Zusätzliche Trinkgeldquellen und tatsächliche Rückgaben lesen",
)
async def payer_tips(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    before_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[PayerTipRead]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    query = select(PayerTipEntry).where(PayerTipEntry.venue_id == venue_id)
    if before_id:
        query = query.where(PayerTipEntry.id < before_id)
    return [
        await read_tip(db, entry)
        for entry in (
            await db.execute(query.order_by(PayerTipEntry.id.desc()).limit(limit))
        ).scalars()
    ]


@router.post(
    "/venues/{venue_id}/payer-tips/{tip_id}/returns",
    response_model=PayerTipRead,
    status_code=201,
    summary="Tatsächliche Trinkgeldrückgabe durch verantwortliche Person bestätigen",
)
async def payer_tip_return(
    venue_id: uuid.UUID, tip_id: uuid.UUID, data: PayerTipReturnInput, user: Actor, db: DB
) -> PayerTipRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    return await return_tip(db, venue, user.id, tip_id, data)
