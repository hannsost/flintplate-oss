from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from pydantic import BaseModel, JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.gastro.models import Device, DiningTable, Event, Membership, MenuItem, Order, Venue
from app.gastro.schemas import LineRead, MenuPayload, MenuPublic, OrderInput, OrderRead, StateInput
from app.users.models import User

MANAGERS = {"manager"}
SERVICE = {"manager", "service"}
KITCHEN = {"manager", "service", "kitchen"}
ACTIVE_ORDER_STATES = ("sent", "preparing", "ready", "served")


def digest(data: BaseModel) -> str:
    payload = data.model_dump(mode="json")
    if isinstance(data, OrderInput):
        # Course 1 was implicit before stable kitchen lines were introduced.
        # Keep old pending device/browser request keys replayable across upgrades.
        for line in payload["lines"]:
            if line.get("course") == 1:
                line.pop("course", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def check_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise HTTPException(
            409, "Der Stand wurde inzwischen geändert. Bitte neu laden und Änderungen prüfen."
        )


async def venue_access(
    db: AsyncSession,
    user: User,
    venue_id: uuid.UUID,
    roles: set[str] | None = None,
    *,
    lock: bool = False,
) -> tuple[Venue, str]:
    query = (
        select(Venue, Membership.role)
        .join(Membership, Membership.venue_id == Venue.id)
        .join(Customer, Customer.id == Venue.tenant_id)
        .where(
            Venue.id == venue_id,
            Venue.tenant_id == user.tenant_id,
            Membership.user_id == user.id,
            Membership.active.is_(True),
            Customer.status.in_(["active", "trial"]),
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        # Serialize venue mutations without blocking foreign-key KEY SHARE locks.
        query = query.with_for_update(of=Venue, key_share=True)
    row = (await db.execute(query)).first()
    if row is None:
        raise HTTPException(404, "Betriebsstätte nicht gefunden oder kein Zugriff.")
    venue, role = row
    if roles is not None and role not in roles:
        raise HTTPException(403, "Für diese Aktion fehlt das Recht in dieser Betriebsstätte.")
    return venue, role


async def table_for_venue(
    db: AsyncSession, venue_id: uuid.UUID, table_id: uuid.UUID, *, lock: bool = False
) -> DiningTable:
    query = (
        select(DiningTable)
        .where(DiningTable.id == table_id, DiningTable.venue_id == venue_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    table = (await db.execute(query)).scalar_one_or_none()
    if table is None:
        raise HTTPException(404, "Tisch nicht gefunden.")
    return table


async def validate_combinable(
    db: AsyncSession,
    venue_id: uuid.UUID,
    partners: list[str],
    table_id: uuid.UUID | None = None,
) -> None:
    """Combinable partners must be real resources of this venue, and never the table itself."""
    if not partners:
        return
    ids = {uuid.UUID(entry) for entry in partners}
    if table_id is not None and table_id in ids:
        raise HTTPException(422, "Ein Tisch kann nicht mit sich selbst kombiniert werden.")
    known = set(
        (
            await db.execute(
                select(DiningTable.id).where(
                    DiningTable.venue_id == venue_id, DiningTable.id.in_(ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if known != ids:
        raise HTTPException(404, "Ein kombinierbarer Tisch gehört nicht zu dieser Betriebsstätte.")


async def menu_for_venue(
    db: AsyncSession, venue_id: uuid.UUID, item_id: uuid.UUID, *, lock: bool = False
) -> MenuItem:
    query = (
        select(MenuItem)
        .where(MenuItem.id == item_id, MenuItem.venue_id == venue_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    item = (await db.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Artikel nicht gefunden.")
    return item


async def order_for_venue(
    db: AsyncSession, venue_id: uuid.UUID, order_id: uuid.UUID, *, lock: bool = False
) -> Order:
    query = (
        select(Order)
        .where(Order.id == order_id, Order.venue_id == venue_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    order = (await db.execute(query)).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Bestellung nicht gefunden.")
    return order


def event(
    db: AsyncSession,
    venue_id: uuid.UUID,
    kind: str,
    aggregate_id: uuid.UUID,
    payload: dict[str, JsonValue],
    user_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
) -> None:
    db.add(
        Event(
            venue_id=venue_id,
            kind=kind,
            aggregate_id=aggregate_id,
            payload=payload,
            actor_id=user_id,
            device_id=device_id,
        )
    )


async def catalog(db: AsyncSession, venue_id: uuid.UUID) -> list[MenuPublic]:
    items = (
        (
            await db.execute(
                select(MenuItem)
                .where(MenuItem.venue_id == venue_id, MenuItem.published.is_not(None))
                .order_by(MenuItem.sku)
            )
        )
        .scalars()
        .all()
    )
    return [
        MenuPublic(
            id=item.id,
            sku=item.sku,
            version=item.published_version or 1,
            # The public snapshot is a contract with FireFlint: costs and the
            # internal ingredient list stay out of it.
            **MenuPayload.model_validate(item.published).model_dump(
                exclude={"cost_cents", "ingredients", "contains"}
            ),
        )
        for item in items
    ]


async def snapshot_lines(
    db: AsyncSession,
    venue: Venue,
    data: OrderInput,
    *,
    source_rows: dict[str, int] | None = None,
) -> tuple[list[dict[str, JsonValue]], int]:
    from app.gastro.recipes import RecipeVersion

    items = (
        (
            await db.execute(
                select(MenuItem)
                .where(
                    MenuItem.venue_id == venue.id,
                    MenuItem.id.in_([line.item_id for line in data.lines]),
                )
                .order_by(MenuItem.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    from app.gastro.station_service import order_snapshot, resolve_stations

    index = {item.id: item for item in items}
    payloads = {
        item.id: MenuPayload.model_validate(item.published)
        for item in items
        if item.published is not None
    }
    stations = await resolve_stations(
        db, venue.id, (payload.station for payload in payloads.values()), preparation=True
    )
    lines: list[dict[str, JsonValue]] = []
    total = 0
    for source_index, line in enumerate(data.lines):
        item = index.get(line.item_id)
        if item is None or item.published is None:
            raise HTTPException(404, "Ein Artikel ist nicht auf der veröffentlichten Karte.")
        check_version(item.published_version or 1, line.menu_version)
        payload = payloads[item.id]
        if not payload.available:
            raise HTTPException(409, f"{payload.name} ist derzeit nicht verfügbar.")
        line_total = payload.price_cents * line.quantity
        tax = int(
            (Decimal(line_total) * payload.tax_rate_bps / (10000 + payload.tax_rate_bps)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        recipe_id = (
            await db.execute(
                select(RecipeVersion.id)
                .where(
                    RecipeVersion.venue_id == venue.id,
                    RecipeVersion.menu_item_id == item.id,
                    RecipeVersion.menu_version <= item.published_version,
                )
                .order_by(RecipeVersion.menu_version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        snapshot = LineRead(
            recipe_id=recipe_id,
            line_id=uuid.uuid4(),
            course=line.course,
            item_id=item.id,
            sku=item.sku,
            name=payload.name,
            menu_version=line.menu_version,
            quantity=line.quantity,
            price_cents=payload.price_cents,
            tax_rate_bps=payload.tax_rate_bps,
            tax_cents=tax,
            total_cents=line_total,
            allergens=payload.allergens,
            station=payload.station,
            station_snapshot=order_snapshot(payload, stations[payload.station]),
            note=line.note,
        )
        if source_rows is not None:
            source_rows[str(snapshot.line_id)] = source_index
        lines.append(snapshot.model_dump(mode="json"))
        total += line_total
        packaging = payload.takeaway_packaging if data.fulfillment == "takeaway" else None
        if packaging:
            for kind, name, price, rate in (
                ("packaging", packaging.name, packaging.price_cents, packaging.tax_rate_bps),
                (
                    "deposit",
                    f"Pfand · {packaging.name}",
                    packaging.deposit_cents,
                    packaging.deposit_tax_rate_bps,
                ),
            ):
                if not price:
                    continue
                gross = price * line.quantity
                extra = snapshot.model_copy(
                    update={
                        "line_id": uuid.uuid4(),
                        "recipe_id": None,
                        "kind": kind,
                        "sku": f"{item.sku}-{kind}",
                        "name": name,
                        "price_cents": price,
                        "total_cents": gross,
                        "tax_rate_bps": rate,
                        "tax_cents": int(
                            (Decimal(gross) * rate / (10000 + rate)).quantize(
                                Decimal("1"), rounding=ROUND_HALF_UP
                            )
                        ),
                        "allergens": [],
                        "station": "service",
                        "station_snapshot": None,
                        "note": "Mehrweg" if packaging.reusable else "Einweg",
                    }
                )
                if source_rows is not None:
                    source_rows[str(extra.line_id)] = source_index
                lines.append(extra.model_dump(mode="json"))
                total += gross

    if total > 100000000:
        raise HTTPException(422, "Bestellsumme ist zu hoch.")
    return lines, total


async def create_order(
    db: AsyncSession,
    venue: Venue,
    data: OrderInput,
    *,
    user_id: uuid.UUID | None = None,
    device: Device | None = None,
    customer_id: uuid.UUID | None = None,
    source_rows: dict[str, int] | None = None,
) -> Order:
    # Lock the venue before checking the request key: concurrent device retries
    # cannot produce two kitchen tickets or two order numbers.
    await db.execute(select(Venue).where(Venue.id == venue.id).with_for_update(key_share=True))
    prior = (
        await db.execute(
            select(Order).where(Order.venue_id == venue.id, Order.request_key == data.request_key)
        )
    ).scalar_one_or_none()
    fingerprint = digest(data)
    if prior:
        if prior.request_hash != fingerprint or prior.customer_id != customer_id:
            raise HTTPException(
                409, "Diese Vorgangs-ID wurde bereits für eine andere Bestellung verwendet."
            )
        return prior
    if data.table_id:
        table = await table_for_venue(db, venue.id, data.table_id)
        if data.guests > table.seats:
            raise HTTPException(422, "Die Gästezahl überschreitet die Sitzplätze des Tisches.")
    lines, total = await snapshot_lines(db, venue, data, source_rows=source_rows)
    number = (
        int(
            (
                await db.execute(
                    select(func.count()).select_from(Order).where(Order.venue_id == venue.id)
                )
            ).scalar_one()
        )
        + 1001
    )
    order = Order(
        venue_id=venue.id,
        table_id=data.table_id,
        actor_id=user_id,
        device_id=device.id if device else None,
        request_key=data.request_key,
        request_hash=fingerprint,
        number=f"FP-{number}",
        lines=lines,
        total_cents=total,
        subtotal_cents=total,
        fulfillment=data.fulfillment,
        customer_id=customer_id,
        currency=venue.currency,
        guests=data.guests,
        note=data.note,
    )
    db.add(order)
    await db.flush()
    event(
        db,
        venue.id,
        "order.created",
        order.id,
        OrderRead.model_validate(order).model_dump(mode="json"),
        user_id,
        device.id if device else None,
    )
    return order


async def transition_order(
    db: AsyncSession,
    venue_id: uuid.UUID,
    order_id: uuid.UUID,
    data: StateInput,
    role: str,
    *,
    user_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
) -> Order:
    venue = (
        await db.execute(select(Venue).where(Venue.id == venue_id).with_for_update(key_share=True))
    ).scalar_one()
    order = await order_for_venue(db, venue_id, order_id, lock=True)
    if data.status == "cancelled":
        from app.gastro.cancellation import legacy_cancel

        return await legacy_cancel(
            db, order, version=data.version, reason=data.reason, actor_id=user_id, role=role
        )
    check_version(order.version, data.version)
    if order.paid_at is not None or order.pos_requested:
        raise HTTPException(409, "Die Bestellung ist bereits an der Kasse oder abgeschlossen.")
    transitions = {"sent": "preparing", "preparing": "ready", "ready": "served"}
    if transitions.get(order.status) != data.status:
        raise HTTPException(409, "Dieser Statuswechsel passt nicht zum aktuellen Bestellstand.")
    if data.status == "served" and role == "kitchen":
        raise HTTPException(403, "Servieren erfordert eine Servicerolle.")
    from app.gastro.cancellation_projection import remaining_lines

    active_ids = {str(line["line_id"]) for line in remaining_lines(order)}
    if data.status == "preparing":
        from app.gastro.recipes import consume_order_lines

        await consume_order_lines(
            db,
            venue,
            order,
            [line for line in order.lines if line.get("preparation_status", "sent") == "sent"],
            user_id,
        )
    order.status = data.status
    order.fulfillment_status = data.status
    ranks = {"sent": 0, "preparing": 1, "ready": 2, "served": 3, "cancelled": 4}
    order.lines = [
        (
            {**line, "preparation_status": data.status}
            if str(line.get("line_id")) in active_ids
            and ranks.get(str(line.get("preparation_status", "sent")), 0) < ranks[data.status]
            else line
        )
        for line in order.lines
    ]
    order.version += 1
    event(
        db,
        venue_id,
        "order.status_changed",
        order.id,
        {"status": order.status, "version": order.version, "reason": data.reason},
        user_id,
        device_id,
    )
    await db.flush()
    return order


async def request_pos(
    db: AsyncSession, venue_id: uuid.UUID, order_id: uuid.UUID, version: int, user_id: uuid.UUID
) -> Order:
    order = await order_for_venue(db, venue_id, order_id, lock=True)
    if order.status != "served" or order.paid_at:
        raise HTTPException(
            409, "Nur servierte, offene Bestellungen können an die Kasse übergeben werden."
        )
    if order.pos_requested and version in {order.version, order.version - 1}:
        return order
    check_version(order.version, version)
    await handoff_checkout(db, order, user_id)
    return order


async def handoff_checkout(db: AsyncSession, order: Order, user_id: uuid.UUID) -> None:
    """One immutable checkout snapshot; caller holds the order lock."""
    from app.gastro.cancellation_money import assert_checkout_reconciled
    from app.gastro.cash import balance_read, order_entries

    await assert_checkout_reconciled(db, order)
    remaining = balance_read(order, await order_entries(db, order)).remaining_cents
    if order.cancellation_units and remaining == 0:
        raise HTTPException(409, "Nach der Stornokorrektur ist kein Zahlbetrag mehr offen.")
    order.pos_requested = True
    order.payment_status = "requested"
    order.version += 1
    payload = OrderRead.model_validate(order).model_dump(mode="json")
    payload["amount_due_cents"] = remaining
    event(db, order.venue_id, "pos.checkout_requested", order.id, payload, user_id)
    await db.flush()


async def device_venue(db: AsyncSession, device: Device, scope: str) -> Venue:
    if scope not in device.scopes:
        raise HTTPException(403, "Der Geräteschlüssel erlaubt diese Aktion nicht.")
    row = (
        await db.execute(
            select(Venue)
            .join(Customer, Customer.id == Venue.tenant_id)
            .where(Venue.id == device.venue_id, Customer.status.in_(["active", "trial"]))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(403, "Der Betrieb ist nicht aktiv.")
    device.last_seen_at = datetime.now(UTC)
    return row


async def check_resource_available(
    db: AsyncSession, table_id: uuid.UUID, starts_at: datetime, ends_at: datetime
) -> None:
    from app.gastro.booking_service import check_available

    await check_available(db, [table_id], starts_at, ends_at)
