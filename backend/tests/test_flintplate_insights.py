from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order
from tests.test_flintplate_production import setup_recipe

pytest_plugins = ["tests.test_flintplate"]


@pytest.mark.asyncio
async def test_insights_do_not_invent_history_or_recipe_cost(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    result = body(await client.get(site.path("/insights"), headers=site.headers))
    assert result["paid_orders"] == 0 and result["dishes"] == []
    assert all(day["expected_orders"] is None for day in result["forecast"])
    assert (
        await client.get(site.path("/insights"), headers=hr_workspace.headers("other_hr"))
    ).status_code == 404


@pytest.mark.asyncio
async def test_prepared_cancellation_records_waste_without_restoring_consumed_food(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_recipe(client, site)
    order = await sent_order(
        client,
        site,
        lines=[
            {
                "item_id": site.item_id,
                "menu_version": setup["recipe"]["menu_version"],
                "quantity": 2,
            }
        ],
    )
    preparing = body(
        await client.post(
            site.path(f"/orders/{order['id']}/status"),
            headers=site.headers,
            json={"version": order["version"], "status": "preparing"},
        )
    )
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/status"),
            headers=site.headers,
            json={
                "version": preparing["version"],
                "status": "cancelled",
                "reason": "Gast musste dringend gehen",
            },
        )
    )
    result = body(await client.get(site.path("/insights"), headers=site.headers))
    assert result["prepared_cancellations"] == 1
    stock = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert float(stock["balances"][0]["quantity"]) == 9.5


def test_forecast_backtest_does_not_use_future_or_insufficient_history() -> None:
    from datetime import date, timedelta

    from app.gastro.insight_math import rolling_backtest, weekday_prediction

    start = date(2026, 1, 1)
    daily = {start + timedelta(days=day): 10 for day in range(84)}
    target = start + timedelta(days=35)
    before = weekday_prediction(daily, start, target, target)
    daily[target] = 1000000
    daily[target + timedelta(days=7)] = 2000000
    assert weekday_prediction(daily, start, target, target) == before
    assert all(day < target for day in before.sample_days)
    assert weekday_prediction(daily, start, start + timedelta(days=21), target).expected is None
    report = rolling_backtest(daily, start, target)
    assert report.evaluated_days == 7
    assert report.median_mae == report.prior_week_mae == 0


def test_cost_pool_weights_known_receipts_without_inventing_opening_values() -> None:
    from decimal import Decimal as D

    from app.gastro.stock_costs import CostPool

    pool = CostPool()
    pool.add(D(10), D(1000))
    assert pool.take(D(5)) == (D(500), D(0))
    pool.add(D(5), D(2000))
    assert pool.take(D(2)) == (D(500), D(0))
    pool.add(D(2), None)
    assert pool.take(D(5)) == (D(1000), D(1))
    assert pool.quantity == 5 and pool.known_quantity == 4
    # A later price never revalues a consumption already returned above.
    pool.add(D(10), D(100000))
    assert pool.take(D(15)) == (D(101000), D(1))


@pytest.mark.asyncio
async def test_insights_refunds_reduce_only_product_revenue_and_keep_recipe_cost(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    import uuid

    from tests.cancellation_support import approve_cancellation
    from tests.test_flintplate import serve
    from tests.test_flintplate_cash import payment, till

    setup = await setup_recipe(client, site)
    session = await till(client, site, hr_workspace)
    order = await sent_order(
        client,
        site,
        lines=[
            {
                "item_id": site.item_id,
                "menu_version": setup["recipe"]["menu_version"],
                "quantity": 2,
            }
        ],
    )
    order = await serve(client, site, order)
    await payment(client, site, order, session, order["total_cents"])
    before = body(await client.get(site.path("/insights"), headers=site.headers))
    entries = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )["entries"]
    execution = await approve_cancellation(
        client,
        site,
        order,
        lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}],
    )
    refund = body(
        await client.post(
            site.path(f"/cash/payments/{entries[0]['id']}/refunds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "amount_cents": 101,
                "session_id": session["id"],
                "reason": "Teilbetrag wegen Serviceproblem",
                "cancellation_id": execution["id"],
                "confirmed": True,
            },
        ),
        201,
    )
    expected = sum(
        a["amount_cents"] - a["tax_cents"] for a in refund["allocations"] if a["kind"] == "product"
    )
    after = body(await client.get(site.path("/insights"), headers=site.headers))
    assert after["refunded_net_cents"] == expected
    assert after["revenue_before_refunds_net_cents"] == before["revenue_net_cents"]
    assert after["revenue_net_cents"] == before["revenue_net_cents"] - expected
    assert after["dishes"][0]["recipe_cost_cents"] == before["dishes"][0]["recipe_cost_cents"]
    assert after["dishes"][0]["actual_consumption_cost_cents"] is None
    assert after["legacy_paid_orders"] == after["unmatched_refund_entries"] == 0
    from decimal import Decimal

    assert Decimal(after["stock_usage"][0]["unvalued_consumption_quantity"]) == Decimal("0.5")


@pytest.mark.asyncio
async def test_receipt_cost_waste_uses_evidenced_price_and_ignores_later_receipt(
    client: AsyncClient, site: Site
) -> None:
    import uuid
    from decimal import Decimal

    from tests.test_flintplate_purchasing import catalog, delivered, ordered

    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    await delivered(client, site, setup, order)
    stock = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    lot = next(lot for lot in stock["lots"] if lot["code"] == "LOT-A")
    body(
        await client.post(
            site.path("/inventory/waste"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "lot_id": lot["id"],
                "location_id": setup["location_id"],
                "quantity": "1.25",
                "reason": "Beschädigung geprüft",
            },
        ),
        201,
    )
    before = body(await client.get(site.path("/insights"), headers=site.headers))
    row = before["stock_usage"][0]
    assert Decimal(row["waste_quantity"]) == Decimal("1.25")
    assert row["known_waste_cost_cents"] == 500
    assert Decimal(row["unvalued_waste_quantity"]) == 0
    # Same-lot unpriced manual addition must not change past cost evidence.
    body(
        await client.post(
            site.path("/inventory/receipts"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "item_id": setup["item_id"],
                "owner_id": setup["owner_id"],
                "location_id": setup["location_id"],
                "quantity": "10",
                "lot_code": lot["code"],
                "expires_on": lot["expires_on"],
                "reason": "Unbewerteter Altbestand",
                "reference": "OPEN-01",
            },
        ),
        201,
    )
    after = body(await client.get(site.path("/insights"), headers=site.headers))
    assert after["stock_usage"][0]["known_waste_cost_cents"] == 500


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_ingredient", [False, True])
async def test_actual_prep_yield_flows_to_sale_cost_without_double_counting(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, unknown_ingredient: bool
) -> None:
    import uuid
    from datetime import date, timedelta
    from decimal import Decimal

    from tests.test_flintplate import serve
    from tests.test_flintplate_cash import payment, till
    from tests.test_flintplate_purchasing import catalog, delivered, ordered

    async def post(path: str, payload: dict) -> dict:
        return body(await client.post(site.path(path), headers=site.headers, json=payload), 201)

    setup = await catalog(client, site)
    purchase = await ordered(client, site, setup)
    await delivered(client, site, setup, purchase)
    components = [{"stock_item_id": setup["item_id"], "quantity": "2.5", "unit_cost_cents": 400}]
    if unknown_ingredient:
        unknown = await post(
            "/inventory/items", {"sku": "UNKNOWN-A", "name": "Unbewertete Zutat", "unit": "kg"}
        )
        await post(
            "/inventory/receipts",
            {
                "request_key": str(uuid.uuid4()),
                "item_id": unknown["id"],
                "owner_id": setup["owner_id"],
                "location_id": setup["location_id"],
                "quantity": "1",
                "lot_code": "UNKNOWN-LOT",
                "expires_on": (date.today() + timedelta(days=3)).isoformat(),
                "reason": "Altbestand ohne belegten Einstandspreis",
                "reference": "OPEN-UNKNOWN",
            },
        )
        components.append({"stock_item_id": unknown["id"], "quantity": "1", "unit_cost_cents": 0})
    prepped_item = await post(
        "/inventory/items", {"sku": "PREP-A", "name": "Vorbereitete Portion", "unit": "piece"}
    )
    recipe = await post(
        "/recipes",
        {
            "request_key": str(uuid.uuid4()),
            "name": "Prep mit Ausbeute",
            "output_item_id": prepped_item["id"],
            "yield_quantity": "10",
            "allergen_reviewed": True,
            "components": components,
        },
    )
    await post(
        "/prep",
        {
            "request_key": str(uuid.uuid4()),
            "reason": "Tatsächliche Ausbeute gewogen",
            "recipe_id": recipe["id"],
            "batches": "1",
            "output_quantity": "4",
            "location_id": setup["location_id"],
            "owner_id": setup["owner_id"],
            "lot_code": "PREP-4",
            "expires_on": (date.today() + timedelta(days=3)).isoformat(),
        },
    )
    dish = await post(
        "/inventory/items", {"sku": "DISH-A", "name": "Fertiges Gericht", "unit": "piece"}
    )
    menu_recipe = await post(
        "/recipes",
        {
            "request_key": str(uuid.uuid4()),
            "name": "Gericht aus Prep",
            "output_item_id": dish["id"],
            "yield_quantity": "1",
            "menu_item_id": site.item_id,
            "menu_version": 1,
            "allergen_reviewed": True,
            "components": [
                {
                    "stock_item_id": prepped_item["id"],
                    "quantity": "1",
                    "unit_cost_cents": recipe["cost_cents"],
                    "subrecipe_id": recipe["id"],
                }
            ],
        },
    )
    body(
        await client.post(
            site.path(f"/menu/{site.item_id}/publish"),
            headers=site.headers,
            json={"version": menu_recipe["menu_version"]},
        )
    )
    order = await sent_order(
        client,
        site,
        lines=[
            {"item_id": site.item_id, "menu_version": menu_recipe["menu_version"], "quantity": 2}
        ],
    )
    order = await serve(client, site, order)
    session = await till(client, site, hr_workspace)
    await payment(client, site, order, session, order["total_cents"])
    result = body(await client.get(site.path("/insights"), headers=site.headers))
    assert result["dishes"][0]["recipe_cost_cents"] == 200
    assert result["dishes"][0]["actual_consumption_cost_cents"] == (
        None if unknown_ingredient else 500
    )
    prep_usage = next(row for row in result["stock_usage"] if row["item_id"] == prepped_item["id"])
    assert Decimal(prep_usage["unvalued_consumption_quantity"]) == (2 if unknown_ingredient else 0)
    assert sum(row["known_consumption_cost_cents"] for row in result["stock_usage"]) == 500
    raw = next(row for row in result["stock_usage"] if row["item_id"] == setup["item_id"])
    assert Decimal(raw["production_input_quantity"]) == Decimal("2.5")
    assert Decimal(raw["consumed_quantity"]) == 0


@pytest.mark.asyncio
async def test_reserved_people_and_unknown_past_outcomes_do_not_invent_orders_or_no_shows(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    import uuid
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from app.gastro.booking_models import ReservationMeta
    from app.gastro.models import Reservation

    local = ZoneInfo("Europe/Berlin")
    today = datetime.now(local).date()
    for index, status in enumerate(("completed", "no_show", "confirmed", "no_show")):
        start = datetime.combine(today - timedelta(days=index + 1), time(19), tzinfo=local)
        row = Reservation(
            venue_id=uuid.UUID(site.venue_id),
            table_id=uuid.UUID(site.table_id),
            guest_name="Synthetic history",
            guests=2,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            status=status,
        )
        db_session.add(row)
        await db_session.flush()
        db_session.add(
            ReservationMeta(reservation_id=row.id, source="walkin" if index == 3 else "reservation")
        )
    tomorrow = datetime.combine(today + timedelta(days=1), time(19), tzinfo=local)
    db_session.add(
        Reservation(
            venue_id=uuid.UUID(site.venue_id),
            table_id=uuid.UUID(site.table_id),
            guest_name="Synthetic tomorrow",
            guests=6,
            starts_at=tomorrow,
            ends_at=tomorrow + timedelta(hours=1),
            status="confirmed",
        )
    )
    await db_session.flush()
    result = body(await client.get(site.path("/insights"), headers=site.headers))
    assert result["forecast"][0]["reserved_guests"] == 6
    assert result["forecast"][0]["expected_orders"] is None
    assert result["reservation_history"] == {
        "completed_reservations": 1,
        "no_shows": 1,
        "pending_past_reservations": 1,
        "no_show_rate": 0.5,
    }


@pytest.mark.asyncio
async def test_report_snapshot_is_stable_while_other_transactions_keep_writing() -> None:
    import uuid

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.gastro.reporting import reporting_db
    from tests.conftest import TestSessionLocal, test_engine

    table = "report_snapshot_" + uuid.uuid4().hex
    async with test_engine.begin() as connection:
        assert (
            await connection.execute(text("SELECT current_database()"))
        ).scalar_one() == "flintplate_test"
        await connection.execute(text(f"CREATE TABLE {table}(amount integer NOT NULL)"))
        await connection.execute(text(f"INSERT INTO {table} VALUES(100)"))
    try:
        async with TestSessionLocal() as session:
            await reporting_db(session)
            assert (
                await session.execute(text("SHOW transaction_isolation"))
            ).scalar_one() == "repeatable read"
            assert (await session.execute(text("SHOW transaction_read_only"))).scalar_one() == "on"
            assert (await session.execute(text(f"SELECT amount FROM {table}"))).scalar_one() == 100
            async with test_engine.begin() as writer:
                await writer.execute(text(f"UPDATE {table} SET amount=200"))
            assert (await session.execute(text(f"SELECT amount FROM {table}"))).scalar_one() == 100
            with pytest.raises(DBAPIError, match="read-only"):
                await session.execute(text(f"UPDATE {table} SET amount=300"))
        async with test_engine.connect() as reader:
            assert (await reader.execute(text(f"SELECT amount FROM {table}"))).scalar_one() == 200
    finally:
        async with test_engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE {table}"))


def test_report_isolation_dependency_precedes_authentication_query() -> None:
    from app.gastro.insights import router
    from app.gastro.reporting import reporting_db
    from app.security import get_current_user

    route = next(route for route in router.routes if route.path.endswith("/insights"))
    calls = [dependency.call for dependency in route.dependant.dependencies]
    assert calls.index(reporting_db) < calls.index(get_current_user)


@pytest.mark.asyncio
async def test_real_report_requests_read_inventory_without_write_locks(client: AsyncClient) -> None:
    import uuid
    from collections.abc import AsyncIterator

    from app.admin.models import Customer
    from app.database import get_db
    from app.gastro.models import Membership, Venue
    from app.main import app
    from app.security import create_access_token
    from app.users.models import User
    from tests.conftest import TestSessionLocal
    from tests.utils import auth_headers

    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Read-only reports", slug="reports-" + uuid.uuid4().hex, status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email="report-" + uuid.uuid4().hex + "@example.com",
            hashed_password="unused-synthetic",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Read-only snapshot", tenant_id=tenant.id)
        db.add_all([user, venue])
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
        await db.commit()
        headers = auth_headers(create_access_token({"sub": user.email}))
        venue_id = venue.id

    async def independent_session() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as db:
            yield db
            await db.commit()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = independent_session
    try:
        # These HTTP requests establish their own actual READ ONLY transaction.
        # A nested inventory SELECT FOR UPDATE used to fail here with HTTP500.
        for suffix in ("/inventory/snapshot", "/insights"):
            result = await client.get(f"/gastro/venues/{venue_id}{suffix}", headers=headers)
            assert result.status_code == 200, result.text
    finally:
        app.dependency_overrides[get_db] = previous
