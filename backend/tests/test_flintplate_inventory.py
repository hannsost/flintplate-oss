"""The stock lifecycle, ownership boundaries and concurrent posting guarantees."""

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
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.database import get_db
from app.gastro.inventory_models import StockMovement
from app.gastro.models import Membership, Venue
from app.main import app
from app.security import create_access_token
from app.users.models import User
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]


def path(site: Site, suffix: str) -> str:
    return site.path("/inventory" + suffix)


async def prepare(client: AsyncClient, site: Site) -> dict[str, str]:
    item = body(
        await client.post(
            path(site, "/items"),
            headers=site.headers,
            json={"sku": "TOMATO", "name": "Tomaten", "unit": "kg", "requires_expiry": True},
        ),
        201,
    )
    owner = body(
        await client.post(
            path(site, "/owners"),
            headers=site.headers,
            json={"name": "Unser Betrieb", "kind": "own"},
        ),
        201,
    )
    locations = []
    for name in ("Kühlhaus", "Küche"):
        locations.append(
            body(
                await client.post(
                    path(site, "/locations"), headers=site.headers, json={"name": name}
                ),
                201,
            )["id"]
        )
    return {
        "item_id": item["id"],
        "owner_id": owner["id"],
        "location_id": locations[0],
        "destination": locations[1],
    }


def receipt(stock: dict[str, str], **changes: object) -> dict[str, object]:
    return {
        "request_key": str(uuid.uuid4()),
        "item_id": stock["item_id"],
        "owner_id": stock["owner_id"],
        "location_id": stock["location_id"],
        "lot_code": "SUPPLIER-1",
        "expires_on": (date.today() + timedelta(days=14)).isoformat(),
        "quantity": "2.125",
        "reason": "Wareneingang geprüft",
        "reference": "LS-001",
        **changes,
    }


async def received(
    client: AsyncClient, site: Site, stock: dict[str, str], **changes: object
) -> dict:
    return body(
        await client.post(
            path(site, "/receipts"), headers=site.headers, json=receipt(stock, **changes)
        ),
        201,
    )


async def balances(client: AsyncClient, site: Site) -> dict[tuple[str, str], Decimal]:
    snapshot = body(await client.get(path(site, "/snapshot"), headers=site.headers))
    return {
        (row["lot_id"], row["location_id"]): Decimal(row["quantity"])
        for row in snapshot["balances"]
    }


@pytest.mark.asyncio
async def test_decimal_receipt_transfer_waste_and_count_reconcile(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    incoming = await received(client, site, stock)
    lot_id = incoming["movements"][0]["lot_id"]
    moved = body(
        await client.post(
            path(site, "/transfers"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "lot_id": lot_id,
                "source_location_id": stock["location_id"],
                "destination_location_id": stock["destination"],
                "quantity": "0.625",
                "reason": "Vorbereitung Küche",
            },
        ),
        201,
    )
    assert sum(Decimal(row["quantity"]) for row in moved["movements"]) == 0
    body(
        await client.post(
            path(site, "/waste"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "lot_id": lot_id,
                "location_id": stock["destination"],
                "quantity": "0.125",
                "reason": "Beim Sortieren verdorben",
            },
        ),
        201,
    )
    counted = body(
        await client.post(
            path(site, "/counts"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "lot_id": lot_id,
                "location_id": stock["location_id"],
                "expected_quantity": "1.5",
                "counted_quantity": "1.375",
                "reason": "Abendinventur nachgezählt",
            },
        ),
        201,
    )
    assert Decimal(counted["movements"][0]["quantity"]) == Decimal("-0.125")
    assert await balances(client, site) == {
        (lot_id, stock["location_id"]): Decimal("1.375"),
        (lot_id, stock["destination"]): Decimal("0.5"),
    }
    journal = (await client.get(path(site, "/operations"), headers=site.headers)).json()
    assert [entry["kind"] for entry in journal] == ["receipt", "transfer", "waste", "count"]
    next_page = (
        await client.get(
            path(site, f"/operations?after={journal[1]['sequence']}&limit=1"), headers=site.headers
        )
    ).json()
    assert [row["id"] for row in next_page] == [journal[2]["id"]]


@pytest.mark.asyncio
async def test_receipt_replay_is_exact_and_decimal_scale_is_irrelevant(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    data = receipt(stock, quantity="1.100000")
    first = body(await client.post(path(site, "/receipts"), headers=site.headers, json=data), 201)
    again = body(
        await client.post(
            path(site, "/receipts"), headers=site.headers, json={**data, "quantity": "1.1"}
        ),
        201,
    )
    assert first == again
    assert (
        await client.post(
            path(site, "/receipts"), headers=site.headers, json={**data, "quantity": "2"}
        )
    ).status_code == 409
    assert list((await balances(client, site)).values()) == [Decimal("1.1")]


@pytest.mark.asyncio
async def test_owners_do_not_merge_even_for_the_same_supplier_lot(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    partner = body(
        await client.post(
            path(site, "/owners"),
            headers=site.headers,
            json={"name": "Partner-Bäckerei", "kind": "partner"},
        ),
        201,
    )
    first = await received(client, site, stock, quantity="1")
    second = await received(client, site, stock, owner_id=partner["id"], quantity="3")
    assert first["movements"][0]["lot_id"] != second["movements"][0]["lot_id"]
    snapshot = body(await client.get(path(site, "/snapshot"), headers=site.headers))
    assert {row["owner_id"]: Decimal(row["quantity"]) for row in snapshot["balances"]} == {
        stock["owner_id"]: Decimal(1),
        partner["id"]: Decimal(3),
    }


@pytest.mark.asyncio
async def test_expiry_is_required_and_cannot_be_rewritten_on_an_existing_lot(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    assert (
        await client.post(
            path(site, "/receipts"), headers=site.headers, json=receipt(stock, expires_on=None)
        )
    ).status_code == 422
    await received(client, site, stock)
    assert (
        await client.post(
            path(site, "/receipts"),
            headers=site.headers,
            json=receipt(stock, expires_on=(date.today() + timedelta(days=20)).isoformat()),
        )
    ).status_code == 409
    assert len(await balances(client, site)) == 1


@pytest.mark.asyncio
async def test_expired_and_quarantined_stock_remains_visible_with_zero_available(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    await received(client, site, stock, expires_on=(date.today() - timedelta(days=2)).isoformat())
    await received(client, site, stock, lot_code="HOLD", blocked=True)
    snapshot = body(await client.get(path(site, "/snapshot"), headers=site.headers))
    assert all(
        Decimal(row["quantity"]) > 0 and Decimal(row["available_quantity"]) == 0
        for row in snapshot["balances"]
    )
    assert any(row["expired"] for row in snapshot["balances"])
    assert any(row["blocked"] for row in snapshot["balances"])


@pytest.mark.asyncio
async def test_quarantine_is_versioned_replayable_and_release_requires_management(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    stock = await prepare(client, site)
    first = await received(client, site, stock)
    lot_id = first["movements"][0]["lot_id"]
    data = {
        "request_key": str(uuid.uuid4()),
        "version": 1,
        "blocked": True,
        "reason": "Temperaturabweichung prüfen",
    }
    endpoint = path(site, f"/lots/{lot_id}/quarantine")
    one = body(await client.post(endpoint, headers=hr_workspace.headers("worker"), json=data), 201)
    assert one == body(
        await client.post(endpoint, headers=hr_workspace.headers("worker"), json=data), 201
    )
    release = {
        **data,
        "request_key": str(uuid.uuid4()),
        "version": 2,
        "blocked": False,
        "reason": "Prüfung abgeschlossen",
    }
    assert (
        await client.post(endpoint, headers=hr_workspace.headers("worker"), json=release)
    ).status_code == 403
    assert (
        await client.post(endpoint, headers=site.headers, json={**release, "version": 1})
    ).status_code == 409
    body(await client.post(endpoint, headers=site.headers, json=release), 201)
    snapshot = body(await client.get(path(site, "/snapshot"), headers=site.headers))
    assert snapshot["lots"][0]["version"] == 3 and snapshot["lots"][0]["blocked"] is False
    assert Decimal(snapshot["balances"][0]["available_quantity"]) == Decimal("2.125")


@pytest.mark.asyncio
async def test_quarantine_key_cannot_replay_against_a_different_lot(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    one = await received(client, site, stock)
    two = await received(client, site, stock, lot_code="OTHER")
    data = {
        "request_key": str(uuid.uuid4()),
        "version": 1,
        "blocked": True,
        "reason": "Eingangskontrolle",
    }
    for index, entry in enumerate((one, two)):
        response = await client.post(
            path(site, f"/lots/{entry['movements'][0]['lot_id']}/quarantine"),
            headers=site.headers,
            json=data,
        )
        assert response.status_code == (201 if index == 0 else 409)


@pytest.mark.asyncio
async def test_stock_cannot_be_overdrawn_and_failed_transfer_has_no_destination_entry(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    incoming = await received(client, site, stock, quantity="0.5")
    lot_id = incoming["movements"][0]["lot_id"]
    before = await balances(client, site)
    for endpoint, fields in (
        (
            "/transfers",
            {
                "source_location_id": stock["location_id"],
                "destination_location_id": stock["destination"],
            },
        ),
        ("/waste", {"location_id": stock["location_id"]}),
    ):
        response = await client.post(
            path(site, endpoint),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "lot_id": lot_id,
                "quantity": "0.500001",
                "reason": "Zu große Menge",
                **fields,
            },
        )
        assert response.status_code == 409
    assert await balances(client, site) == before


@pytest.mark.asyncio
async def test_count_rejects_stale_stock_and_records_zero_difference_without_fake_movement(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    incoming = await received(client, site, stock, quantity="1")
    lot_id = incoming["movements"][0]["lot_id"]
    data = {
        "request_key": str(uuid.uuid4()),
        "lot_id": lot_id,
        "location_id": stock["location_id"],
        "expected_quantity": "0",
        "counted_quantity": "1",
        "reason": "Inventur gezählt",
    }
    assert (
        await client.post(path(site, "/counts"), headers=site.headers, json=data)
    ).status_code == 409
    one = body(
        await client.post(
            path(site, "/counts"), headers=site.headers, json={**data, "expected_quantity": "1"}
        ),
        201,
    )
    assert one["movements"] == []
    again = body(
        await client.post(
            path(site, "/counts"), headers=site.headers, json={**data, "expected_quantity": "1"}
        ),
        201,
    )
    assert again == one
    assert list((await balances(client, site)).values()) == [Decimal(1)]


@pytest.mark.asyncio
async def test_piece_counts_and_decimal_precision_are_validated(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    item = body(
        await client.post(
            path(site, "/items"),
            headers=site.headers,
            json={"sku": "CUP", "name": "Mehrwegbecher", "unit": "piece"},
        ),
        201,
    )
    for changes in (
        {"quantity": "0.0000001"},
        {"quantity": "-1"},
        {"item_id": item["id"], "quantity": "0.5"},
        {"quantity": "NaN"},
    ):
        assert (
            await client.post(
                path(site, "/receipts"), headers=site.headers, json=receipt(stock, **changes)
            )
        ).status_code == 422
    accepted = await received(client, site, stock, quantity="0.000001")
    assert Decimal(accepted["movements"][0]["quantity"]) == Decimal("0.000001")


@pytest.mark.asyncio
async def test_read_write_and_foreign_reference_boundaries(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    stock = await prepare(client, site)
    assert (
        await client.get(path(site, "/snapshot"), headers=hr_workspace.headers("other_hr"))
    ).status_code == 404
    assert (
        await client.post(
            path(site, "/items"),
            headers=hr_workspace.headers("worker"),
            json={"sku": "NO", "name": "Kein Recht", "unit": "kg"},
        )
    ).status_code == 403
    first = await received(client, site, stock)
    assert (
        await client.post(
            path(site, "/counts"),
            headers=hr_workspace.headers("worker"),
            json={
                "request_key": str(uuid.uuid4()),
                "lot_id": first["movements"][0]["lot_id"],
                "location_id": stock["location_id"],
                "expected_quantity": "2.125",
                "counted_quantity": "2",
                "reason": "Nicht freigegeben",
            },
        )
    ).status_code == 403
    other_venue = body(
        await client.post(
            "/gastro/venues", headers=site.headers, json={"name": "Zweiter eigener Betrieb"}
        ),
        201,
    )
    other = Site(other_venue["id"], "", "", site.headers)
    foreign = await prepare(client, other)
    for field in ("item_id", "owner_id", "location_id"):
        assert (
            await client.post(
                path(site, "/receipts"),
                headers=site.headers,
                json=receipt(stock, **{field: foreign[field]}),
            )
        ).status_code == 404
    assert (await client.get(path(other, "/operations"), headers=site.headers)).json() == []


@pytest.mark.asyncio
async def test_request_keys_are_scoped_to_venue(client: AsyncClient, site: Site) -> None:
    stock = await prepare(client, site)
    other_venue = body(
        await client.post("/gastro/venues", headers=site.headers, json={"name": "Zweiter Betrieb"}),
        201,
    )
    other = Site(other_venue["id"], "", "", site.headers)
    other_stock = await prepare(client, other)
    key = str(uuid.uuid4())
    one = await received(client, site, stock, request_key=key)
    two = await received(client, other, other_stock, request_key=key)
    assert one["id"] != two["id"]


@pytest.mark.asyncio
async def test_duplicate_masters_return_conflict(client: AsyncClient, site: Site) -> None:
    await prepare(client, site)
    for suffix, data in (
        ("/items", {"sku": "TOMATO", "name": "Tomaten", "unit": "kg"}),
        ("/owners", {"name": "Unser Betrieb", "kind": "own"}),
        ("/locations", {"name": "Kühlhaus"}),
    ):
        assert (
            await client.post(path(site, suffix), headers=site.headers, json=data)
        ).status_code == 409


@pytest.mark.asyncio
async def test_migration_round_trip_and_ledger_mutation_rejection(db_session: AsyncSession) -> None:
    spec = importlib.util.spec_from_file_location(
        "inventory_migration", Path("alembic/versions/068_flintplate_inventory.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = await db_session.connection()

    def install(sync: Connection) -> None:
        # A separate schema keeps later modules' foreign keys completely untouched.
        schema = f"inventory_migration_{uuid.uuid4().hex}"
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
                    "lot",
                    "operation",
                    "movement",
                    "key",
                )
            }
            for statement in (
                "INSERT INTO fp_venues VALUES (:venue)",
                "INSERT INTO users VALUES (:user)",
                "INSERT INTO fp_stock_items(id,venue_id,sku,name,unit) VALUES (:item,:venue,'SKU','Stock','kg')",
                "INSERT INTO fp_stock_owners(id,venue_id,name,kind) VALUES (:owner,:venue,'Owner','own')",
                "INSERT INTO fp_stock_locations(id,venue_id,name) VALUES (:location,:venue,'Store')",
                "INSERT INTO fp_stock_lots(id,venue_id,item_id,owner_id,code) VALUES (:lot,:venue,:item,:owner,'LOT')",
                "INSERT INTO fp_stock_operations(id,venue_id,request_key,request_hash,kind,actor_id,reason,details) VALUES (:operation,:venue,:key,'hash','receipt',:user,'Receipt','{}'::jsonb)",
                "INSERT INTO fp_stock_movements(id,venue_id,operation_id,lot_id,location_id,quantity) VALUES (:movement,:venue,:operation,:lot,:location,2.125)",
            ):
                sync.execute(text(statement), ids)
            for statement in (
                "UPDATE fp_stock_movements SET quantity=99",
                "DELETE FROM fp_stock_movements",
                "TRUNCATE fp_stock_movements",
                "UPDATE fp_stock_operations SET reason='changed'",
                "DELETE FROM fp_stock_operations",
                "TRUNCATE fp_stock_operations CASCADE",
                "UPDATE fp_stock_lots SET code='other'",
                "DELETE FROM fp_stock_lots",
                "TRUNCATE fp_stock_lots CASCADE",
            ):
                with pytest.raises(DBAPIError, match="append-only|immutable"), sync.begin_nested():
                    sync.execute(text(statement))
            sync.execute(text("UPDATE fp_stock_lots SET blocked=true,version=version+1"))
            assert sync.execute(
                text("SELECT SUM(quantity) FROM fp_stock_movements")
            ).scalar_one() == Decimal("2.125")
        finally:
            sync.execute(
                text("SELECT set_config('search_path', :path, true)"), {"path": previous_path}
            )
            sync.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            sync.execution_options(schema_translate_map=previous_map)

    await connection.run_sync(install)


@pytest.mark.asyncio
async def test_database_rejects_a_foreign_location_even_without_the_router(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    stock = await prepare(client, site)
    incoming = await received(client, site, stock)
    other_venue = body(
        await client.post("/gastro/venues", headers=site.headers, json={"name": "Anderer Ort"}), 201
    )
    other = Site(other_venue["id"], "", "", site.headers)
    foreign = await prepare(client, other)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                StockMovement(
                    venue_id=uuid.UUID(site.venue_id),
                    operation_id=uuid.UUID(incoming["id"]),
                    lot_id=uuid.UUID(incoming["movements"][0]["lot_id"]),
                    location_id=uuid.UUID(foreign["location_id"]),
                    quantity=Decimal(1),
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_concurrent_retry_and_competing_withdrawals_use_separate_transactions(
    client: AsyncClient,
) -> None:
    # Independent committed fixtures remain confined to this run's disposable test schema.
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Stock concurrency", slug=f"stock-{uuid.uuid4().hex}", status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email=f"stock-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name="Stock operator",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Concurrent stock", tenant_id=tenant.id)
        db.add_all([user, venue])
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
        headers = auth_headers(create_access_token({"sub": user.email}))
        site = Site(str(venue.id), "", "", headers)
        await db.commit()

    async def isolated_db() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as db:
            yield db
            await db.commit()

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = isolated_db
    try:
        stock = await prepare(client, site)
        data = receipt(stock, quantity="1")
        replies = await asyncio.gather(
            *[client.post(path(site, "/receipts"), headers=headers, json=data) for _ in range(2)]
        )
        first, second = (body(response, 201) for response in replies)
        assert first["id"] == second["id"]
        lot_id = first["movements"][0]["lot_id"]
        competing = await asyncio.gather(
            *[
                client.post(
                    path(site, "/waste"),
                    headers=headers,
                    json={
                        "request_key": str(uuid.uuid4()),
                        "lot_id": lot_id,
                        "location_id": stock["location_id"],
                        "quantity": "0.75",
                        "reason": "Konkurrierende Schwundbuchung",
                    },
                )
                for _ in range(2)
            ]
        )
        assert sorted(response.status_code for response in competing) == [201, 409]
        assert list((await balances(client, site)).values()) == [Decimal("0.25")]
    finally:
        app.dependency_overrides[get_db] = original
