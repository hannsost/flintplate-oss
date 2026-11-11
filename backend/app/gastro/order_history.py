"""Bounded order search and complete, paginated journal exports."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select

from app.gastro import service as svc
from app.gastro.models import Event, Order
from app.gastro.reporting import ReportingDB
from app.gastro.router import Actor, private_response
from app.gastro.schemas import EventRead, OrderRead

router = APIRouter(dependencies=[Depends(private_response)])


class OrderHistoryPage(BaseModel):
    items: list[OrderRead]
    next_before: uuid.UUID | None
    has_more: bool


class AuditEventPage(BaseModel):
    items: list[EventRead]
    through_sequence: int
    next_after: int
    has_more: bool


@router.get(
    "/venues/{venue_id}/orders/{order_id}",
    response_model=OrderRead,
    status_code=200,
    summary="Aktuellen Bonstand einschließlich abgeschlossener Bestellungen lesen",
)
async def order_detail(
    venue_id: uuid.UUID, order_id: uuid.UUID, db: ReportingDB, user: Actor
) -> OrderRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return OrderRead.model_validate(await svc.order_for_venue(db, venue_id, order_id))


@router.get(
    "/venues/{venue_id}/order-history",
    response_model=OrderHistoryPage,
    status_code=200,
    summary="Alle Bons einschließlich abgeschlossener und stornierter Bestellungen durchsuchen",
)
async def order_history(
    venue_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    q: Annotated[str, Query(max_length=80)] = "",
    day: date | None = None,
    table_id: uuid.UUID | None = None,
) -> OrderHistoryPage:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    query = select(Order).where(Order.venue_id == venue_id)
    if before is not None:
        cursor = await svc.order_for_venue(db, venue_id, before)
        query = query.where(
            or_(
                Order.created_at < cursor.created_at,
                and_(Order.created_at == cursor.created_at, Order.id < cursor.id),
            )
        )
    if q.strip():
        # Search literally; '%' and '_' must not become user-controlled wildcards.
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Order.number.ilike(f"%{term}%", escape="\\"))
    if day is not None:
        if day in {date.min, date.max}:
            raise HTTPException(422, "Dieses Datum liegt außerhalb des unterstützten Zeitraums.")
        zone = ZoneInfo(venue.timezone)
        start = datetime.combine(day, time.min, zone).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
        query = query.where(Order.created_at >= start, Order.created_at < end)
    if table_id is not None:
        query = query.where(Order.table_id == table_id)
    rows = list(
        (
            await db.execute(
                query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return OrderHistoryPage(
        items=[OrderRead.model_validate(row) for row in rows],
        next_before=rows[-1].id if has_more else None,
        has_more=has_more,
    )


@router.get(
    "/venues/{venue_id}/audit-events",
    response_model=AuditEventPage,
    status_code=200,
    summary="Journal bis zu einem festen Sequenzstand vollständig seitenweise lesen",
)
async def audit_events(
    venue_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    after: Annotated[int, Query(ge=0)] = 0,
    through: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> AuditEventPage:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    latest = int(
        (
            await db.execute(
                select(func.coalesce(func.max(Event.sequence), 0)).where(Event.venue_id == venue_id)
            )
        ).scalar_one()
    )
    upper = latest if through is None else through
    if upper > latest or after > upper:
        raise HTTPException(422, "Ungültiger Journalbereich; Export bitte neu beginnen.")
    rows = list(
        (
            await db.execute(
                select(Event)
                .where(
                    Event.venue_id == venue_id,
                    Event.sequence > after,
                    Event.sequence <= upper,
                )
                .order_by(Event.sequence)
                .limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return AuditEventPage(
        items=[EventRead.model_validate(row) for row in rows],
        through_sequence=upper,
        next_after=rows[-1].sequence if rows else after,
        has_more=has_more,
    )
