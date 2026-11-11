"""Ordering suggestions preserve the source instant, package math and stock boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.models import Venue
from app.gastro.purchasing_models import Supplier, SupplierPrice, SupplierProduct
from app.gastro.purchasing_sources import MAX_SOURCE_OPTIONS, suggested_sources
from app.gastro.purchasing_terms_models import SupplierOrderTerms
from tests.hr_support import body
from tests.test_flintplate import Site
from tests.test_flintplate_purchase_conditions import terms
from tests.test_flintplate_purchasing import catalog, ordered, path

pytest_plugins = ["tests.test_flintplate"]


async def venue_for(db: AsyncSession, site: Site) -> Venue:
    return (
        await db.execute(select(Venue).where(Venue.id == uuid.UUID(site.venue_id)))
    ).scalar_one()


@pytest.mark.asyncio
async def test_sources_round_to_paid_and_free_packages_with_lead_time_and_minimum(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    setup = await catalog(
        client,
        site,
        conditions={
            "minimum_paid_packs": 2,
            "order_multiple": 2,
            "tiers": [{"minimum_paid_packs": 10, "pack_price_cents": 800}],
            "natural_rebate": {"buy_packs": 10, "free_packs": 2},
        },
    )
    venue = await venue_for(db_session, site)
    tomorrow = datetime.now(ZoneInfo(venue.timezone)).date() + timedelta(days=1)
    as_of = datetime.combine(tomorrow, time(18), tzinfo=ZoneInfo(venue.timezone))
    conditions = await terms(
        client,
        site,
        setup,
        minimum_order_net_cents=9000,
        lead_time_calendar_days=2,
        order_cutoff_local="12:00:00",
        excluded_delivery_dates=[(tomorrow + timedelta(days=3)).isoformat()],
    )
    before = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    pending = Supplier(venue_id=venue.id, name="Noch nicht gespeicherter Lieferant")
    db_session.add(pending)
    options = await suggested_sources(
        db_session, venue, uuid.UUID(setup["item_id"]), Decimal(28), as_of
    )
    assert pending in db_session.new  # The helper must not autoflush unrelated caller changes.
    db_session.expunge(pending)
    assert len(options) == 1
    option = options[0]
    assert (option.packs, option.bonus_packs, option.paid_quantity) == (10, 2, Decimal(25))
    assert (option.ordered_quantity, option.ordered_bonus_quantity, option.overage_quantity) == (
        Decimal(30),
        Decimal(5),
        Decimal(2),
    )
    assert (option.pack_price_cents, option.net_cents, option.shortfall_to_minimum_net_cents) == (
        800,
        8000,
        1000,
    )
    assert option.supplier_terms_id == uuid.UUID(conditions["id"])
    assert option.price_id == uuid.UUID(setup["product"]["current_price"]["id"])
    assert option.earliest_delivery_on == tomorrow + timedelta(days=4)
    assert "Mindestbestellwert" in option.blocking_reasons[0]
    assert option.unit == "kg" and option.currency == "EUR"
    after = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert after == before


@pytest.mark.asyncio
async def test_sources_only_use_prices_and_rules_known_and_effective_at_as_of(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    setup = await catalog(client, site)
    original_terms = await terms(client, site, setup, lead_time_calendar_days=2)
    venue = await venue_for(db_session, site)
    as_of = datetime.now(UTC) + timedelta(days=2)
    local_day = as_of.astimezone(ZoneInfo(venue.timezone)).date()
    original_price = await db_session.get(
        SupplierPrice, uuid.UUID(setup["product"]["current_price"]["id"])
    )
    assert original_price is not None
    for version, effective_on, created_at in (
        (2, original_price.effective_on, as_of + timedelta(days=1)),
        (3, local_day + timedelta(days=1), datetime.now(UTC)),
    ):
        db_session.add(
            SupplierPrice(
                venue_id=venue.id,
                product_id=original_price.product_id,
                version=version,
                effective_on=effective_on,
                created_at=created_at,
                pack_price_cents=version * 100,
                tax_rate_bps=700,
                actor_id=original_price.actor_id,
            )
        )
        db_session.add(
            SupplierOrderTerms(
                venue_id=venue.id,
                supplier_id=uuid.UUID(setup["supplier_id"]),
                version=version,
                effective_on=effective_on,
                created_at=created_at,
                rules={"lead_time_calendar_days": 30},
                request_key=uuid.uuid4(),
                request_hash="historical-fixture",
                reason="Stichtagsprüfung",
                actor_id=original_price.actor_id,
            )
        )
    await db_session.flush()
    current = (
        await suggested_sources(db_session, venue, uuid.UUID(setup["item_id"]), Decimal(5), as_of)
    )[0]
    assert current.price_id == original_price.id
    assert current.supplier_terms_id == uuid.UUID(original_terms["id"])
    assert current.pack_price_cents == 1000
    future = (
        await suggested_sources(
            db_session, venue, uuid.UUID(setup["item_id"]), Decimal(5), as_of + timedelta(days=2)
        )
    )[0]
    assert future.price_version == future.supplier_terms_version == 3
    assert future.pack_price_cents == 300


@pytest.mark.asyncio
async def test_unknown_terms_stay_unknown_and_unconfirmed_orders_do_not_reduce_need(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    setup = await catalog(client, site)
    await ordered(client, site, setup)
    venue = await venue_for(db_session, site)
    option = (
        await suggested_sources(
            db_session, venue, uuid.UUID(setup["item_id"]), Decimal(5), datetime.now(UTC)
        )
    )[0]
    assert option.need_quantity == option.ordered_quantity == Decimal(5)
    assert option.packs == 2 and option.net_cents == 2000
    assert option.supplier_terms_id is None and option.earliest_delivery_on is None
    assert option.shortfall_to_minimum_net_cents is None
    assert option.minimum_order_net_cents is None and not option.blocking_reasons
    other = body(
        await client.post("/gastro/venues", headers=site.headers, json={"name": "Andere Quellen"}),
        201,
    )
    foreign = await venue_for(db_session, Site(other["id"], "", "", site.headers))
    assert not await suggested_sources(
        db_session, foreign, uuid.UUID(setup["item_id"]), Decimal(5), datetime.now(UTC)
    )
    assert not await suggested_sources(
        db_session, venue, uuid.uuid4(), Decimal(5), datetime.now(UTC)
    )
    assert not await suggested_sources(
        db_session, venue, uuid.UUID(setup["item_id"]), Decimal(0), datetime.now(UTC)
    )


@pytest.mark.asyncio
async def test_blocked_offer_does_not_hide_other_priced_catalog_options(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    setup = await catalog(client, site)
    venue = await venue_for(db_session, site)
    for sku, effective, conditions in (
        ("A-TOO-LARGE", datetime.now(UTC).date(), {"minimum_paid_packs": 1000000}),
        ("B-FUTURE", datetime.now(UTC).date() + timedelta(days=30), {}),
    ):
        body(
            await client.post(
                path(site, "/catalog"),
                headers=site.headers,
                json={
                    "supplier_id": setup["supplier_id"],
                    "item_id": setup["item_id"],
                    "supplier_sku": sku,
                    "pack_name": "Großgebinde",
                    "pack_quantity": "1000",
                    "pack_price_cents": 1000,
                    "tax_rate_bps": 700,
                    "effective_on": effective.isoformat(),
                    "conditions": conditions,
                },
            ),
            201,
        )
    options = await suggested_sources(
        db_session, venue, uuid.UUID(setup["item_id"]), Decimal(1), datetime.now(UTC)
    )
    assert len(options) == 2
    blocked, normal = options
    assert blocked.supplier_sku == "A-TOO-LARGE" and blocked.packs is None
    assert blocked.blocking_reasons and blocked.net_cents is None
    assert normal.supplier_sku == "TOM-BOX" and normal.packs == 1
    assert normal.ordered_quantity == Decimal("2.5") and not normal.blocking_reasons


@pytest.mark.asyncio
async def test_sources_limit_is_deterministic_and_invalid_inputs_fail_before_queries(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    setup = await catalog(client, site)
    venue = await venue_for(db_session, site)
    original_price = await db_session.get(
        SupplierPrice, uuid.UUID(setup["product"]["current_price"]["id"])
    )
    assert original_price is not None
    for index in range(MAX_SOURCE_OPTIONS):
        product = SupplierProduct(
            id=uuid.uuid4(),
            venue_id=venue.id,
            supplier_id=uuid.UUID(setup["supplier_id"]),
            item_id=uuid.UUID(setup["item_id"]),
            supplier_sku=f"SOURCE-{index:03}",
            pack_name="Karton",
            pack_quantity=Decimal(1),
        )
        db_session.add(product)
        await db_session.flush()
        db_session.add(
            SupplierPrice(
                venue_id=venue.id,
                product_id=product.id,
                version=1,
                effective_on=original_price.effective_on,
                pack_price_cents=1000,
                tax_rate_bps=700,
                actor_id=original_price.actor_id,
            )
        )
    await db_session.flush()
    as_of = datetime.now(UTC)
    item_id = uuid.UUID(setup["item_id"])
    all_options = await suggested_sources(db_session, venue, item_id, Decimal(1), as_of)
    assert len(all_options) == MAX_SOURCE_OPTIONS
    assert [row.supplier_sku for row in all_options] == [
        f"SOURCE-{index:03}" for index in range(MAX_SOURCE_OPTIONS)
    ]
    limited = await suggested_sources(db_session, venue, item_id, Decimal(1), as_of, limit=3)
    assert limited == all_options[:3]
    for invalid in (0, MAX_SOURCE_OPTIONS + 1, True):
        with pytest.raises(ValueError, match="1 bis 50"):
            await suggested_sources(db_session, venue, item_id, Decimal(1), as_of, limit=invalid)
    with pytest.raises(ValueError, match="Zeitzonenbezug"):
        await suggested_sources(db_session, venue, item_id, Decimal(1), as_of.replace(tzinfo=None))
    for invalid_need in (Decimal(-1), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError, match="nichtnegative"):
            await suggested_sources(db_session, venue, item_id, invalid_need, as_of)
