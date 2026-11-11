"""Explainable operational signals from the venue's own recorded activity."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gastro import service as svc
from app.gastro.booking_models import ReservationMeta
from app.gastro.cash import units_for
from app.gastro.cash_models import CashEntry
from app.gastro.deliveries import confirmations
from app.gastro.insight_math import rolling_backtest, weekday_prediction
from app.gastro.inventory import snapshot
from app.gastro.labour_service import labour_summary
from app.gastro.models import Event, Order, Reservation
from app.gastro.purchasing_sources import (
    MAX_SOURCE_OPTIONS,
    SupplierSourceOption,
    suggested_sources,
)
from app.gastro.recipes import RecipeVersion
from app.gastro.reporting import ReportingDB
from app.gastro.router import Actor, private_response
from app.gastro.stock_costs import StockUsage, stock_costs

router = APIRouter(dependencies=[Depends(private_response)])


class DishInsight(BaseModel):
    item_id: str
    name: str
    quantity: int
    revenue_net_cents: int
    refunded_net_cents: int = 0
    actual_consumption_cost_cents: int | None = 0
    recipe_cost_cents: int | None
    contribution_cents: int | None
    category: str


class StockSuggestion(BaseModel):
    item_id: uuid.UUID
    name: str
    unit: str
    available_quantity: Decimal
    minimum_quantity: Decimal
    proposed_quantity: Decimal
    reason: str
    incoming_quantity_next7days: Decimal = Decimal(0)
    uncovered_after_incoming_quantity: Decimal = Decimal(0)
    earliest_confirmed_on: date | None = None
    confirmation_ids: list[uuid.UUID] = Field(default_factory=list)
    supplier_options: list[SupplierSourceOption] = Field(default_factory=list)
    supplier_option_limit: int = MAX_SOURCE_OPTIONS


class ForecastDay(BaseModel):
    date: str
    expected_orders: int | None
    lower_orders: int | None
    upper_orders: int | None
    comparable_days: int
    reserved_guests: int = 0


class ForecastBacktest(BaseModel):
    evaluated_days: int
    median_mae: float | None
    prior_week_mae: float | None
    from_date: date | None
    through_date: date | None


class ReservationHistory(BaseModel):
    completed_reservations: int
    no_shows: int
    pending_past_reservations: int
    no_show_rate: float | None


class OperationsInsights(BaseModel):
    cohort_start: date
    cohort_through: date
    as_of: datetime
    revenue_before_refunds_net_cents: int
    refunded_net_cents: int
    unpaid_cancellation_net_cents: int = 0
    legacy_paid_orders: int
    unmatched_refund_entries: int
    backtest: ForecastBacktest
    reservation_history: ReservationHistory
    approved_work_through: date
    approved_work_minutes: int
    unvalued_work_minutes: int
    labor_cost_cents: int | None
    labor_known_cost_cents: int
    labor_valued_minutes: int
    labor_ambiguous_minutes: int
    labor_rate_revision_ids: list[uuid.UUID]
    labor_source_fingerprint: str
    stock_usage: list[StockUsage]
    window_days: int
    paid_orders: int
    revenue_net_cents: int
    dishes: list[DishInsight]
    purchasing: list[StockSuggestion]
    forecast: list[ForecastDay]
    prepared_cancellations: int
    method: str
    limitations: list[str]


@router.get(
    "/venues/{venue_id}/insights",
    response_model=OperationsInsights,
    status_code=200,
    summary="Menübeiträge, Mindestbestände und nachvollziehbare Wochenprognose",
)
async def insights(venue_id: uuid.UUID, db: ReportingDB, user: Actor) -> OperationsInsights:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    now = datetime.now(ZoneInfo(venue.timezone))
    start = datetime.combine(now.date() - timedelta(days=55), time.min, tzinfo=now.tzinfo)
    history_start = datetime.combine(now.date() - timedelta(days=84), time.min, tzinfo=now.tzinfo)
    orders = list(
        (
            await db.execute(
                select(Order)
                .where(
                    Order.venue_id == venue_id,
                    Order.created_at >= history_start,
                    Order.created_at <= now,
                )
                .order_by(Order.created_at)
            )
        ).scalars()
    )
    recipes = {
        str(row.id): row
        for row in (
            await db.execute(select(RecipeVersion).where(RecipeVersion.venue_id == venue_id))
        ).scalars()
    }
    costs = await stock_costs(db, venue_id, start, now)
    cash_entries = list(
        (
            await db.execute(
                select(CashEntry)
                .join(Order, Order.id == CashEntry.order_id)
                .where(
                    CashEntry.venue_id == venue_id,
                    Order.created_at >= start,
                    Order.created_at <= now,
                    CashEntry.created_at <= now,
                )
            )
        ).scalars()
    )
    entry_by_id = {entry.id: entry for entry in cash_entries}
    entries_by_order: dict[uuid.UUID, list[CashEntry]] = defaultdict(list)
    for entry in cash_entries:
        if entry.order_id is not None:
            entries_by_order[entry.order_id].append(entry)
    paid_order_ids = {entry.order_id for entry in cash_entries if entry.kind == "sale"}
    refunds: dict[tuple[uuid.UUID, str], int] = defaultdict(int)
    unmatched_refunds = 0
    product_lines = {
        (order.id, str(line.get("line_id") or uuid.uuid5(order.id, f"line:{index}")))
        for order in orders
        if order.created_at >= start
        for index, line in enumerate(order.lines)
        if line.get("kind", "product") == "product"
    }
    for entry in cash_entries:
        if entry.kind != "refund":
            continue
        source = entry_by_id.get(entry.original_id) if entry.original_id else None
        if source is None or source.kind != "sale" or source.order_id != entry.order_id:
            unmatched_refunds += 1
            continue
        source_keys = {(str(a["line_id"]), str(a["unit"])) for a in source.allocations}
        unmatched = False
        for allocation in entry.allocations:
            if allocation.get("kind") != "product":
                continue
            line_id = str(allocation.get("line_id"))
            if (
                entry.order_id is None
                or (entry.order_id, line_id) not in product_lines
                or (line_id, str(allocation.get("unit"))) not in source_keys
            ):
                unmatched = True
                continue
            refunds[(entry.order_id, line_id)] += int(str(allocation["amount_cents"])) - int(
                str(allocation["tax_cents"])
            )
        unmatched_refunds += int(unmatched)
    daily: dict[date, int] = defaultdict(int)
    dishes: dict[str, DishInsight] = {}
    paid = 0
    revenue = 0
    revenue_before_refunds = 0
    refunded = 0
    unpaid_cancellations = 0
    legacy_paid = 0
    for order in orders:
        # All placed orders count, including later cancellations. Using current
        # cancellation state would leak subsequent outcomes into historical tests.
        daily[order.created_at.astimezone(ZoneInfo(venue.timezone)).date()] += 1
        covered_by_correction = (
            bool(order.cancellation_units)
            and order.id in paid_order_ids
            and not any(unit.remaining for unit in units_for(order, entries_by_order[order.id]))
        )
        if (
            order.created_at < start
            or (order.paid_at is None and not covered_by_correction)
            or (order.paid_at is not None and order.paid_at > now)
        ):
            continue
        paid += 1
        legacy_paid += int(order.id not in paid_order_ids)
        for index, line in enumerate(order.lines):
            if line.get("kind", "product") != "product":
                continue
            key = str(line["item_id"])
            quantity = int(str(line["quantity"]))
            net = int(str(line["total_cents"])) - int(str(line["tax_cents"]))
            line_id = str(line.get("line_id") or uuid.uuid5(order.id, f"line:{index}"))
            waived = sum(
                unit.unpaid_credit_cents - unit.unpaid_tax_cents
                for unit in order.cancellation_units
                if str(unit.line_id) == line_id
            )
            net -= waived
            unpaid_cancellations += waived
            refund = refunds[(order.id, line_id)]
            revenue_before_refunds += net
            net -= refund
            refunded += refund
            revenue += net
            recipe = recipes.get(str(line.get("recipe_id")))
            cost = recipe.cost_cents * quantity if recipe else None
            if key not in dishes:
                dishes[key] = DishInsight(
                    item_id=key,
                    name=str(line["name"]),
                    quantity=0,
                    revenue_net_cents=0,
                    recipe_cost_cents=0,
                    contribution_cents=None,
                    category="Kosten fehlen",
                )
            row = dishes[key]
            row.quantity += quantity
            row.revenue_net_cents += net
            row.refunded_net_cents += refund
            actual = costs.line_costs.get((str(order.id), line_id))
            row.actual_consumption_cost_cents = (
                row.actual_consumption_cost_cents + actual
                if row.actual_consumption_cost_cents is not None and actual is not None
                else None
            )
            row.recipe_cost_cents = (
                row.recipe_cost_cents + cost
                if row.recipe_cost_cents is not None and cost is not None
                else None
            )
    known = [row for row in dishes.values() if row.recipe_cost_cents is not None]
    quantity_mid = median([row.quantity for row in known]) if known else 0
    contribution_mid = (
        median(
            [(row.revenue_net_cents - (row.recipe_cost_cents or 0)) / row.quantity for row in known]
        )
        if known
        else 0
    )
    for row in known:
        row.contribution_cents = row.revenue_net_cents - (row.recipe_cost_cents or 0)
        high_margin = row.contribution_cents / row.quantity >= contribution_mid
        high_sales = row.quantity >= quantity_mid
        row.category = (
            "Bestseller mit Beitrag"
            if high_margin and high_sales
            else (
                "Marge prüfen"
                if high_sales
                else "Sichtbarkeit prüfen" if high_margin else "Angebot überprüfen"
            )
        )
    inventory = await snapshot(venue_id, db, user)
    available: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    own_ids = {row.id for row in inventory.owners if row.kind == "own"}
    for balance in inventory.balances:
        if balance.owner_id in own_ids:
            available[balance.item_id] += balance.available_quantity
    incoming = await confirmations(
        venue_id, user, db, line_id=None, current_only=True, before_version=None
    )
    upcoming: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    earliest: dict[uuid.UUID, date] = {}
    confirmation_ids: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for promise in incoming:
        if (
            promise.reliable_for_planning
            and promise.owner_id in own_ids
            and promise.expected_on <= now.date() + timedelta(days=7)
        ):
            upcoming[promise.item_id] += promise.remaining_physical_quantity
            earliest[promise.item_id] = min(
                earliest.get(promise.item_id, promise.expected_on), promise.expected_on
            )
            confirmation_ids[promise.item_id].append(promise.id)
    purchasing = [
        StockSuggestion(
            item_id=item.id,
            name=item.name,
            unit=item.unit,
            available_quantity=available[item.id],
            minimum_quantity=item.minimum_quantity,
            proposed_quantity=item.minimum_quantity - available[item.id],
            reason="Freigegebener eigener Bestand liegt unter dem Mindestbestand. Lieferzusagen bleiben bis zur tatsächlichen Annahme getrennt.",
            incoming_quantity_next7days=upcoming[item.id],
            uncovered_after_incoming_quantity=max(
                Decimal(0), item.minimum_quantity - available[item.id] - upcoming[item.id]
            ),
            earliest_confirmed_on=earliest.get(item.id),
            confirmation_ids=confirmation_ids[item.id],
        )
        for item in inventory.items
        if available[item.id] < item.minimum_quantity
    ]
    for suggestion in purchasing:
        suggestion.supplier_options = await suggested_sources(
            db,
            venue,
            suggestion.item_id,
            suggestion.uncovered_after_incoming_quantity,
            now,
        )
    forecast: list[ForecastDay] = []
    first_activity = min(
        (order.created_at.astimezone(ZoneInfo(venue.timezone)).date() for order in orders),
        default=now.date(),
    )
    reservations = (
        await db.execute(
            select(Reservation, ReservationMeta)
            .outerjoin(ReservationMeta, ReservationMeta.reservation_id == Reservation.id)
            .where(
                Reservation.venue_id == venue_id,
                Reservation.starts_at >= start,
                Reservation.starts_at
                < datetime.combine(now.date() + timedelta(days=8), time.min, tzinfo=now.tzinfo),
            )
        )
    ).all()
    reserved: dict[date, int] = defaultdict(int)
    no_shows = completed = pending = 0
    for reservation, meta in reservations:
        if reservation.status == "confirmed":
            reserved[
                reservation.starts_at.astimezone(ZoneInfo(venue.timezone)).date()
            ] += reservation.guests
        if reservation.ends_at >= now or (meta is not None and meta.source != "reservation"):
            continue
        if reservation.status == "no_show":
            no_shows += 1
        elif reservation.status == "completed" or (
            meta is not None and meta.checked_in_at is not None
        ):
            completed += 1
        elif reservation.status == "confirmed":
            pending += 1
    for ahead in range(1, 8):
        day = now.date() + timedelta(days=ahead)
        prediction = weekday_prediction(daily, first_activity, day, now.date())
        forecast.append(
            ForecastDay(
                date=day.isoformat(),
                expected_orders=prediction.expected,
                lower_orders=prediction.low_observed,
                upper_orders=prediction.high_observed,
                comparable_days=len(prediction.sample_days),
                reserved_guests=reserved[day],
            )
        )
    backtest = rolling_backtest(daily, first_activity, now.date())
    work = await labour_summary(
        db, venue, start, datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    )
    work_minutes = work.valued_minutes + work.unvalued_minutes
    waste = (
        await db.execute(
            select(Event.id).where(
                Event.venue_id == venue_id,
                Event.kind == "production.prepared_cancelled",
                Event.created_at >= start,
            )
        )
    ).all()
    return OperationsInsights(
        cohort_start=start.date(),
        cohort_through=now.date(),
        as_of=now,
        revenue_before_refunds_net_cents=revenue_before_refunds,
        refunded_net_cents=refunded,
        unpaid_cancellation_net_cents=unpaid_cancellations,
        legacy_paid_orders=legacy_paid,
        unmatched_refund_entries=unmatched_refunds,
        backtest=ForecastBacktest(
            evaluated_days=backtest.evaluated_days,
            median_mae=backtest.median_mae,
            prior_week_mae=backtest.prior_week_mae,
            from_date=backtest.from_date,
            through_date=backtest.through_date,
        ),
        reservation_history=ReservationHistory(
            completed_reservations=completed,
            no_shows=no_shows,
            pending_past_reservations=pending,
            no_show_rate=(
                round(no_shows / (completed + no_shows), 4) if completed + no_shows else None
            ),
        ),
        approved_work_through=now.date() - timedelta(days=1),
        approved_work_minutes=work_minutes,
        unvalued_work_minutes=work.unvalued_minutes,
        labor_cost_cents=work.cost_cents,
        labor_known_cost_cents=work.known_cost_cents,
        labor_valued_minutes=work.valued_minutes,
        labor_ambiguous_minutes=work.ambiguous_minutes,
        labor_rate_revision_ids=work.rate_revision_ids,
        labor_source_fingerprint=work.source_fingerprint,
        stock_usage=costs.usage,
        window_days=56,
        paid_orders=paid,
        revenue_net_cents=revenue,
        dishes=sorted(dishes.values(), key=lambda row: row.revenue_net_cents, reverse=True),
        purchasing=purchasing,
        forecast=forecast,
        prepared_cancellations=len(waste),
        method="Median desselben Wochentags aus erfassten Bons einschließlich späterer Stornos; mindestens vier Vergleichstage. Spanne: historisches Minimum/Maximum. Rollierender Rücktest gegen den Vorwochenwert ohne spätere Eingabedaten.",
        limitations=[
            "Unbezahlte Stornoanteile mindern die Erlösbasis. Durch Teilzahlung und Forderungsverzicht vollständig gedeckte Bons zählen mit, ohne eine neue Zahlung zu behaupten. Noch nicht ausgezahlte Erstattungsansprüche stehen getrennt am Bon; erst tatsächliche Erstattungen mindern die hier ausgewiesenen Zahlungsumsätze.",
            "Verkaufskohorte nach Bon-Erstellung; zugehörige bestätigte Produkt-Erstattungen bis zum Abfragezeitpunkt mindern den Nettoerlös. Kein periodenreiner Finanzabschluss.",
            "Historische bezahlte Bons ohne Kassenbuch und nicht zuordenbare Erstattungen werden separat gezählt. Rezeptkosten sind Kalkulationen und bleiben bei Geldrückzahlungen bestehen.",
            "Belegte Verbrauchskosten verwenden gleitende Chargenkosten aus angenommenen Einkaufsmengen zu festen Bestellpreisen einschließlich Gratisware und tatsächlicher Prep-Ausbeute. Unbewertete Zugänge bleiben unbekannt; Fracht, spätere Gutschriften und Boni sind nicht enthalten.",
            "Produktionszutaten werden separat ausgewiesen, damit ihre Kosten beim späteren Verbrauch der fertigen Charge nicht doppelt zählen. Alle Lagerkennzahlen beziehen sich auf Eigenbestand.",
            "Freigegebene Arbeitsminuten zählen abgeschlossene Kalendertage bis gestern und benötigen eine aktuelle eindeutige Dienstzuordnung. Personalkosten verwenden die aktuelle belegte Satzrevision einschließlich konfiguriertem Arbeitgeberzuschlag; Korrekturen können die Live-Auswertung ändern, frühere Revisionen bleiben abrufbar. Gemeinkosten und Lohnabrechnung sind nicht enthalten.",
            "Tage ohne Bon nach erster Aktivität zählen im Modell als null. Historische Öffnungs-/Schließtage, Wetter und Veranstaltungen fehlen; Spannen sind keine Konfidenzintervalle.",
            "Reservierte Personen bleiben getrennt von erwarteten Bestellungen. Offene vergangene Reservierungen zählen nicht automatisch als No-show. Vorschläge lösen keine externe Bestellung aus.",
        ],
    )
