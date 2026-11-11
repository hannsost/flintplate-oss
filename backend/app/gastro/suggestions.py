"""Vorschläge aus dem, was tatsächlich zusammen bestellt wurde.

Kein trainiertes Modell und keine Behauptung, eines zu sein. Gezählt wird, wie oft
zwei Artikel auf demselben Bon standen. Aus der Zahl folgt ein Anteil, und der
Anteil steht im Klartext neben dem Vorschlag: "in 12 von 37 Bestellungen mit
diesem Artikel". Das ist bei kleinen Datenmengen ehrlicher und sofort nützlich.

Gibt es noch keine Historie, schlägt der Dienst die meistbestellten Artikel vor
und sagt auch das. Artikel, die zu den Merkmalen des Gastes nicht passen, fallen
vorher heraus; ein Vorschlag, den jemand nicht essen darf, ist kein Vorschlag.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.models import GuestProfile, Order
from app.gastro.nutrition import check, items_of, payload_of
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])

WINDOW_DAYS = 180
MAX_ORDERS = 2000
MIN_SUPPORT = 2


class SuggestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=40)
    profile_id: uuid.UUID | None = None
    limit: int = Field(default=4, ge=1, le=12)


class Suggestion(BaseModel):
    item_id: uuid.UUID
    name: str
    price_cents: int
    together: int
    of_orders: int
    share: float
    reason: str


class SuggestResult(BaseModel):
    basis: str
    orders_seen: int
    filtered_out: int
    suggestions: list[Suggestion]


async def baskets(db: AsyncSession, venue_id: uuid.UUID) -> list[set[uuid.UUID]]:
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
    rows = (
        (
            await db.execute(
                select(Order.lines)
                .where(
                    Order.venue_id == venue_id,
                    Order.status != "cancelled",
                    Order.created_at >= since,
                )
                .order_by(Order.created_at.desc())
                .limit(MAX_ORDERS)
            )
        )
        .scalars()
        .all()
    )
    result: list[set[uuid.UUID]] = []
    for lines in rows:
        items = set()
        for line in lines or []:
            if isinstance(line, dict) and line.get("kind", "product") == "product":
                raw = line.get("item_id")
                if isinstance(raw, str):
                    try:
                        items.add(uuid.UUID(raw))
                    except ValueError:
                        continue
        if items:
            result.append(items)
    return result


async def suggest(
    db: AsyncSession, venue_id: uuid.UUID, data: SuggestInput, marker_keys: list[str]
) -> SuggestResult:
    history = await baskets(db, venue_id)
    anchors = set(data.item_ids)
    together: Counter[uuid.UUID] = Counter()
    matching_orders = 0
    popular: Counter[uuid.UUID] = Counter()
    for basket in history:
        popular.update(basket)
        hit = basket & anchors
        if not hit:
            continue
        matching_orders += 1
        for item in basket - anchors:
            together[item] += 1

    base = matching_orders
    ranked = [
        (item, count) for item, count in together.most_common() if count >= MIN_SUPPORT and base
    ]
    basis = "gemeinsame Bestellungen"
    if not ranked:
        basis = "häufig bestellt" if popular else "keine Historie"
        ranked = [(item, count) for item, count in popular.most_common() if item not in anchors]

    catalog = {row.id: row for row in await items_of(db, venue_id)}
    verdicts = {}
    if marker_keys:
        result = await check(db, venue_id, marker_keys, [item for item, _ in ranked])
        verdicts = {row.item_id: row for row in result.verdicts}

    suggestions: list[Suggestion] = []
    filtered = 0
    for item, count in ranked:
        row = catalog.get(item)
        if row is None or row.published is None:
            continue
        payload = payload_of(row)
        if not payload.available:
            continue
        verdict = verdicts.get(item)
        if verdict is not None and verdict.state != "ok":
            filtered += 1
            continue
        share = round(count / base, 2) if basis == "gemeinsame Bestellungen" and base else 0.0
        reason = (
            f"In {count} von {base} Bestellungen mit dieser Auswahl kam das dazu."
            if basis == "gemeinsame Bestellungen"
            else f"{count} mal bestellt in den letzten {WINDOW_DAYS} Tagen."
        )
        suggestions.append(
            Suggestion(
                item_id=item,
                name=payload.name,
                price_cents=payload.price_cents,
                together=count,
                of_orders=base,
                share=share,
                reason=reason,
            )
        )
        if len(suggestions) >= data.limit:
            break
    return SuggestResult(
        basis=basis,
        orders_seen=len(history),
        filtered_out=filtered,
        suggestions=suggestions,
    )


@router.post(
    "/venues/{venue_id}/suggestions",
    response_model=SuggestResult,
    status_code=200,
    summary="Passende Artikel aus bisherigen Bestellungen vorschlagen",
)
async def for_service(
    venue_id: uuid.UUID, data: SuggestInput, user: Actor, db: DB
) -> SuggestResult:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    keys: list[str] = []
    if data.profile_id is not None:
        from app.gastro.guestbook import profile_for

        profile = await profile_for(db, venue_id, data.profile_id)
        keys = list(profile.markers)
    return await suggest(db, venue_id, data, keys)


async def for_guest(
    db: AsyncSession, venue_id: uuid.UUID, account_id: uuid.UUID, data: SuggestInput
) -> SuggestResult:
    profile = (
        await db.execute(
            select(GuestProfile).where(
                GuestProfile.venue_id == venue_id, GuestProfile.account_id == account_id
            )
        )
    ).scalar_one_or_none()
    return await suggest(db, venue_id, data, list(profile.markers) if profile else [])
