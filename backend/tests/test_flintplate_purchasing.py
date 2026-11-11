"""Purchasing reconciles pack terms, actual stock and approved invoice quantities."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.database import get_db
from app.gastro.models import Membership, Venue
from app.main import app
from app.security import create_access_token
from app.users.models import User
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.test_flintplate_inventory import prepare
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]


def path(site: Site, suffix: str) -> str:
    return site.path("/purchasing" + suffix)


async def catalog(client: AsyncClient, site: Site, **changes: object) -> dict:
    stock = await prepare(client, site)
    supplier = body(
        await client.post(
            path(site, "/suppliers"),
            headers=site.headers,
            json={"name": "Gemüsehandel", "reference": "SUP-001"},
        ),
        201,
    )
    product = body(
        await client.post(
            path(site, "/catalog"),
            headers=site.headers,
            json={
                "supplier_id": supplier["id"],
                "item_id": stock["item_id"],
                "supplier_sku": "TOM-BOX",
                "pack_name": "Kiste",
                "pack_quantity": "2.5",
                "pack_price_cents": 1000,
                "tax_rate_bps": 700,
                "effective_on": date.today().isoformat(),
                **changes,
            },
        ),
        201,
    )
    return {**stock, "supplier_id": supplier["id"], "product": product}


def order_input(setup: dict, **changes: object) -> dict:
    product = setup["product"]
    return {
        "request_key": str(uuid.uuid4()),
        "reason": "Wochenbedarf Küche",
        "supplier_id": setup["supplier_id"],
        "owner_id": setup["owner_id"],
        "location_id": setup["location_id"],
        "lines": [
            {"product_id": product["id"], "price_id": product["current_price"]["id"], "packs": 2}
        ],
        **changes,
    }


async def ordered(client: AsyncClient, site: Site, setup: dict, **changes: object) -> dict:
    order = body(
        await client.post(
            path(site, "/orders"), headers=site.headers, json=order_input(setup, **changes)
        ),
        201,
    )
    return body(
        await client.post(
            path(site, f"/orders/{order['id']}/state"),
            headers=site.headers,
            json={"version": order["version"], "status": "ordered", "reason": "Bestellung geprüft"},
        )
    )


def delivery_input(setup: dict, order: dict, **changes: object) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "line_id": order["lines"][0]["id"],
        "location_id": setup["location_id"],
        "lot_code": "LOT-A",
        "expires_on": (date.today() + timedelta(days=14)).isoformat(),
        "accepted_quantity": "5",
        "rejected_quantity": "0",
        "reference": "LS-101",
        "reason": "Lieferung geprüft",
        **changes,
    }


async def delivered(
    client: AsyncClient, site: Site, setup: dict, order: dict, **changes: object
) -> dict:
    return body(
        await client.post(
            path(site, f"/orders/{order['id']}/receipts"),
            headers=site.headers,
            json=delivery_input(setup, order, **changes),
        ),
        201,
    )


def invoice_input(setup: dict, order: dict, **changes: object) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "reason": "Lieferantenrechnung erfasst",
        "supplier_id": setup["supplier_id"],
        "number": f"INV-{uuid.uuid4().hex[:12]}",
        "issued_on": date.today().isoformat(),
        "lines": [
            {
                "purchase_line_id": order["lines"][0]["id"],
                "quantity": "5",
                "net_cents": 2000,
                "tax_rate_bps": 700,
            }
        ],
        **changes,
    }


async def invoice(
    client: AsyncClient, site: Site, setup: dict, order: dict, **changes: object
) -> dict:
    return body(
        await client.post(
            path(site, "/invoices"),
            headers=site.headers,
            json=invoice_input(setup, order, **changes),
        ),
        201,
    )


async def approve(client: AsyncClient, site: Site, entry: dict, status: int = 200) -> dict:
    return body(
        await client.post(
            path(site, f"/invoices/{entry['id']}/decision"),
            headers=site.headers,
            json={"version": entry["version"], "status": "approved", "reason": "Rechnung geprüft"},
        ),
        status,
    )


@pytest.mark.asyncio
async def test_packs_partial_receiving_and_rejections_reconcile_to_exact_stock(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    assert Decimal(order["lines"][0]["ordered_quantity"]) == Decimal(5)
    assert order["net_cents"] == 2000 and order["total_cents"] == 2140
    first = await delivered(
        client,
        site,
        setup,
        order,
        accepted_quantity="2.125",
        rejected_quantity="0.375",
        rejection_reason="Druckstellen",
    )
    assert first["status"] == "partial"
    assert Decimal(first["lines"][0]["remaining_quantity"]) == Decimal("2.875")
    second = await delivered(
        client, site, setup, first, lot_code="LOT-B", accepted_quantity="2.875"
    )
    assert second["status"] == "received"
    snapshot = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert sum(Decimal(row["quantity"]) for row in snapshot["balances"]) == Decimal(5)
    assert len(second["receipts"]) == 2


@pytest.mark.asyncio
async def test_receipt_replay_does_not_book_stock_twice(client: AsyncClient, site: Site) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    data = delivery_input(setup, order)
    endpoint = path(site, f"/orders/{order['id']}/receipts")
    one = body(await client.post(endpoint, headers=site.headers, json=data), 201)
    two = body(await client.post(endpoint, headers=site.headers, json=data), 201)
    assert one == two
    assert (
        await client.post(endpoint, headers=site.headers, json={**data, "reference": "DIFFERENT"})
    ).status_code == 409
    assert (
        len((await client.get(site.path("/inventory/operations"), headers=site.headers)).json())
        == 1
    )


@pytest.mark.asyncio
async def test_rejected_only_delivery_records_evidence_without_stock(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    result = await delivered(
        client,
        site,
        setup,
        order,
        accepted_quantity="0",
        rejected_quantity="5",
        rejection_reason="Kühlkette unterbrochen",
    )
    assert result["status"] == "ordered" and result["receipts"][0]["stock_operation_id"] is None
    assert result["receipts"][0]["details"]["lot_code"] == "LOT-A"
    assert (
        body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))["balances"]
        == []
    )
    bill = await invoice(client, site, setup, order)
    assert bill["check"]["matched"] is False
    await approve(client, site, bill, 409)


@pytest.mark.asyncio
async def test_overdelivery_and_closed_order_cannot_increase_stock(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    endpoint = path(site, f"/orders/{order['id']}/receipts")
    assert (
        await client.post(
            endpoint,
            headers=site.headers,
            json=delivery_input(setup, order, accepted_quantity="5.000001"),
        )
    ).status_code == 409
    partial = await delivered(client, site, setup, order, accepted_quantity="2")
    assert (
        await client.post(
            path(site, f"/orders/{order['id']}/state"),
            headers=site.headers,
            json={
                "version": partial["version"],
                "status": "cancelled",
                "reason": "Unzulässiges Storno",
            },
        )
    ).status_code == 409
    closed = body(
        await client.post(
            path(site, f"/orders/{order['id']}/state"),
            headers=site.headers,
            json={
                "version": partial["version"],
                "status": "closed",
                "reason": "Restlieferung entfällt",
            },
        )
    )
    assert closed["status"] == "closed" and Decimal(closed["lines"][0]["remaining_quantity"]) == 3
    assert (
        await client.post(
            endpoint, headers=site.headers, json=delivery_input(setup, order, accepted_quantity="3")
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_order_terms_survive_later_supplier_price_changes(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    changed = body(
        await client.post(
            path(site, "/prices"),
            headers=site.headers,
            json={
                "product_id": setup["product"]["id"],
                "expected_version": 1,
                "effective_on": date.today().isoformat(),
                "pack_price_cents": 1800,
                "tax_rate_bps": 1900,
            },
        ),
        201,
    )
    assert len(changed["prices"]) == 2 and changed["current_price"]["pack_price_cents"] == 1800
    await delivered(client, site, setup, order)
    bill = await invoice(client, site, setup, order)
    assert bill["check"]["matched"] is True
    approved = await approve(client, site, bill)
    assert approved["status"] == "approved" and approved["check"]["net_cents"] == 2000


@pytest.mark.asyncio
async def test_future_prices_do_not_replace_current_terms_and_stale_price_is_rejected(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    current = setup["product"]["current_price"]["id"]
    changed = body(
        await client.post(
            path(site, "/prices"),
            headers=site.headers,
            json={
                "product_id": setup["product"]["id"],
                "expected_version": 1,
                "effective_on": (date.today() + timedelta(days=30)).isoformat(),
                "pack_price_cents": 5000,
                "tax_rate_bps": 700,
            },
        ),
        201,
    )
    assert changed["current_price"]["id"] == current
    body(
        await client.post(
            path(site, "/prices"),
            headers=site.headers,
            json={
                "product_id": setup["product"]["id"],
                "expected_version": 2,
                "effective_on": date.today().isoformat(),
                "pack_price_cents": 1100,
                "tax_rate_bps": 700,
            },
        ),
        201,
    )
    assert (
        await client.post(path(site, "/orders"), headers=site.headers, json=order_input(setup))
    ).status_code == 409


@pytest.mark.asyncio
async def test_draft_must_be_rechecked_before_release(client: AsyncClient, site: Site) -> None:
    setup = await catalog(client, site)
    draft = body(
        await client.post(path(site, "/orders"), headers=site.headers, json=order_input(setup)), 201
    )
    assert (
        await client.post(
            path(site, f"/orders/{draft['id']}/receipts"),
            headers=site.headers,
            json=delivery_input(setup, draft),
        )
    ).status_code == 409
    body(
        await client.post(
            path(site, "/prices"),
            headers=site.headers,
            json={
                "product_id": setup["product"]["id"],
                "expected_version": 1,
                "effective_on": date.today().isoformat(),
                "pack_price_cents": 1500,
                "tax_rate_bps": 700,
            },
        ),
        201,
    )
    assert (
        await client.post(
            path(site, f"/orders/{draft['id']}/state"),
            headers=site.headers,
            json={"version": 1, "status": "ordered", "reason": "Veraltete Freigabe"},
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_three_way_check_names_price_tax_and_quantity_differences(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    await delivered(client, site, setup, order, accepted_quantity="2")
    bill = await invoice(
        client,
        site,
        setup,
        order,
        lines=[
            {
                "purchase_line_id": order["lines"][0]["id"],
                "quantity": "5",
                "net_cents": 2500,
                "tax_rate_bps": 1900,
            }
        ],
    )
    assert len(bill["check"]["lines"][0]["differences"]) == 3
    await approve(client, site, bill, 409)


@pytest.mark.asyncio
async def test_invoice_checks_update_after_receiving_but_approval_snapshot_stays_fixed(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    bill = await invoice(client, site, setup, order)
    assert bill["check"]["matched"] is False
    await delivered(client, site, setup, order)
    approved = await approve(client, site, bill)
    snapshot = body(await client.get(path(site, "/snapshot"), headers=site.headers))
    assert snapshot["invoices"][0]["check"] == approved["check"]
    assert (
        await client.post(
            path(site, f"/invoices/{bill['id']}/decision"),
            headers=site.headers,
            json={
                "version": approved["version"],
                "status": "rejected",
                "reason": "Nachträgliche Änderung",
            },
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_two_invoices_cannot_bill_the_same_received_quantity(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    await delivered(client, site, setup, order)
    one = await invoice(client, site, setup, order)
    two = await invoice(client, site, setup, order)
    assert one["check"]["matched"] and two["check"]["matched"]
    await approve(client, site, one)
    await approve(client, site, two, 409)


@pytest.mark.asyncio
async def test_partial_invoice_rounding_never_creates_extra_cents(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site, pack_quantity="3", pack_price_cents=2, tax_rate_bps=0)
    order = await ordered(
        client,
        site,
        setup,
        lines=[
            {
                "product_id": setup["product"]["id"],
                "price_id": setup["product"]["current_price"]["id"],
                "packs": 1,
            }
        ],
    )
    await delivered(client, site, setup, order, accepted_quantity="3")
    for expected in (1, 0, 1):
        bill = await invoice(
            client,
            site,
            setup,
            order,
            lines=[
                {
                    "purchase_line_id": order["lines"][0]["id"],
                    "quantity": "1",
                    "net_cents": expected,
                    "tax_rate_bps": 0,
                }
            ],
        )
        assert bill["check"]["lines"][0]["expected_net_cents"] == expected
        await approve(client, site, bill)
    snapshot = body(await client.get(path(site, "/snapshot"), headers=site.headers))
    assert (
        sum(
            row["check"]["net_cents"] for row in snapshot["invoices"] if row["status"] == "approved"
        )
        == 2
    )


@pytest.mark.asyncio
async def test_rejected_invoice_can_be_replaced_with_same_supplier_number(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    data = invoice_input(setup, order, number="RE-001")
    bill = body(await client.post(path(site, "/invoices"), headers=site.headers, json=data), 201)
    assert (
        await client.post(
            path(site, "/invoices"),
            headers=site.headers,
            json={**data, "request_key": str(uuid.uuid4())},
        )
    ).status_code == 409
    body(
        await client.post(
            path(site, f"/invoices/{bill['id']}/decision"),
            headers=site.headers,
            json={"version": 1, "status": "rejected", "reason": "Rechnung korrigieren"},
        )
    )
    corrected = body(
        await client.post(
            path(site, "/invoices"),
            headers=site.headers,
            json={**data, "request_key": str(uuid.uuid4())},
        ),
        201,
    )
    assert corrected["id"] != bill["id"]


@pytest.mark.asyncio
async def test_order_and_invoice_request_replay(client: AsyncClient, site: Site) -> None:
    setup = await catalog(client, site)
    data = order_input(setup)
    one = body(await client.post(path(site, "/orders"), headers=site.headers, json=data), 201)
    two = body(await client.post(path(site, "/orders"), headers=site.headers, json=data), 201)
    assert one == two
    assert (
        await client.post(
            path(site, "/orders"),
            headers=site.headers,
            json={**data, "reason": "Andere Bestellung"},
        )
    ).status_code == 409
    order = await ordered(client, site, setup)
    bill_data = invoice_input(setup, order)
    first = body(
        await client.post(path(site, "/invoices"), headers=site.headers, json=bill_data), 201
    )
    second = body(
        await client.post(path(site, "/invoices"), headers=site.headers, json=bill_data), 201
    )
    assert first == second


@pytest.mark.asyncio
async def test_purchase_permissions_and_supplier_boundaries(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await catalog(client, site)
    assert (
        await client.get(path(site, "/snapshot"), headers=hr_workspace.headers("other_hr"))
    ).status_code == 404
    assert (
        await client.post(
            path(site, "/orders"), headers=hr_workspace.headers("worker"), json=order_input(setup)
        )
    ).status_code == 403
    other_supplier = body(
        await client.post(
            path(site, "/suppliers"), headers=site.headers, json={"name": "Anderer Lieferant"}
        ),
        201,
    )
    assert (
        await client.post(
            path(site, "/orders"),
            headers=site.headers,
            json=order_input(setup, supplier_id=other_supplier["id"]),
        )
    ).status_code == 422
    order = await ordered(client, site, setup)
    assert (
        await client.post(
            path(site, "/invoices"),
            headers=site.headers,
            json=invoice_input(setup, order, supplier_id=other_supplier["id"]),
        )
    ).status_code == 422
    result = await client.post(
        path(site, f"/orders/{order['id']}/receipts"),
        headers=hr_workspace.headers("worker"),
        json=delivery_input(setup, order),
    )
    assert result.status_code == 201


@pytest.mark.asyncio
async def test_foreign_venue_catalog_and_order_positions_are_rejected(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    other_venue = body(
        await client.post("/gastro/venues", headers=site.headers, json={"name": "Zweiter Einkauf"}),
        201,
    )
    other = Site(other_venue["id"], "", "", site.headers)
    foreign = await catalog(client, other)
    for field in ("supplier_id", "owner_id", "location_id"):
        assert (
            await client.post(
                path(site, "/orders"),
                headers=site.headers,
                json=order_input(setup, **{field: foreign[field]}),
            )
        ).status_code == 404
    foreign_order = await ordered(client, other, foreign)
    order = await ordered(client, site, setup)
    assert (
        await client.post(
            path(site, f"/orders/{order['id']}/receipts"),
            headers=site.headers,
            json=delivery_input(setup, order, line_id=foreign_order["lines"][0]["id"]),
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_concurrent_invoice_approvals_reserve_received_quantity_once(
    client: AsyncClient,
) -> None:
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Purchase concurrency", slug=f"purchase-{uuid.uuid4().hex}", status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email=f"purchase-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name="Purchasing",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Concurrent purchasing", tenant_id=tenant.id)
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
        bills = [
            await invoice(client, site, setup, order),
            await invoice(client, site, setup, order),
        ]
        results = await asyncio.gather(
            *[
                client.post(
                    path(site, f"/invoices/{bill['id']}/decision"),
                    headers=site.headers,
                    json={"version": 1, "status": "approved", "reason": "Parallele Prüfung"},
                )
                for bill in bills
            ]
        )
        assert sorted(result.status_code for result in results) == [200, 409]
    finally:
        app.dependency_overrides[get_db] = original


@pytest.mark.asyncio
async def test_purchasing_migration_round_trip_and_frozen_evidence(
    db_session: AsyncSession,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "purchasing_migration", Path("alembic/versions/071_flintplate_purchasing.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = await db_session.connection()

    def install(sync: Connection) -> None:
        schema = f"purchasing_migration_{uuid.uuid4().hex}"
        previous_path = sync.execute(text("SHOW search_path")).scalar_one()
        previous_map = sync.get_execution_options().get("schema_translate_map")
        sync.execution_options(schema_translate_map=None)
        sync.execute(text(f'CREATE SCHEMA "{schema}"'))
        sync.execute(
            text("SELECT set_config('search_path', :path, true)"), {"path": f"{schema},public"}
        )
        try:
            sync.execute(text("CREATE TABLE fp_venues (id uuid PRIMARY KEY)"))
            sync.execute(text("CREATE TABLE users (id uuid PRIMARY KEY)"))
            for name in (
                "fp_stock_items",
                "fp_stock_owners",
                "fp_stock_locations",
                "fp_stock_operations",
            ):
                sync.execute(
                    text(
                        f"CREATE TABLE {name} (id uuid PRIMARY KEY, venue_id uuid NOT NULL, UNIQUE(venue_id,id))"
                    )
                )
            with Operations.context(MigrationContext.configure(sync)):
                migration.upgrade()
                migration.downgrade()
                migration.upgrade()
            ids = {
                name: uuid.uuid4()
                for name in (
                    "venue",
                    "user",
                    "item",
                    "owner",
                    "location",
                    "supplier",
                    "product",
                    "price",
                    "order",
                    "line",
                    "invoice",
                    "invoice_line",
                    "key",
                    "invoice_key",
                )
            }
            for statement in (
                "INSERT INTO fp_venues VALUES (:venue)",
                "INSERT INTO users VALUES (:user)",
                "INSERT INTO fp_stock_items VALUES (:item,:venue)",
                "INSERT INTO fp_stock_owners VALUES (:owner,:venue)",
                "INSERT INTO fp_stock_locations VALUES (:location,:venue)",
                "INSERT INTO fp_suppliers(id,venue_id,name) VALUES (:supplier,:venue,'Supplier')",
                "INSERT INTO fp_supplier_products(id,venue_id,supplier_id,item_id,supplier_sku,pack_name,pack_quantity) VALUES (:product,:venue,:supplier,:item,'SKU','Pack',2.5)",
                "INSERT INTO fp_supplier_prices(id,venue_id,product_id,version,effective_on,pack_price_cents,tax_rate_bps,actor_id) VALUES (:price,:venue,:product,1,CURRENT_DATE,1000,700,:user)",
                "INSERT INTO fp_purchase_orders(id,venue_id,supplier_id,owner_id,location_id,number,request_key,request_hash,currency,note,actor_id) VALUES (:order,:venue,:supplier,:owner,:location,'EK-1',:key,'hash','EUR','note',:user)",
                "INSERT INTO fp_purchase_order_lines(id,venue_id,order_id,product_id,item_id,price_id,item_name,unit,supplier_sku,pack_name,pack_quantity,packs,ordered_quantity,pack_price_cents,tax_rate_bps) VALUES (:line,:venue,:order,:product,:item,:price,'Tomatoes','kg','SKU','Pack',2.5,2,5,1000,700)",
                "INSERT INTO fp_purchase_invoices(id,venue_id,supplier_id,number,issued_on,currency,request_key,request_hash,actor_id) VALUES (:invoice,:venue,:supplier,'INV-1',CURRENT_DATE,'EUR',:invoice_key,'hash',:user)",
                "INSERT INTO fp_purchase_invoice_lines(id,venue_id,invoice_id,purchase_line_id,quantity,net_cents,tax_rate_bps) VALUES (:invoice_line,:venue,:invoice,:line,5,2000,700)",
                "UPDATE fp_purchase_orders SET status='ordered',version=2",
                "UPDATE fp_purchase_invoices SET status='approved',version=2,approval_snapshot='{}'::jsonb",
            ):
                sync.execute(text(statement), ids)
            for statement in (
                "UPDATE fp_supplier_prices SET pack_price_cents=1",
                "DELETE FROM fp_supplier_prices",
                "UPDATE fp_purchase_order_lines SET packs=99",
                "TRUNCATE fp_purchase_order_lines CASCADE",
                "UPDATE fp_purchase_orders SET currency='USD'",
                "DELETE FROM fp_purchase_orders",
                "UPDATE fp_purchase_invoices SET status='draft',version=3",
                "DELETE FROM fp_purchase_invoice_lines",
            ):
                with pytest.raises(DBAPIError, match="append-only|immutable"), sync.begin_nested():
                    sync.execute(text(statement))
            with pytest.raises(DBAPIError, match="draft"), sync.begin_nested():
                sync.execute(
                    text(
                        "INSERT INTO fp_purchase_invoice_lines(id,venue_id,invoice_id,purchase_line_id,quantity,net_cents,tax_rate_bps) VALUES (gen_random_uuid(),:venue,:invoice,:line,5,2000,700)"
                    ),
                    ids,
                )
        finally:
            sync.execute(
                text("SELECT set_config('search_path', :path, true)"), {"path": previous_path}
            )
            sync.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            sync.execution_options(schema_translate_map=previous_map)

    await connection.run_sync(install)
