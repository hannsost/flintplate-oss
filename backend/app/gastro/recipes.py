"""Versioned recipes, traceable preparation and immutable food-safety records."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro import inventory as stock
from app.gastro import service as svc
from app.gastro.inventory_models import (
    InventoryBase,
    StockLot,
    StockMovement,
    StockOperation,
    StockOwner,
)
from app.gastro.inventory_schemas import BookingInput, PositiveQuantity
from app.gastro.models import MenuItem, Order, Venue
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import Ingredient, MenuPayload, food_tag
from app.gastro.stock_availability import reserved_at

router = APIRouter(dependencies=[Depends(private_response)])


class RecipeVersion(InventoryBase):
    __tablename__ = "fp_recipe_versions"
    __table_args__ = (UniqueConstraint("venue_id", "request_key", name="uq_fp_recipe_request"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_menu_items.id"), nullable=True
    )
    menu_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_stock_items.id"))
    yield_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    components: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    cost_cents: Mapped[int] = mapped_column(Integer)
    allergens: Mapped[list[str]] = mapped_column(JSONB)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PrepRun(InventoryBase):
    __tablename__ = "fp_prep_runs"
    __table_args__ = (UniqueConstraint("venue_id", "request_key", name="uq_fp_prep_request"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_recipe_versions.id"))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    operation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_stock_operations.id"))
    output_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_stock_lots.id"))
    batches: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    output_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))


class HaccpRecord(InventoryBase):
    __tablename__ = "fp_haccp_records"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_haccp_request"),
        UniqueConstraint("venue_id", "id", name="uq_fp_haccp_record_scope"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(120))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    minimum: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    maximum: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(20))
    result: Mapped[str] = mapped_column(String(12))
    correction: Mapped[str] = mapped_column(String(500))
    corrects_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_haccp_records.id"), nullable=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class Component(BaseModel):
    stock_item_id: uuid.UUID
    # Omit an absent reference from hashes so old pending recipe requests replay.
    subrecipe_id: uuid.UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    quantity: PositiveQuantity
    unit_cost_cents: int = Field(ge=0, le=10000000)
    allergens: list[str] = Field(default_factory=list, max_length=30)
    contains: list[str] = Field(default_factory=list, max_length=30)


class RecipeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    name: str = Field(min_length=2, max_length=120)
    menu_item_id: uuid.UUID | None = None
    menu_version: int | None = Field(default=None, ge=1)
    output_item_id: uuid.UUID
    yield_quantity: PositiveQuantity
    components: list[Component] = Field(min_length=1, max_length=60)
    allergen_reviewed: Literal[True]

    @model_validator(mode="after")
    def unique_components(self) -> RecipeInput:
        if len({c.stock_item_id for c in self.components}) != len(self.components):
            raise ValueError("Jede Zutat darf nur einmal vorkommen.")
        if self.menu_item_id and self.menu_version is None:
            raise ValueError("Der aktuelle Kartenstand fehlt.")
        return self


class RecipeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    menu_item_id: uuid.UUID | None
    menu_version: int | None
    output_item_id: uuid.UUID
    yield_quantity: Decimal
    components: list[dict[str, JsonValue]]
    cost_cents: int
    allergens: list[str]
    created_at: datetime


class PrepInput(BookingInput):
    recipe_id: uuid.UUID
    batches: PositiveQuantity = Decimal(1)
    output_quantity: PositiveQuantity
    owner_id: uuid.UUID
    location_id: uuid.UUID
    lot_code: str = Field(min_length=1, max_length=100)
    expires_on: date


class PrepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    recipe_id: uuid.UUID
    output_lot_id: uuid.UUID
    operation_id: uuid.UUID
    batches: Decimal
    output_quantity: Decimal
    created_at: datetime


class HaccpInput(BaseModel):
    request_key: uuid.UUID
    name: str = Field(min_length=2, max_length=120)
    location: str = Field(min_length=2, max_length=120)
    value: Decimal = Field(ge=-100000, le=100000, decimal_places=3)
    minimum: Decimal = Field(ge=-100000, le=100000, decimal_places=3)
    maximum: Decimal = Field(ge=-100000, le=100000, decimal_places=3)
    unit: str = Field(min_length=1, max_length=20)
    correction: str = Field(default="", max_length=500)
    corrects_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def limits(self) -> HaccpInput:
        if self.minimum > self.maximum:
            raise ValueError("Untergrenze muss unter der Obergrenze liegen.")
        if not self.minimum <= self.value <= self.maximum and len(self.correction.strip()) < 5:
            raise ValueError(
                "Bei Grenzwertverletzung ist eine konkrete Sofortmaßnahme erforderlich."
            )
        return self


class HaccpRead(HaccpInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    result: str
    actor_id: uuid.UUID
    measured_at: datetime


@router.get(
    "/venues/{venue_id}/recipes",
    response_model=list[RecipeRead],
    status_code=200,
    summary="Unveränderliche Rezeptversionen und Portionskosten anzeigen",
)
async def recipes(venue_id: uuid.UUID, user: Actor, db: DB) -> list[RecipeVersion]:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    return list(
        (
            await db.execute(
                select(RecipeVersion)
                .where(RecipeVersion.venue_id == venue_id)
                .order_by(RecipeVersion.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/recipes",
    response_model=RecipeRead,
    status_code=201,
    summary="Geprüfte Rezeptur versionieren und Kartenentwurf aktualisieren",
)
async def create_recipe(
    venue_id: uuid.UUID, data: RecipeInput, user: Actor, db: DB
) -> RecipeVersion:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    prior = (
        await db.execute(
            select(RecipeVersion).where(
                RecipeVersion.venue_id == venue_id, RecipeVersion.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != svc.digest(data):
            raise HTTPException(409, "Diese Rezept-ID wurde anders verwendet.")
        return prior
    if data.menu_item_id:
        from app.gastro.partners_models import PartnerContract

        if (
            await db.execute(
                select(PartnerContract.id).where(
                    PartnerContract.venue_id == venue_id,
                    PartnerContract.menu_item_id == data.menu_item_id,
                )
            )
        ).first():
            raise HTTPException(
                409,
                "Dieser Verkaufsartikel gehört zu einem Partnervertrag. Eigenwaren-Rezepturen benötigen einen eigenen Kartenartikel.",
            )
    output = await stock.item_for(db, venue_id, data.output_item_id)
    if data.menu_item_id and output.unit != "piece":
        raise HTTPException(
            422,
            "Kartenrezepte benötigen einen Ausgabeartikel in Stück (Portionen). Mengen in kg oder l zuerst als internes Unterrezept vorbereiten.",
        )
    stock.validate_quantity(output, data.yield_quantity)
    components: list[dict[str, JsonValue]] = []
    ingredients: list[Ingredient] = []
    allergens: set[str] = set()
    contains: set[str] = set()
    cost = Decimal(0)
    for component in data.components:
        item = await stock.item_for(db, venue_id, component.stock_item_id)
        stock.validate_quantity(item, component.quantity)
        if item.id == output.id:
            raise HTTPException(
                422, "Eine Rezeptur darf ihren eigenen Ausgabeartikel nicht verbrauchen."
            )
        component_allergens = {tag.strip().lower() for tag in component.allergens if tag.strip()}
        component_contains = {food_tag(tag) for tag in component.contains if tag.strip()}
        unit_cost_cents = component.unit_cost_cents
        if component.subrecipe_id:
            subrecipe = await recipe_for(db, venue_id, component.subrecipe_id)
            if subrecipe.output_item_id != item.id:
                raise HTTPException(422, "Das Unterrezept produziert einen anderen Lagerartikel.")
            if component.unit_cost_cents != subrecipe.cost_cents:
                raise HTTPException(
                    422, "Unterrezeptkosten müssen der ausgewählten Rezeptversion entsprechen."
                )
            unit_cost_cents = subrecipe.cost_cents
            component_allergens.update(subrecipe.allergens)
            for inherited in subrecipe.components:
                raw_tags = inherited.get("contains")
                if isinstance(raw_tags, list):
                    component_contains.update(food_tag(str(tag)) for tag in raw_tags)
        if len(component_allergens) > 14 or len(component_contains) > 30:
            raise HTTPException(
                422,
                "Bitte Allergen- und Zutatenmerkmale dieser Zutat auf konsistente Bezeichnungen zusammenführen.",
            )
        json_allergens: list[JsonValue] = [tag for tag in sorted(component_allergens)]
        json_contains: list[JsonValue] = [tag for tag in sorted(component_contains)]
        components.append(
            {
                **component.model_dump(mode="json"),
                "name": item.name,
                "unit": item.unit,
                "unit_cost_cents": unit_cost_cents,
                "allergens": json_allergens,
                "contains": json_contains,
            }
        )
        ingredients.append(Ingredient(name=item.name[:80], allergens=sorted(component_allergens)))
        allergens.update(component_allergens)
        contains.update(component_contains)
        cost += component.quantity * unit_cost_cents
    unit_cost = int((cost / data.yield_quantity).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    menu: MenuItem | None = None
    if data.menu_item_id:
        menu = await svc.menu_for_venue(db, venue_id, data.menu_item_id, lock=True)
        svc.check_version(menu.version, data.menu_version or 0)
        draft = MenuPayload.model_validate(
            {
                **menu.draft,
                "ingredients": [i.model_dump() for i in ingredients],
                "allergens": sorted(allergens),
                "contains": sorted(contains | allergens),
                "cost_cents": unit_cost,
            }
        )
        menu.draft = draft.model_dump(mode="json")
        menu.version += 1
    row = RecipeVersion(
        venue_id=venue_id,
        request_key=data.request_key,
        request_hash=svc.digest(data),
        name=data.name,
        menu_item_id=menu.id if menu else None,
        menu_version=menu.version if menu else None,
        output_item_id=output.id,
        yield_quantity=data.yield_quantity,
        components=components,
        cost_cents=unit_cost,
        allergens=sorted(allergens),
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "recipe.version_created",
        row.id,
        {"menu_item_id": str(menu.id) if menu else None, "menu_version": row.menu_version},
        user.id,
    )
    return row


async def recipe_for(db: DB, venue_id: uuid.UUID, recipe_id: uuid.UUID) -> RecipeVersion:
    row = (
        await db.execute(
            select(RecipeVersion).where(
                RecipeVersion.venue_id == venue_id, RecipeVersion.id == recipe_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Rezeptversion nicht gefunden.")
    return row


async def consume_components(
    db: DB, venue: Venue, operation: StockOperation, recipe: RecipeVersion, batches: Decimal
) -> None:
    """FEFO allocation under the venue lock; no negative, expired or partner stock."""
    today = datetime.now(ZoneInfo(venue.timezone)).date()
    for component in recipe.components:
        item_id = uuid.UUID(str(component["stock_item_id"]))
        exact = Decimal(str(component["quantity"])) * batches
        required = exact.quantize(Decimal("0.000001"))
        if required <= 0 or exact != required:
            raise HTTPException(
                422, "Die Rezeptmenge lässt sich nicht ohne Rundungsverlust buchen."
            )
        item = await stock.item_for(db, venue.id, item_id)
        stock.validate_quantity(item, required)
        lots = list(
            (
                await db.execute(
                    select(StockLot)
                    .join(StockOwner, StockOwner.id == StockLot.owner_id)
                    .where(
                        StockLot.venue_id == venue.id,
                        StockLot.item_id == item_id,
                        StockOwner.kind == "own",
                    )
                    .order_by(
                        StockLot.expires_on.asc().nullslast(), StockLot.created_at, StockLot.id
                    )
                )
            ).scalars()
        )
        if component.get("subrecipe_id"):
            # A prepared ingredient must match its frozen recipe version. A
            # newer batch may have different allergens, cost or composition.
            matching_lots = set(
                (
                    await db.execute(
                        select(PrepRun.output_lot_id).where(
                            PrepRun.venue_id == venue.id,
                            PrepRun.recipe_id == uuid.UUID(str(component["subrecipe_id"])),
                        )
                    )
                ).scalars()
            )
            lots = [lot for lot in lots if lot.id in matching_lots]
        for lot in lots:
            if lot.expires_on is not None and lot.expires_on < today:
                continue
            if getattr(lot, "blocked", False):
                continue
            balances = (
                await db.execute(
                    select(StockMovement.location_id, func.sum(StockMovement.quantity))
                    .where(StockMovement.venue_id == venue.id, StockMovement.lot_id == lot.id)
                    .group_by(StockMovement.location_id)
                    .order_by(StockMovement.location_id)
                )
            ).all()
            for location_id, balance in balances:
                held = await reserved_at(db, venue.id, lot.id, location_id)
                amount = min(required, max(Decimal(0), Decimal(str(balance)) - held))
                if amount:
                    db.add(
                        StockMovement(
                            venue_id=venue.id,
                            operation_id=operation.id,
                            lot_id=lot.id,
                            location_id=location_id,
                            quantity=-amount,
                        )
                    )
                    required -= amount
                if required <= 0:
                    break
            if required <= 0:
                break
        if required > 0:
            raise HTTPException(
                409,
                f"Zu wenig freigegebener Bestand für {component['name']}: {required} {component['unit']} fehlen.",
            )
    await db.flush()


@router.post(
    "/venues/{venue_id}/prep",
    response_model=PrepRead,
    status_code=201,
    summary="Prep-Charge mit FEFO-Zutatenverbrauch und Rückverfolgung buchen",
)
async def prepare_batch(venue_id: uuid.UUID, data: PrepInput, user: Actor, db: DB) -> PrepRun:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    previous = (
        await db.execute(
            select(PrepRun).where(
                PrepRun.venue_id == venue_id, PrepRun.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Diese Produktions-ID wurde anders verwendet.")
        return previous
    recipe = await recipe_for(db, venue_id, data.recipe_id)
    output = await stock.item_for(db, venue_id, recipe.output_item_id)
    stock.validate_quantity(output, data.output_quantity)
    await stock.location_for(db, venue_id, data.location_id)
    owner = (
        await db.execute(
            select(StockOwner).where(
                StockOwner.id == data.owner_id,
                StockOwner.venue_id == venue_id,
                StockOwner.kind == "own",
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        raise HTTPException(422, "Produktion benötigt einen eigenen Bestandseigentümer.")
    if data.output_quantity > recipe.yield_quantity * data.batches:
        raise HTTPException(422, "Ausbeute überschreitet die geplante Rezeptmenge.")
    if data.expires_on < datetime.now(ZoneInfo(venue.timezone)).date():
        raise HTTPException(422, "Die neue Charge darf nicht bereits abgelaufen sein.")
    if (
        await db.execute(
            select(StockLot.id).where(
                StockLot.venue_id == venue_id,
                StockLot.item_id == output.id,
                StockLot.owner_id == owner.id,
                StockLot.code == data.lot_code,
            )
        )
    ).first():
        raise HTTPException(409, "Diese Produktionscharge existiert bereits.")
    lot = StockLot(
        venue_id=venue_id,
        item_id=output.id,
        owner_id=owner.id,
        code=data.lot_code,
        expires_on=data.expires_on,
    )
    operation = StockOperation(
        venue_id=venue_id,
        request_key=data.request_key,
        request_hash=svc.digest(data),
        kind="production",
        actor_id=user.id,
        reason=data.reason,
        details={**data.model_dump(mode="json"), "recipe_id": str(recipe.id)},
    )
    db.add_all([lot, operation])
    await db.flush()
    await consume_components(db, venue, operation, recipe, data.batches)
    db.add(
        StockMovement(
            venue_id=venue_id,
            operation_id=operation.id,
            lot_id=lot.id,
            location_id=data.location_id,
            quantity=data.output_quantity,
        )
    )
    row = PrepRun(
        venue_id=venue_id,
        recipe_id=recipe.id,
        request_key=data.request_key,
        request_hash=svc.digest(data),
        operation_id=operation.id,
        output_lot_id=lot.id,
        batches=data.batches,
        output_quantity=data.output_quantity,
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "production.batch_created",
        row.id,
        {
            "recipe_id": str(recipe.id),
            "output_lot_id": str(lot.id),
            "operation_id": str(operation.id),
        },
        user.id,
    )
    return row


@router.get(
    "/venues/{venue_id}/prep",
    response_model=list[PrepRead],
    status_code=200,
    summary="Produktionschargen mit Ausbeute anzeigen",
)
async def prep_runs(venue_id: uuid.UUID, user: Actor, db: DB) -> list[PrepRun]:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    return list(
        (
            await db.execute(
                select(PrepRun)
                .where(PrepRun.venue_id == venue_id)
                .order_by(PrepRun.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/haccp",
    response_model=HaccpRead,
    status_code=201,
    summary="Hygienekontrolle mit betrieblichen Grenzwerten unveränderlich protokollieren",
)
async def record_haccp(venue_id: uuid.UUID, data: HaccpInput, user: Actor, db: DB) -> HaccpRecord:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    previous = (
        await db.execute(
            select(HaccpRecord).where(
                HaccpRecord.venue_id == venue_id, HaccpRecord.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Diese Kontroll-ID wurde anders verwendet.")
        return previous
    if (
        data.corrects_id
        and not (
            await db.execute(
                select(HaccpRecord.id).where(
                    HaccpRecord.venue_id == venue_id, HaccpRecord.id == data.corrects_id
                )
            )
        ).first()
    ):
        raise HTTPException(404, "Ursprüngliche Kontrolle nicht gefunden.")
    row = HaccpRecord(
        venue_id=venue_id,
        **data.model_dump(),
        request_hash=svc.digest(data),
        measured_at=datetime.now(ZoneInfo("UTC")),
        result="ok" if data.minimum <= data.value <= data.maximum else "deviation",
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "haccp.recorded",
        row.id,
        {
            "result": row.result,
            "name": row.name,
            "corrects_id": str(row.corrects_id) if row.corrects_id else None,
        },
        user.id,
    )
    return row


@router.get(
    "/venues/{venue_id}/haccp",
    response_model=list[HaccpRead],
    status_code=200,
    summary="Hygienekontrollen und Abweichungen anzeigen",
)
async def haccp_records(venue_id: uuid.UUID, user: Actor, db: DB) -> list[HaccpRecord]:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    return list(
        (
            await db.execute(
                select(HaccpRecord)
                .where(HaccpRecord.venue_id == venue_id)
                .order_by(HaccpRecord.measured_at.desc(), HaccpRecord.id)
                .limit(200)
            )
        ).scalars()
    )


async def consume_order_lines(
    db: DB,
    venue: Venue,
    order: Order,
    lines: list[dict[str, JsonValue]],
    actor_id: uuid.UUID | None,
) -> None:
    """Production starts once per stable line; a payment callback cannot consume it again."""
    from app.gastro.cancellation_projection import remaining_lines

    active = {str(line["line_id"]): line for line in remaining_lines(order)}
    for original in lines:
        line = active.get(str(original.get("line_id")))
        if line is None:
            continue
        raw_recipe = line.get("recipe_id")
        if not raw_recipe:
            continue
        if actor_id is None:
            actor_id = order.actor_id
        if actor_id is None:
            raise HTTPException(
                409, "Eine verantwortliche Serviceperson muss die Rezeptproduktion starten."
            )
        recipe = await recipe_for(db, venue.id, uuid.UUID(str(raw_recipe)))
        key = uuid.uuid5(uuid.UUID(str(line["line_id"])), "recipe-consumption")
        if (
            await db.execute(
                select(StockOperation.id).where(
                    StockOperation.venue_id == venue.id, StockOperation.request_key == key
                )
            )
        ).first():
            continue
        data = BookingInput(
            request_key=key, reason=f"Produktion {order.number} · {line['name']}"[:300]
        )
        operation = StockOperation(
            venue_id=venue.id,
            request_key=key,
            request_hash=svc.digest(data),
            kind="consume",
            actor_id=actor_id,
            reason=data.reason,
            details={
                "order_id": str(order.id),
                "line_id": line["line_id"],
                "recipe_id": str(recipe.id),
            },
        )
        db.add(operation)
        await db.flush()
        await consume_components(
            db, venue, operation, recipe, Decimal(str(line["quantity"])) / recipe.yield_quantity
        )
        svc.event(
            db,
            venue.id,
            "inventory.order_consumed",
            order.id,
            {"line_id": line["line_id"], "operation_id": str(operation.id)},
            actor_id,
        )


class TraceRead(BaseModel):
    source_lot_id: uuid.UUID
    affected_lot_ids: list[uuid.UUID]
    operation_ids: list[uuid.UUID]
    order_ids: list[uuid.UUID]
    truncated: bool = False


async def trace_lot(db: DB, venue_id: uuid.UUID, lot_id: uuid.UUID) -> TraceRead:
    await stock.lot_for(db, venue_id, lot_id)
    seen = {lot_id}
    frontier = {lot_id}
    operations: set[uuid.UUID] = set()
    orders: set[uuid.UUID] = set()
    truncated = False
    while frontier:
        matches = list(
            (
                await db.execute(
                    select(StockOperation)
                    .join(StockMovement, StockMovement.operation_id == StockOperation.id)
                    .where(
                        StockMovement.venue_id == venue_id,
                        StockMovement.lot_id.in_(frontier),
                        StockMovement.quantity < 0,
                        StockOperation.kind.in_(["production", "consume"]),
                    )
                    .distinct()
                )
            ).scalars()
        )
        new_ops = {row.id for row in matches} - operations
        operations.update(new_ops)
        for row in matches:
            if row.details.get("order_id"):
                orders.add(uuid.UUID(str(row.details["order_id"])))
        outputs = (
            set(
                (
                    await db.execute(
                        select(StockMovement.lot_id).where(
                            StockMovement.venue_id == venue_id,
                            StockMovement.operation_id.in_(new_ops),
                            StockMovement.quantity > 0,
                        )
                    )
                ).scalars()
            )
            if new_ops
            else set()
        )
        frontier = outputs - seen
        seen.update(frontier)
        if len(seen) > 500:
            truncated = True
            break
    return TraceRead(
        source_lot_id=lot_id,
        affected_lot_ids=sorted(seen),
        operation_ids=sorted(operations),
        order_ids=sorted(orders),
        truncated=truncated,
    )


@router.get(
    "/venues/{venue_id}/inventory/lots/{lot_id}/trace",
    response_model=TraceRead,
    status_code=200,
    summary="Chargen bis zur Prep-Produktion und zum verkauften Gericht verfolgen",
)
async def trace(venue_id: uuid.UUID, lot_id: uuid.UUID, user: Actor, db: DB) -> TraceRead:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    return await trace_lot(db, venue_id, lot_id)


@router.post(
    "/venues/{venue_id}/inventory/lots/{lot_id}/recall",
    response_model=TraceRead,
    status_code=200,
    summary="Rückruf mit allen abgeleiteten Produktionschargen sperren",
)
async def recall(
    venue_id: uuid.UUID, lot_id: uuid.UUID, data: BookingInput, user: Actor, db: DB
) -> TraceRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    prior = (
        await db.execute(
            select(StockOperation).where(
                StockOperation.venue_id == venue_id, StockOperation.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if (
            prior.kind != "quarantine"
            or prior.request_hash != svc.digest(data)
            or prior.details.get("source_lot_id") != str(lot_id)
        ):
            raise HTTPException(409, "Diese Rückruf-ID wurde anders verwendet.")
        return TraceRead.model_validate(prior.details)
    result = await trace_lot(db, venue_id, lot_id)
    if result.truncated:
        raise HTTPException(
            409,
            "Der Rückruf umfasst mehr als 500 Chargen. Gesamten Betrieb sperren und Support einschalten.",
        )
    lots = (
        await db.execute(
            select(StockLot)
            .where(StockLot.venue_id == venue_id, StockLot.id.in_(result.affected_lot_ids))
            .with_for_update()
        )
    ).scalars()
    for lot in lots:
        if not lot.blocked:
            lot.blocked = True
            lot.version += 1
    operation = StockOperation(
        venue_id=venue_id,
        request_key=data.request_key,
        request_hash=svc.digest(data),
        kind="quarantine",
        actor_id=user.id,
        reason=data.reason,
        details=result.model_dump(mode="json"),
    )
    db.add(operation)
    await db.flush()
    svc.event(
        db, venue_id, "inventory.recall_started", lot_id, result.model_dump(mode="json"), user.id
    )
    return result


async def validate_menu_recipe(db: DB, item: MenuItem, payload: MenuPayload) -> None:
    """Price/copy edits retain the bound recipe; ingredient changes need a new version."""
    recipe = (
        await db.execute(
            select(RecipeVersion)
            .where(
                RecipeVersion.venue_id == item.venue_id,
                RecipeVersion.menu_item_id == item.id,
                RecipeVersion.menu_version <= item.version,
            )
            .order_by(RecipeVersion.menu_version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if recipe is None:
        return
    names = [str(component["name"])[:80] for component in recipe.components]
    contains: set[str] = {food_tag(tag) for tag in recipe.allergens}
    for component in recipe.components:
        raw = component.get("contains")
        if isinstance(raw, list):
            contains.update(food_tag(str(tag)) for tag in raw if str(tag).strip())
    if (
        names != [ingredient.name for ingredient in payload.ingredients]
        or set(recipe.allergens) != {tag.lower() for tag in payload.allergens}
        or contains != set(payload.contains)
        or payload.cost_cents != recipe.cost_cents
    ):
        raise HTTPException(
            409,
            "Zutaten, Allergene und Kosten dieser Karte stammen aus einer Rezeptur. Änderungen bitte unter Produktion als neue Rezeptversion erfassen.",
        )
