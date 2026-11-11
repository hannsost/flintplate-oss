"""077 acceptance: physical free goods, frozen terms and traceable supplier bonuses."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.database import Base, get_db
from app.gastro.models import Membership, Venue
from app.gastro.purchasing_math import earliest_delivery, minimum_packs_for_need, request_digest
from app.gastro.purchasing_schemas import PurchaseOrderInput, PurchaseReceiptInput
from app.gastro.purchasing_terms_schemas import ProductConditions, SupplierRules
from app.main import app
from app.security import create_access_token
from app.users.models import User
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.test_flintplate_purchasing import (
    approve,
    catalog,
    delivered,
    delivery_input,
    invoice,
    order_input,
    ordered,
    path,
)
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]


def assert_migrated_orm_columns(
    sync: Connection,
    schema: str,
    table_names: tuple[str, ...],
    *,
    historical_checkpoint: bool = False,
) -> None:
    """Reflect installed DDL; create_all would conceal a missing inherited column."""
    reflected = inspect(sync)
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        installed = {
            column["name"]: column for column in reflected.get_columns(table_name, schema=schema)
        }
        expected = {column.name: column for column in table.columns}
        missing = set(expected) - set(installed)
        if historical_checkpoint:
            # Later revisions extend these models. The current-head chain test
            # checks completeness; this checkpoint retains strict checks for
            # installed fields and both inherited timestamps.
            missing &= {"id", "created_at", "updated_at"}
        assert not missing and not set(installed) - set(expected), (
            table_name,
            "missing",
            missing,
            "extra",
            set(installed) - set(expected),
        )
        for name, column in expected.items():
            if name not in installed:
                continue
            actual = installed[name]
            assert actual["nullable"] == column.nullable, (table_name, name, "nullable")
            assert actual["type"].compile(dialect=sync.dialect) == column.type.compile(
                dialect=sync.dialect
            ), (table_name, name, "type")
            if name in {"created_at", "updated_at"}:
                assert actual["default"] is not None, (table_name, name, "timestamp server default")
        primary_key = reflected.get_pk_constraint(table_name, schema=schema)["constrained_columns"]
        assert set(primary_key) == {column.name for column in table.primary_key.columns}, table_name
        # Use ORM column definitions for the fields installed at this revision.
        sync.execute(
            select(*(column for column in table.columns if column.name in installed)).limit(0)
        ).all()


def booking(**fields: object) -> dict:
    return {"request_key": str(uuid.uuid4()), "reason": "Geprüfte Einkaufskondition", **fields}


def ordered_packs(setup: dict, packs: int) -> list[dict]:
    product = setup["product"]
    return [
        {"product_id": product["id"], "price_id": product["current_price"]["id"], "packs": packs}
    ]


async def terms(client: AsyncClient, site: Site, setup: dict, **rules: object) -> dict:
    return body(
        await client.post(
            path(site, "/supplier-terms"),
            headers=site.headers,
            json=booking(
                supplier_id=setup["supplier_id"],
                expected_version=0,
                effective_on=date.today().isoformat(),
                rules=rules,
            ),
        ),
        201,
    )


async def agreement(client: AsyncClient, site: Site, setup: dict, **changes: object) -> dict:
    yesterday = date.today() - timedelta(days=1)
    fields = {
        "supplier_id": setup["supplier_id"],
        "reference": f"BON-{uuid.uuid4().hex}",
        "period_start": (yesterday - timedelta(days=20)).isoformat(),
        "period_end": yesterday.isoformat(),
        "rate_bps": 1000,
        **changes,
    }
    return body(
        await client.post(
            path(site, "/bonus-agreements"), headers=site.headers, json=booking(**fields)
        ),
        201,
    )


async def state(client: AsyncClient, site: Site, contract: dict, **changes: object) -> dict:
    preview = body(
        await client.get(
            path(site, f"/bonus-agreements/{contract['id']}/preview"), headers=site.headers
        )
    )
    return body(
        await client.post(
            path(site, "/bonus-statements"),
            headers=site.headers,
            json=booking(
                agreement_id=contract["id"], fingerprint=preview["fingerprint"], **changes
            ),
        ),
        201,
    )


async def old_invoice(
    client: AsyncClient, site: Site, setup: dict, order: dict, *, qty: str = "5", net: int = 2000
) -> dict:
    bill = await invoice(
        client,
        site,
        setup,
        order,
        issued_on=(date.today() - timedelta(days=1)).isoformat(),
        lines=[
            {
                "purchase_line_id": order["lines"][0]["id"],
                "quantity": qty,
                "net_cents": net,
                "tax_rate_bps": 700,
            }
        ],
    )
    return await approve(client, site, bill)


@pytest.mark.asyncio
async def test_natural_rebate_adds_physical_stock_but_never_extra_invoice_quantity(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(
        client,
        site,
        conditions={
            "tiers": [{"minimum_paid_packs": 10, "pack_price_cents": 800}],
            "natural_rebate": {"buy_packs": 10, "free_packs": 1},
        },
    )
    order = await ordered(client, site, setup, lines=ordered_packs(setup, 10))
    line = order["lines"][0]
    assert (
        Decimal(line["ordered_quantity"]),
        Decimal(line["ordered_bonus_quantity"]),
        order["net_cents"],
    ) == (Decimal("27.5"), Decimal("2.5"), 8000)
    order = await delivered(
        client, site, setup, order, accepted_quantity="27.5", accepted_bonus_quantity="2.5"
    )
    assert Decimal(order["lines"][0]["billable_received_quantity"]) == 25
    bill = await invoice(
        client,
        site,
        setup,
        order,
        lines=[
            {
                "purchase_line_id": line["id"],
                "quantity": "27.5",
                "net_cents": 8800,
                "tax_rate_bps": 700,
            }
        ],
    )
    assert not bill["check"]["matched"]
    correct = await invoice(
        client,
        site,
        setup,
        order,
        lines=[
            {
                "purchase_line_id": line["id"],
                "quantity": "25",
                "net_cents": 8000,
                "tax_rate_bps": 700,
            }
        ],
    )
    assert (await approve(client, site, correct))["check"]["matched"]
    inventory = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert sum(Decimal(row["quantity"]) for row in inventory["balances"]) == Decimal("27.5")


@pytest.mark.asyncio
async def test_free_delivery_can_arrive_first_and_is_bounded_separately(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(
        client, site, conditions={"natural_rebate": {"buy_packs": 2, "free_packs": 1}}
    )
    order = await ordered(client, site, setup)
    first = await delivered(
        client, site, setup, order, accepted_quantity="2.5", accepted_bonus_quantity="2.5"
    )
    assert Decimal(first["lines"][0]["billable_received_quantity"]) == 0
    too_much = delivery_input(setup, first, accepted_quantity="0.1", accepted_bonus_quantity="0.1")
    body(
        await client.post(
            path(site, f"/orders/{order['id']}/receipts"), headers=site.headers, json=too_much
        ),
        409,
    )
    complete = await delivered(client, site, setup, first, accepted_quantity="5")
    assert complete["status"] == "received"
    assert Decimal(complete["lines"][0]["received_bonus_quantity"]) == Decimal("2.5")


@pytest.mark.asyncio
async def test_identical_total_with_changed_free_split_is_not_an_idempotent_retry(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(
        client, site, conditions={"natural_rebate": {"buy_packs": 2, "free_packs": 1}}
    )
    order = await ordered(client, site, setup)
    data = delivery_input(setup, order, accepted_quantity="2.5", accepted_bonus_quantity="2.5")
    endpoint = path(site, f"/orders/{order['id']}/receipts")
    one = body(await client.post(endpoint, headers=site.headers, json=data), 201)
    two = body(await client.post(endpoint, headers=site.headers, json=data), 201)
    assert one["receipts"][0]["id"] == two["receipts"][0]["id"]
    body(
        await client.post(
            endpoint, headers=site.headers, json={**data, "accepted_bonus_quantity": "0"}
        ),
        409,
    )


@pytest.mark.asyncio
async def test_minimum_order_value_blocks_release_but_preserves_reviewable_draft(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    rule = await terms(client, site, setup, minimum_order_net_cents=3000, lead_time_calendar_days=2)
    quote = body(
        await client.post(
            path(site, "/quotes"),
            headers=site.headers,
            json={"supplier_id": setup["supplier_id"], "lines": ordered_packs(setup, 2)},
        )
    )
    assert (
        quote["shortfall_to_minimum_net_cents"] == 1000 and quote["supplier_terms_id"] == rule["id"]
    )
    draft = body(
        await client.post(
            path(site, "/orders"),
            headers=site.headers,
            json=order_input(setup, supplier_terms_id=rule["id"]),
        ),
        201,
    )
    assert draft["shortfall_to_minimum_net_cents"] == 1000
    body(
        await client.post(
            path(site, f"/orders/{draft['id']}/state"),
            headers=site.headers,
            json={"version": 1, "status": "ordered", "reason": "Zu kleiner Warenkorb"},
        ),
        409,
    )
    assert (await ordered(client, site, setup, lines=ordered_packs(setup, 3)))[
        "status"
    ] == "ordered"


@pytest.mark.asyncio
async def test_pack_minimum_and_absolute_multiple_are_enforced_on_server(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site, conditions={"minimum_paid_packs": 3, "order_multiple": 2})
    for packs in (2, 3, 5):
        body(
            await client.post(
                path(site, "/orders"),
                headers=site.headers,
                json=order_input(setup, lines=ordered_packs(setup, packs)),
            ),
            422,
        )
    assert (await ordered(client, site, setup, lines=ordered_packs(setup, 4)))["net_cents"] == 4000


@pytest.mark.asyncio
async def test_changed_delivery_terms_reject_stale_draft_without_rewriting_it(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    rule = await terms(client, site, setup, minimum_order_net_cents=1000)
    draft = body(
        await client.post(path(site, "/orders"), headers=site.headers, json=order_input(setup)), 201
    )
    body(
        await client.post(
            path(site, "/supplier-terms"),
            headers=site.headers,
            json=booking(
                supplier_id=setup["supplier_id"],
                expected_version=1,
                effective_on=date.today().isoformat(),
                rules={"minimum_order_net_cents": 5000},
            ),
        ),
        201,
    )
    body(
        await client.post(
            path(site, f"/orders/{draft['id']}/state"),
            headers=site.headers,
            json={"version": 1, "status": "ordered", "reason": "Alter Entwurf"},
        ),
        409,
    )
    assert (
        draft["supplier_terms_id"] == rule["id"]
        and draft["supplier_terms_snapshot"]["minimum_order_net_cents"] == 1000
    )


def test_071_request_hashes_survive_default_bonus_and_supplier_terms_fields() -> None:
    ids = {
        key: str(uuid.uuid4())
        for key in (
            "line_id",
            "location_id",
            "request_key",
            "supplier_id",
            "owner_id",
            "product_id",
            "price_id",
        )
    }
    receipt = PurchaseReceiptInput(
        **{key: ids[key] for key in ("line_id", "location_id", "request_key")},
        reason="Legacy receipt",
        accepted_quantity="5",
        lot_code="OLD",
        reference="LS-OLD",
    )
    old_receipt = receipt.model_dump(mode="json")
    old_receipt.pop("accepted_bonus_quantity")
    old_receipt.pop("rejected_bonus_quantity")
    old_receipt.pop("confirmation_id")
    old_receipt.pop("unconfirmed_delivery_reason")
    old_hash = hashlib.sha256(
        json.dumps(old_receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert request_digest(receipt) == old_hash
    order = PurchaseOrderInput(
        **{key: ids[key] for key in ("supplier_id", "owner_id", "location_id", "request_key")},
        reason="Legacy order",
        lines=[{"product_id": ids["product_id"], "price_id": ids["price_id"], "packs": 2}],
    )
    old_order = order.model_dump(mode="json")
    old_order.pop("supplier_terms_id")
    assert (
        request_digest(order)
        == hashlib.sha256(
            json.dumps(old_order, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_purchase_planning_obeys_cutoff_calendar_and_minimal_needed_packs() -> None:
    rules = SupplierRules(
        lead_time_calendar_days=2, delivery_weekdays=[1, 3], order_cutoff_local="14:00"
    )
    assert earliest_delivery(datetime(2026, 9, 11, 13, tzinfo=UTC), rules, "Europe/Berlin") == date(
        2026, 9, 15
    )
    conditions = ProductConditions.model_validate(
        {"natural_rebate": {"buy_packs": 10, "free_packs": 1}}
    )
    assert minimum_packs_for_need(Decimal("26.8"), Decimal("2.5"), conditions) == 10
    assert minimum_packs_for_need(Decimal(0), Decimal("2.5"), conditions) == 0


@pytest.mark.asyncio
async def test_bonus_statement_and_partial_credit_leave_physical_stock_unchanged(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    await delivered(client, site, setup, order)
    await old_invoice(client, site, setup, order)
    contract = await agreement(client, site, setup)
    statement = await state(client, site, contract)
    assert statement["delta_cents"] == 200 and len(statement["snapshot"]["sources"]) == 1
    doc_data = booking(
        supplier_id=setup["supplier_id"],
        reference="CREDIT-1",
        issued_on=date.today().isoformat(),
        net_cents=120,
        tax_cents=8,
        currency="EUR",
    )
    document = body(
        await client.post(path(site, "/bonus-documents"), headers=site.headers, json=doc_data), 201
    )
    allocate = booking(document_id=document["id"], agreement_id=contract["id"], amount_cents=120)
    first = body(
        await client.post(path(site, "/bonus-allocations"), headers=site.headers, json=allocate),
        201,
    )
    again = body(
        await client.post(path(site, "/bonus-allocations"), headers=site.headers, json=allocate),
        201,
    )
    assert first["id"] == again["id"]
    snapshot = body(await client.get(path(site, "/bonuses"), headers=site.headers))
    assert snapshot["balances"][0]["remaining_cents"] == 80
    assert snapshot["documents"][0]["remaining_cents"] == 0
    stock = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert sum(Decimal(row["quantity"]) for row in stock["balances"]) == 5


@pytest.mark.asyncio
async def test_late_invoice_recognition_creates_only_incremental_bonus_claim(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup, lines=ordered_packs(setup, 4))
    await delivered(client, site, setup, order, accepted_quantity="10")
    await old_invoice(client, site, setup, order)
    contract = await agreement(client, site, setup)
    assert (await state(client, site, contract))["delta_cents"] == 200
    await old_invoice(client, site, setup, order)
    second = await state(client, site, contract)
    assert second["sequence"] == 2 and second["delta_cents"] == 200
    assert second["snapshot"]["claim_cents"] == 400 and len(second["snapshot"]["sources"]) == 2
    unchanged = body(
        await client.get(
            path(site, f"/bonus-agreements/{contract['id']}/preview"), headers=site.headers
        )
    )
    body(
        await client.post(
            path(site, "/bonus-statements"),
            headers=site.headers,
            json=booking(agreement_id=contract["id"], fingerprint=unchanged["fingerprint"]),
        ),
        409,
    )


@pytest.mark.asyncio
async def test_bonus_fingerprint_detects_additional_invoice_before_statement(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    await delivered(client, site, setup, order)
    contract = await agreement(client, site, setup)
    before = body(
        await client.get(
            path(site, f"/bonus-agreements/{contract['id']}/preview"), headers=site.headers
        )
    )
    await old_invoice(client, site, setup, order)
    body(
        await client.post(
            path(site, "/bonus-statements"),
            headers=site.headers,
            json=booking(agreement_id=contract["id"], fingerprint=before["fingerprint"]),
        ),
        409,
    )


@pytest.mark.asyncio
async def test_bonus_documents_cannot_be_reused_or_allocated_beyond_claim(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    contract = await agreement(client, site, setup)
    await state(client, site, contract)
    doc_data = booking(
        supplier_id=setup["supplier_id"],
        reference="ONCE",
        issued_on=date.today().isoformat(),
        net_cents=200,
        tax_cents=14,
        currency="EUR",
    )
    doc = body(
        await client.post(path(site, "/bonus-documents"), headers=site.headers, json=doc_data), 201
    )
    body(
        await client.post(
            path(site, "/bonus-documents"),
            headers=site.headers,
            json={**doc_data, "request_key": str(uuid.uuid4())},
        ),
        409,
    )
    body(
        await client.post(
            path(site, "/bonus-allocations"),
            headers=site.headers,
            json=booking(document_id=doc["id"], agreement_id=contract["id"], amount_cents=1),
        ),
        409,
    )
    body(
        await client.post(
            path(site, "/bonus-allocations"),
            headers=site.headers,
            json=booking(
                document_id=str(uuid.uuid4()), agreement_id=contract["id"], amount_cents=1
            ),
        ),
        404,
    )


@pytest.mark.asyncio
async def test_terms_and_bonuses_reject_wrong_role_tenant_supplier_and_venue(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await catalog(client, site)
    data = booking(
        supplier_id=setup["supplier_id"],
        expected_version=0,
        effective_on=date.today().isoformat(),
        rules={},
    )
    body(
        await client.post(
            path(site, "/supplier-terms"), headers=hr_workspace.headers("worker"), json=data
        ),
        403,
    )
    body(await client.get(path(site, "/bonuses"), headers=hr_workspace.headers("other_hr")), 404)
    other_venue = body(
        await client.post(
            "/gastro/venues", headers=site.headers, json={"name": "Andere Konditionen"}
        ),
        201,
    )
    other = Site(other_venue["id"], "", "", site.headers)
    foreign = await catalog(client, other)
    body(
        await client.post(
            path(site, "/supplier-terms"),
            headers=site.headers,
            json={**data, "supplier_id": foreign["supplier_id"]},
        ),
        404,
    )
    foreign_contract = await agreement(client, other, foreign)
    body(
        await client.get(
            path(site, f"/bonus-agreements/{foreign_contract['id']}/preview"), headers=site.headers
        ),
        404,
    )
    contract = await agreement(client, site, setup)
    other_supplier = body(
        await client.post(
            path(site, "/suppliers"), headers=site.headers, json={"name": "Falscher Bonuslieferant"}
        ),
        201,
    )
    doc = body(
        await client.post(
            path(site, "/bonus-documents"),
            headers=site.headers,
            json=booking(
                supplier_id=other_supplier["id"],
                reference="FOREIGN-SUPPLIER",
                issued_on=date.today().isoformat(),
                net_cents=100,
                tax_cents=7,
                currency="EUR",
            ),
        ),
        201,
    )
    body(
        await client.post(
            path(site, "/bonus-allocations"),
            headers=site.headers,
            json=booking(document_id=doc["id"], agreement_id=contract["id"], amount_cents=100),
        ),
        422,
    )


@pytest.mark.asyncio
async def test_partner_owned_purchases_do_not_create_own_supplier_bonus(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    partner = body(
        await client.post(
            site.path("/inventory/owners"),
            headers=site.headers,
            json={"name": "Kommissionsinhaber", "kind": "partner"},
        ),
        201,
    )
    order = await ordered(client, site, setup, owner_id=partner["id"])
    await delivered(client, site, setup, order)
    await old_invoice(client, site, setup, order)
    contract = await agreement(client, site, setup)
    preview = body(
        await client.get(
            path(site, f"/bonus-agreements/{contract['id']}/preview"), headers=site.headers
        )
    )
    assert preview["source_net_cents"] == 0 and preview["sources"] == []


@pytest.mark.asyncio
async def test_open_bonus_period_and_overlapping_agreement_cannot_be_closed_twice(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    contract = await agreement(client, site, setup, period_end=date.today().isoformat())
    preview = body(
        await client.get(
            path(site, f"/bonus-agreements/{contract['id']}/preview"), headers=site.headers
        )
    )
    assert preview["blocking_reasons"]
    body(
        await client.post(
            path(site, "/bonus-statements"),
            headers=site.headers,
            json=booking(agreement_id=contract["id"], fingerprint=preview["fingerprint"]),
        ),
        409,
    )
    duplicate = {
        key: contract[key] for key in ("supplier_id", "period_start", "period_end", "rate_bps")
    }
    body(
        await client.post(
            path(site, "/bonus-agreements"),
            headers=site.headers,
            json=booking(**duplicate, reference="OVERLAP"),
        ),
        409,
    )


@pytest.mark.asyncio
async def test_parallel_bonus_allocations_cannot_overdraw_the_same_claim(
    client: AsyncClient,
) -> None:
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Bonus concurrency", slug=f"bonus-{uuid.uuid4().hex}", status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email=f"bonus-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name="Bonus manager",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Concurrent bonus", tenant_id=tenant.id)
        db.add_all([user, venue])
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
        site = Site(str(venue.id), "", "", auth_headers(create_access_token({"sub": user.email})))
        await db.commit()

    async def isolated_db() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as db:
            yield db
            await db.commit()

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = isolated_db
    try:
        setup = await catalog(client, site)
        order = await ordered(client, site, setup)
        await delivered(client, site, setup, order)
        await old_invoice(client, site, setup, order)
        contract = await agreement(client, site, setup)
        await state(client, site, contract)
        doc = body(
            await client.post(
                path(site, "/bonus-documents"),
                headers=site.headers,
                json=booking(
                    supplier_id=setup["supplier_id"],
                    reference="CONCURRENT",
                    issued_on=date.today().isoformat(),
                    net_cents=300,
                    tax_cents=21,
                    currency="EUR",
                ),
            ),
            201,
        )
        results = await asyncio.gather(
            *(
                client.post(
                    path(site, "/bonus-allocations"),
                    headers=site.headers,
                    json=booking(
                        document_id=doc["id"], agreement_id=contract["id"], amount_cents=150
                    ),
                )
                for _ in range(2)
            )
        )
        assert sorted(result.status_code for result in results) == [201, 409]
        snapshot = body(await client.get(path(site, "/bonuses"), headers=site.headers))
        assert snapshot["balances"][0]["remaining_cents"] == 50
        assert snapshot["documents"][0]["remaining_cents"] == 150
    finally:
        app.dependency_overrides[get_db] = original


@pytest.mark.asyncio
async def test_077_migration_preserves_071_evidence_and_refuses_destructive_downgrade(
    db_session: AsyncSession,
) -> None:
    migrations = []
    for name in (
        "071_flintplate_purchasing",
        "076a_flintplate_inventory_timestamps",
        "077_flintplate_purchase_conditions",
    ):
        spec = importlib.util.spec_from_file_location(name, Path(f"alembic/versions/{name}.py"))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        migrations.append(module)
    connection = await db_session.connection()

    def install(sync: Connection) -> None:
        schema = f"conditions_migration_{uuid.uuid4().hex}"
        old_path = sync.execute(text("SHOW search_path")).scalar_one()
        old_map = sync.get_execution_options().get("schema_translate_map")
        sync.execution_options(schema_translate_map=None)
        sync.execute(text(f'CREATE SCHEMA "{schema}"'))
        sync.execute(
            text("SELECT set_config('search_path', :path, true)"), {"path": f"{schema},public"}
        )
        try:
            sync.execute(text("CREATE TABLE fp_venues (id uuid PRIMARY KEY)"))
            sync.execute(text("CREATE TABLE users (id uuid PRIMARY KEY)"))
            for table in (
                "fp_stock_items",
                "fp_stock_owners",
                "fp_stock_locations",
                "fp_stock_operations",
            ):
                sync.execute(
                    text(
                        f"CREATE TABLE {table} (id uuid PRIMARY KEY, venue_id uuid NOT NULL, UNIQUE(venue_id,id))"
                    )
                )
            with Operations.context(MigrationContext.configure(sync)):
                migrations[0].upgrade()
                legacy = {
                    key: uuid.uuid4()
                    for key in (
                        "venue",
                        "user",
                        "supplier",
                        "item",
                        "owner",
                        "location",
                        "operation",
                        "product",
                        "price",
                        "order",
                        "line",
                        "receipt",
                        "order_key",
                        "receipt_key",
                    )
                }
                for statement in (
                    "INSERT INTO fp_venues VALUES (:venue)",
                    "INSERT INTO users VALUES (:user)",
                    "INSERT INTO fp_stock_items VALUES (:item,:venue)",
                    "INSERT INTO fp_stock_owners VALUES (:owner,:venue)",
                    "INSERT INTO fp_stock_locations VALUES (:location,:venue)",
                    "INSERT INTO fp_stock_operations VALUES (:operation,:venue)",
                    "INSERT INTO fp_suppliers(id,venue_id,name) VALUES (:supplier,:venue,'Legacy supplier')",
                    "INSERT INTO fp_supplier_products(id,venue_id,supplier_id,item_id,supplier_sku,pack_name,pack_quantity) VALUES (:product,:venue,:supplier,:item,'LEGACY','Box',2.5)",
                    "INSERT INTO fp_supplier_prices(id,venue_id,product_id,version,effective_on,pack_price_cents,tax_rate_bps,actor_id) VALUES (:price,:venue,:product,1,CURRENT_DATE,1000,700,:user)",
                    "INSERT INTO fp_purchase_orders(id,venue_id,supplier_id,owner_id,location_id,number,request_key,request_hash,currency,note,actor_id) VALUES (:order,:venue,:supplier,:owner,:location,'OLD-1',:order_key,'old-order-hash','EUR','Legacy order',:user)",
                    "INSERT INTO fp_purchase_order_lines(id,venue_id,order_id,product_id,item_id,price_id,item_name,unit,supplier_sku,pack_name,pack_quantity,packs,ordered_quantity,pack_price_cents,tax_rate_bps) VALUES (:line,:venue,:order,:product,:item,:price,'Legacy kg','kg','LEGACY','Box',2.5,2,5,1000,700)",
                    "UPDATE fp_purchase_orders SET status='ordered',version=2 WHERE id=:order",
                    "INSERT INTO fp_purchase_receipts(id,venue_id,line_id,stock_operation_id,request_key,request_hash,accepted_quantity,rejected_quantity,reference,rejection_reason,details,actor_id) VALUES (:receipt,:venue,:line,:operation,:receipt_key,'old-receipt-hash',5,0,'LS-OLD','','{}'::jsonb,:user)",
                ):
                    sync.execute(text(statement), legacy)
                # 076a repairs all inventory-family tables. Only the purchasing
                # subset needs full prior DDL here; unrelated tables are explicit
                # prerequisites, never generated from ORM metadata.
                existing_tables = set(inspect(sync).get_table_names(schema=schema))
                for table_name in migrations[1].TABLES:
                    if table_name not in existing_tables:
                        sync.execute(text(f"CREATE TABLE {table_name} (id uuid PRIMARY KEY)"))
                migrations[1].upgrade()
                migrations[2].upgrade()
                assert sync.execute(
                    text(
                        "SELECT accepted_bonus_quantity,request_hash FROM fp_purchase_receipts WHERE id=:receipt"
                    ),
                    legacy,
                ).one() == (Decimal(0), "old-receipt-hash")
                migrations[2].downgrade()
                # Downgrade to 076a must retain the repaired timestamp guard.
                sync.execute(
                    text(
                        "INSERT INTO fp_purchase_invoices(id,venue_id,supplier_id,number,issued_on,currency,request_key,request_hash,actor_id) VALUES (gen_random_uuid(),:venue,:supplier,'GUARD-076a',CURRENT_DATE,'EUR',gen_random_uuid(),'guard-hash',:user)"
                    ),
                    legacy,
                )
                sync.execute(
                    text(
                        "UPDATE fp_purchase_invoices SET status='approved',version=2,updated_at=updated_at + interval '1 second',approval_snapshot='{}'::jsonb WHERE number='GUARD-076a'"
                    )
                )
                with pytest.raises(DBAPIError, match="immutable"), sync.begin_nested():
                    sync.execute(
                        text(
                            "UPDATE fp_purchase_invoices SET currency='USD',version=3,updated_at=now() WHERE number='GUARD-076a'"
                        )
                    )
                migrations[2].upgrade()
            compared_tables = (
                "fp_suppliers",
                "fp_supplier_products",
                "fp_supplier_prices",
                "fp_purchase_orders",
                "fp_purchase_order_lines",
                "fp_purchase_receipts",
                "fp_purchase_invoices",
                "fp_purchase_invoice_lines",
                "fp_supplier_order_terms",
                "fp_supplier_bonus_agreements",
                "fp_supplier_bonus_statements",
                "fp_supplier_bonus_documents",
                "fp_supplier_bonus_allocations",
            )
            assert_migrated_orm_columns(sync, schema, compared_tables, historical_checkpoint=True)
            with sync.begin_nested() as omitted_timestamp:
                sync.execute(text("ALTER TABLE fp_supplier_order_terms DROP COLUMN updated_at"))
                with pytest.raises(AssertionError, match="updated_at"):
                    assert_migrated_orm_columns(
                        sync, schema, ("fp_supplier_order_terms",), historical_checkpoint=True
                    )
                omitted_timestamp.rollback()
            assert_migrated_orm_columns(sync, schema, compared_tables, historical_checkpoint=True)
            sync.execute(
                text(
                    "INSERT INTO fp_purchase_invoices(id,venue_id,supplier_id,number,issued_on,currency,request_key,request_hash,actor_id) VALUES (gen_random_uuid(),:venue,:supplier,'GUARD-077',CURRENT_DATE,'EUR',gen_random_uuid(),'guard-hash',:user)"
                ),
                legacy,
            )
            sync.execute(
                text(
                    "UPDATE fp_purchase_invoices SET status='approved',version=2,updated_at=updated_at + interval '1 second',decided_at=now(),approval_snapshot='{}'::jsonb WHERE number='GUARD-077'"
                )
            )
            with pytest.raises(DBAPIError, match="immutable"), sync.begin_nested():
                sync.execute(
                    text(
                        "UPDATE fp_purchase_invoices SET status='draft',version=3,updated_at=now() WHERE number='GUARD-077'"
                    )
                )
            ids = {
                name: uuid.uuid4()
                for name in (
                    "venue",
                    "user",
                    "supplier",
                    "rule",
                    "key",
                    "agreement",
                    "statement",
                    "document",
                    "allocation",
                )
            }
            for statement in (
                "INSERT INTO fp_venues VALUES (:venue)",
                "INSERT INTO users VALUES (:user)",
                "INSERT INTO fp_suppliers(id,venue_id,name) VALUES (:supplier,:venue,'Test supplier')",
                "INSERT INTO fp_supplier_order_terms(id,venue_id,supplier_id,version,effective_on,rules,request_key,request_hash,reason,actor_id) VALUES (:rule,:venue,:supplier,1,CURRENT_DATE,'{}'::jsonb,:key,'hash','terms',:user)",
                "INSERT INTO fp_supplier_bonus_agreements(id,venue_id,supplier_id,reference,period_start,period_end,currency,source_basis,rate_bps,threshold_cents,mode,request_key,request_hash,reason,actor_id) VALUES (:agreement,:venue,:supplier,'BON-TEST',CURRENT_DATE,CURRENT_DATE,'EUR','own_approved_invoice_net_before_credits',100,0,'excess_only',:key,'hash','agreement',:user)",
                "INSERT INTO fp_supplier_bonus_statements(id,venue_id,agreement_id,sequence,delta_cents,snapshot,request_key,request_hash,reason,actor_id) VALUES (:statement,:venue,:agreement,1,10,'{}'::jsonb,:key,'hash','statement',:user)",
                "INSERT INTO fp_supplier_bonus_documents(id,venue_id,supplier_id,reference,issued_on,net_cents,tax_cents,currency,request_key,request_hash,reason,actor_id) VALUES (:document,:venue,:supplier,'CREDIT-TEST',CURRENT_DATE,10,1,'EUR',:key,'hash','document',:user)",
                "INSERT INTO fp_supplier_bonus_allocations(id,venue_id,document_id,agreement_id,amount_cents,request_key,request_hash,reason,actor_id) VALUES (:allocation,:venue,:document,:agreement,10,:key,'hash','allocation',:user)",
            ):
                sync.execute(text(statement), ids)
            for table in (
                "fp_supplier_order_terms",
                "fp_supplier_bonus_agreements",
                "fp_supplier_bonus_statements",
                "fp_supplier_bonus_documents",
                "fp_supplier_bonus_allocations",
            ):
                for statement in (
                    f"UPDATE {table} SET reason='changed'",
                    f"DELETE FROM {table}",
                    f"TRUNCATE {table} CASCADE",
                ):
                    with pytest.raises(DBAPIError, match="append-only"), sync.begin_nested():
                        sync.execute(text(statement))
            with (
                pytest.raises(DBAPIError, match="would erase"),
                sync.begin_nested(),
                Operations.context(MigrationContext.configure(sync)),
            ):
                migrations[2].downgrade()
            assert (
                sync.execute(text("SELECT count(*) FROM fp_supplier_order_terms")).scalar_one() == 1
            )
        finally:
            sync.execute(text("SELECT set_config('search_path', :path, true)"), {"path": old_path})
            sync.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            sync.execution_options(schema_translate_map=old_map)

    await connection.run_sync(install)
