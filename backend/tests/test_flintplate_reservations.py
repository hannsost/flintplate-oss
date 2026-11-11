"""Real counted shortages coexist with holds; exact-once consumption never bypasses quarantine."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
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
from app.gastro import stock_availability as availability
from app.gastro.models import Membership, Venue
from app.main import app
from app.security import create_access_token
from app.users.models import User
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.test_flintplate_inventory import balances, prepare, received
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]


def path(site: Site, suffix: str = "") -> str:
    return site.path("/inventory/reservations" + suffix)


async def setup_stock(client: AsyncClient, site: Site) -> dict:
    stock = await prepare(client, site)
    incoming = await received(client, site, stock, quantity="10")
    return {**stock, "lot_id": incoming["movements"][0]["lot_id"]}


def hold_input(stock: dict, **changes: object) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "reason": "Vorbereitung für das Abendbuffet",
        "lot_id": stock["lot_id"],
        "location_id": stock["location_id"],
        "quantity": "6",
        "duration_minutes": 120,
        **changes,
    }


async def hold(client: AsyncClient, site: Site, stock: dict, **changes: object) -> dict:
    return body(
        await client.post(path(site), headers=site.headers, json=hold_input(stock, **changes)), 201
    )


def close_input(kind: str, **changes: object) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "reason": "Vorbereitung geprüft",
        "kind": kind,
        "usage_reference": "PREP-ABEND-001" if kind == "consume" else "",
        **changes,
    }


async def count(client: AsyncClient, site: Site, stock: dict, expected: str, actual: str) -> dict:
    return body(
        await client.post(
            site.path("/inventory/counts"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Tatsächliche gezählte Menge",
                "lot_id": stock["lot_id"],
                "location_id": stock["location_id"],
                "expected_quantity": expected,
                "counted_quantity": actual,
            },
        ),
        201,
    )


@pytest.mark.asyncio
async def test_hold_reduces_availability_without_moving_goods_and_release_is_idempotent(
    client: AsyncClient, site: Site
) -> None:
    stock = await setup_stock(client, site)
    payload = hold_input(stock)
    reserved = body(await client.post(path(site), headers=site.headers, json=payload), 201)
    assert (
        body(await client.post(path(site), headers=site.headers, json=payload), 201)["id"]
        == reserved["id"]
    )
    snapshot = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    balance = next(row for row in snapshot["balances"] if row["lot_id"] == stock["lot_id"])
    assert (
        Decimal(balance["quantity"]) == 10
        and Decimal(balance["reserved_quantity"]) == 6
        and Decimal(balance["available_quantity"]) == 4
    )
    assert (
        await client.post(path(site), headers=site.headers, json=hold_input(stock, quantity="5"))
    ).status_code == 409
    release = close_input("release")
    result = body(
        await client.post(
            path(site, f"/{reserved['id']}/close"), headers=site.headers, json=release
        ),
        201,
    )
    assert result["status"] == "released" and result["stock_operation_id"] is None
    assert (
        body(
            await client.post(
                path(site, f"/{reserved['id']}/close"), headers=site.headers, json=release
            ),
            201,
        )["closure_id"]
        == result["closure_id"]
    )
    assert (await balances(client, site))[(stock["lot_id"], stock["location_id"])] == 10


@pytest.mark.asyncio
async def test_normal_withdrawals_respect_hold_but_count_records_true_shortage(
    client: AsyncClient, site: Site
) -> None:
    stock = await setup_stock(client, site)
    reserved = await hold(client, site, stock)
    for route, extra in (
        ("waste", {}),
        (
            "transfers",
            {
                "source_location_id": stock["location_id"],
                "destination_location_id": stock["destination"],
            },
        ),
    ):
        payload = {
            "request_key": str(uuid.uuid4()),
            "reason": "Darf reservierte Menge nicht verbrauchen",
            "lot_id": stock["lot_id"],
            "quantity": "5",
            **extra,
        }
        if route == "waste":
            payload["location_id"] = stock["location_id"]
        assert (
            await client.post(site.path("/inventory/" + route), headers=site.headers, json=payload)
        ).status_code == 409
    await count(client, site, stock, "10", "4")
    states = body(await client.get(path(site), headers=site.headers))
    assert states[0]["status"] == "undercovered"
    assert (
        Decimal(states[0]["covered_quantity"]) == 4
        and Decimal(states[0]["shortfall_quantity"]) == 2
    )
    assert (
        await client.post(
            path(site, f"/{reserved['id']}/close"),
            headers=site.headers,
            json=close_input("consume"),
        )
    ).status_code == 409
    assert (await balances(client, site))[(stock["lot_id"], stock["location_id"])] == 4


@pytest.mark.asyncio
async def test_stable_hold_priority_keeps_shortfall_visible_when_covered_hold_is_consumed(
    client: AsyncClient, site: Site
) -> None:
    stock = await setup_stock(client, site)
    first = await hold(client, site, stock, quantity="4")
    second = await hold(client, site, stock, quantity="4")
    await count(client, site, stock, "10", "6")
    states = {row["id"]: row for row in body(await client.get(path(site), headers=site.headers))}
    assert (
        states[first["id"]]["status"] == "active"
        and Decimal(states[first["id"]]["covered_quantity"]) == 4
    )
    assert (
        states[second["id"]]["status"] == "undercovered"
        and Decimal(states[second["id"]]["shortfall_quantity"]) == 2
    )
    payload = close_input("consume")
    consumed = body(
        await client.post(path(site, f"/{first['id']}/close"), headers=site.headers, json=payload),
        201,
    )
    assert consumed["status"] == "consumed" and consumed["stock_operation_id"]
    assert (
        body(
            await client.post(
                path(site, f"/{first['id']}/close"), headers=site.headers, json=payload
            ),
            201,
        )["stock_operation_id"]
        == consumed["stock_operation_id"]
    )
    assert (await balances(client, site))[(stock["lot_id"], stock["location_id"])] == 2
    remaining = next(
        row
        for row in body(await client.get(path(site), headers=site.headers))
        if row["id"] == second["id"]
    )
    assert (
        Decimal(remaining["covered_quantity"]) == 2
        and Decimal(remaining["shortfall_quantity"]) == 2
    )


@pytest.mark.asyncio
async def test_expiry_frees_stock_without_cron_and_same_request_does_not_reacquire(
    client: AsyncClient, site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    stock = await setup_stock(client, site)
    start = availability.utc_now()
    payload = hold_input(stock, duration_minutes=1)
    reserved = body(await client.post(path(site), headers=site.headers, json=payload), 201)
    monkeypatch.setattr(availability, "utc_now", lambda: start + timedelta(minutes=2))
    replay = body(await client.post(path(site), headers=site.headers, json=payload), 201)
    assert replay["id"] == reserved["id"] and replay["status"] == "expired"
    snapshot = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert Decimal(snapshot["balances"][0]["available_quantity"]) == 10
    assert (
        await client.post(
            path(site, f"/{reserved['id']}/close"),
            headers=site.headers,
            json=close_input("consume"),
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_quarantine_and_expiry_never_yield_to_an_existing_hold(
    client: AsyncClient, site: Site
) -> None:
    stock = await setup_stock(client, site)
    reserved = await hold(client, site, stock)
    body(
        await client.post(
            site.path(f"/inventory/lots/{stock['lot_id']}/quarantine"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Sicherheitsrückruf des Lieferanten",
                "blocked": True,
                "version": 1,
            },
        ),
        201,
    )
    assert (
        await client.post(path(site), headers=site.headers, json=hold_input(stock, quantity="1"))
    ).status_code == 409
    assert (
        await client.post(
            path(site, f"/{reserved['id']}/close"),
            headers=site.headers,
            json=close_input("consume"),
        )
    ).status_code == 409
    state = body(await client.get(path(site), headers=site.headers))[0]
    assert state["blocked"] and not state["consumable"]
    assert (await balances(client, site))[(stock["lot_id"], stock["location_id"])] == 10


@pytest.mark.asyncio
async def test_hold_contract_requires_valid_duration_scope_and_consumption_reference(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    stock = await setup_stock(client, site)
    assert (
        await client.post(
            path(site), headers=site.headers, json=hold_input(stock, duration_minutes=0)
        )
    ).status_code == 422
    assert (
        await client.post(
            path(site), headers=site.headers, json=hold_input(stock, duration_minutes=525600)
        )
    ).status_code == 422
    assert (
        await client.post(
            path(site), headers=hr_workspace.headers("other_hr"), json=hold_input(stock)
        )
    ).status_code == 404
    reserved = await hold(client, site, stock)
    assert (
        await client.post(
            path(site, f"/{reserved['id']}/close"),
            headers=site.headers,
            json=close_input("consume", usage_reference=""),
        )
    ).status_code == 422
    foreign = body(
        await client.post("/gastro/venues", headers=site.headers, json={"name": "Andere Reserve"}),
        201,
    )
    assert (
        await client.post(
            f"/gastro/venues/{foreign['id']}/inventory/reservations/{reserved['id']}/close",
            headers=site.headers,
            json=close_input("release"),
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_actual_concurrent_reservations_cannot_claim_same_remaining_stock(
    client: AsyncClient,
) -> None:
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Reservation concurrency", slug=f"hold-{uuid.uuid4().hex}", status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email=f"hold-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name="Stock keeper",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Concurrent stock", tenant_id=tenant.id)
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
        stock = await setup_stock(client, site)
        results = await asyncio.gather(
            *[
                client.post(path(site), headers=site.headers, json=hold_input(stock))
                for _ in range(2)
            ]
        )
        assert sorted(result.status_code for result in results) == [201, 409]
        winner = next(result.json() for result in results if result.status_code == 201)
        payload = close_input("consume")
        closes = await asyncio.gather(
            *[
                client.post(
                    path(site, f"/{winner['id']}/close"), headers=site.headers, json=payload
                )
                for _ in range(2)
            ]
        )
        assert [result.status_code for result in closes] == [201, 201]
        assert closes[0].json()["stock_operation_id"] == closes[1].json()["stock_operation_id"]
        assert (await balances(client, site))[(stock["lot_id"], stock["location_id"])] == 4
    finally:
        app.dependency_overrides[get_db] = original


@pytest.mark.asyncio
async def test_reservation_migration_roundtrip_and_immutable_history(
    db_session: AsyncSession,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "reservation_migration", Path("alembic/versions/076_flintplate_stock_reservations.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = await db_session.connection()

    def install(sync: Connection) -> None:
        schema = f"reservation_migration_{uuid.uuid4().hex}"
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
            for table in ("fp_stock_lots", "fp_stock_locations", "fp_stock_operations"):
                sync.execute(
                    text(
                        f"CREATE TABLE {table} (id uuid PRIMARY KEY,venue_id uuid NOT NULL,UNIQUE(venue_id,id))"
                    )
                )
            with Operations.context(MigrationContext.configure(sync)):
                migration.upgrade()
                migration.downgrade()
                migration.upgrade()
            ids = {
                key: uuid.uuid4()
                for key in ("venue", "user", "lot", "location", "hold", "close", "key")
            }
            for statement in (
                "INSERT INTO fp_venues VALUES (:venue)",
                "INSERT INTO users VALUES (:user)",
                "INSERT INTO fp_stock_lots VALUES (:lot,:venue)",
                "INSERT INTO fp_stock_locations VALUES (:location,:venue)",
                "INSERT INTO fp_stock_reservations(id,venue_id,lot_id,location_id,quantity,expires_at,request_key,request_hash,reason,actor_id) VALUES (:hold,:venue,:lot,:location,1,now()+interval '2 hours',:key,'hash','purpose',:user)",
                "INSERT INTO fp_stock_reservation_closures(id,venue_id,reservation_id,kind,request_key,request_hash,reason,actor_id) VALUES (:close,:venue,:hold,'release',:key,'hash','release',:user)",
            ):
                sync.execute(text(statement), ids)
            for table in ("fp_stock_reservations", "fp_stock_reservation_closures"):
                for statement in (
                    f"UPDATE {table} SET reason='changed'",
                    f"DELETE FROM {table}",
                    f"TRUNCATE {table} CASCADE",
                ):
                    with pytest.raises(DBAPIError, match="append-only"), sync.begin_nested():
                        sync.execute(text(statement))
        finally:
            sync.execute(
                text("SELECT set_config('search_path', :path, true)"), {"path": previous_path}
            )
            sync.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            sync.execution_options(schema_translate_map=previous_map)

    await connection.run_sync(install)
