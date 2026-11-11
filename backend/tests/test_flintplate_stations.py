"""Station routing, old bill snapshots, authorization and actual concurrent commits."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.gastro import router as core
from app.gastro import stations, tips
from app.gastro.models import Membership, MenuItem, Order, Shift, Venue
from app.gastro.schemas import MenuPayload, VersionInput
from app.gastro.station_models import OperatingStation, StationCommand
from app.gastro.station_schemas import StationCreate, StationUpdate
from app.gastro.station_service import ensure_defaults, menu_payload, work_kinds
from app.users.models import User
from tests.conftest import TestSessionLocal, test_engine
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order, serve
from tests.test_flintplate_replacements import setup_request
from tests.test_flintplate_tip_safety import PERIOD, link, shift_for, time_for

pytest_plugins = ["tests.test_flintplate"]


async def station(
    client: AsyncClient, site: Site, name: str = "Grill", kind: str = "kitchen"
) -> dict:
    return body(
        await client.post(
            site.path("/stations"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "name": name,
                "kind": kind,
            },
        ),
        201,
    )


async def route_item(client: AsyncClient, site: Site, code: str, *, publish: bool = True) -> dict:
    rows = body(await client.get(site.path("/menu"), headers=site.headers))
    current = next(row for row in rows if row["id"] == site.item_id)
    updated = body(
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={
                "version": current["version"],
                "data": {**current["draft"], "station": code},
            },
        )
    )
    if publish:
        return body(
            await client.post(
                site.path(f"/menu/{site.item_id}/publish"),
                headers=site.headers,
                json={"version": updated["version"]},
            )
        )
    return updated


async def change_station(client: AsyncClient, site: Site, row: dict, **changes: object):
    return await client.put(
        site.path(f"/stations/{row['id']}"),
        headers=site.headers,
        json={
            "request_key": str(uuid.uuid4()),
            "version": row["version"],
            "name": row["name"],
            "active": row["active"],
            "sort_order": row["sort_order"],
            **changes,
        },
    )


async def test_defaults_manager_boundaries_and_replayed_station_command(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    rows = body(await client.get(site.path("/stations"), headers=hr_workspace.headers("worker")))
    assert {row["code"] for row in rows} == {"kitchen", "bar", "service", "activities"}
    assert {
        row["code"]
        for row in body(
            await client.get(site.path("/stations?preparation_only=true"), headers=site.headers)
        )
    } == {"kitchen", "bar"}
    data = {"request_key": str(uuid.uuid4()), "name": "Grill", "kind": "kitchen"}
    assert (
        await client.post(site.path("/stations"), headers=hr_workspace.headers("worker"), json=data)
    ).status_code == 403
    assert (
        await client.get(site.path("/stations"), headers=hr_workspace.headers("other_hr"))
    ).status_code == 404
    first = body(await client.post(site.path("/stations"), headers=site.headers, json=data), 201)
    assert first == body(
        await client.post(site.path("/stations"), headers=site.headers, json=data), 201
    )
    assert (
        await client.post(
            site.path("/stations"), headers=site.headers, json={**data, "name": "Kaltküche"}
        )
    ).status_code == 409
    assert (
        await client.post(
            site.path("/stations"),
            headers=site.headers,
            json={**data, "request_key": str(uuid.uuid4()), "name": " grill "},
        )
    ).status_code == 409
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(StationCommand)
            .where(StationCommand.venue_id == uuid.UUID(site.venue_id))
        )
        == 1
    )
    assert (await change_station(client, site, first, kind="bar")).status_code == 422
    assert (await change_station(client, site, first, version=99)).status_code == 409
    update = {
        "request_key": str(uuid.uuid4()),
        "version": 1,
        "name": "Grill Ost",
        "active": True,
        "sort_order": 50,
    }
    path = site.path(f"/stations/{first['id']}")
    confirmed = body(await client.put(path, headers=site.headers, json=update))
    body(await change_station(client, site, confirmed, name="Grill West"))
    assert body(await client.put(path, headers=site.headers, json=update)) == confirmed


async def test_menu_requires_a_real_active_station_in_this_venue_and_derives_snapshot(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    own = await station(client, site)
    rows = body(await client.get(site.path("/menu"), headers=site.headers))
    item = next(row for row in rows if row["id"] == site.item_id)
    for code in ("invented", "service", "activities"):
        response = await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={
                "version": item["version"],
                "data": {**item["draft"], "station": code},
            },
        )
        assert response.status_code == 422
    other_venue = body(
        await client.post(
            "/gastro/venues",
            headers=hr_workspace.headers("other_hr"),
            json={"name": "Other kitchen"},
        ),
        201,
    )
    foreign = body(
        await client.post(
            f"/gastro/venues/{other_venue['id']}/stations",
            headers=hr_workspace.headers("other_hr"),
            json={
                "request_key": str(uuid.uuid4()),
                "name": "Other grill",
                "kind": "kitchen",
            },
        ),
        201,
    )
    assert (
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={
                "version": item["version"],
                "data": {**item["draft"], "station": foreign["code"]},
            },
        )
    ).status_code == 422
    forged = {"id": foreign["id"], "code": foreign["code"], "name": "Fake bar", "kind": "bar"}
    updated = body(
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={
                "version": item["version"],
                "data": {**item["draft"], "station": own["code"], "station_snapshot": forged},
            },
        )
    )
    assert updated["draft"]["station_snapshot"] == {
        key: own[key] for key in ("id", "code", "name", "kind")
    }
    inactive = body(await change_station(client, site, own, active=False))
    assert inactive["active"] is False
    assert (
        await client.post(
            site.path(f"/menu/{site.item_id}/publish"),
            headers=site.headers,
            json={"version": updated["version"]},
        )
    ).status_code == 409


async def test_renaming_and_menu_rerouting_never_rewrite_existing_order_snapshots(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    grill = await station(client, site)
    first_menu = await route_item(client, site, grill["code"])
    request = site.order(
        lines=[
            {
                "item_id": site.item_id,
                "menu_version": first_menu["published_version"],
                "quantity": 2,
            }
        ]
    )
    original = body(
        await client.post(site.path("/orders"), headers=site.headers, json=request), 201
    )
    saved = original["lines"][0]["station_snapshot"]
    renamed = body(await change_station(client, site, grill, name="Heißer Grill"))
    again = body(await client.post(site.path("/orders"), headers=site.headers, json=request), 201)
    assert again["lines"] == original["lines"]
    assert saved["name"] == "Grill" and renamed["name"] != saved["name"]
    after_rename = await sent_order(client, site, lines=request["lines"])
    assert after_rename["lines"][0]["station_snapshot"] == saved
    cold = await station(client, site, "Kaltküche")
    next_menu = await route_item(client, site, cold["code"])
    newer = await sent_order(
        client,
        site,
        lines=[
            {"item_id": site.item_id, "menu_version": next_menu["published_version"], "quantity": 1}
        ],
    )
    assert newer["lines"][0]["station_snapshot"]["id"] == cold["id"]
    persisted = await db_session.get(Order, uuid.UUID(original["id"]))
    assert persisted is not None and persisted.lines[0]["station_snapshot"] == saved
    assert original["total_cents"] == 2000 and newer["total_cents"] == 1000


async def test_takeaway_extras_do_not_inherit_a_mismatching_kitchen_snapshot(
    client: AsyncClient, site: Site
) -> None:
    grill = await station(client, site)
    item = await route_item(client, site, grill["code"], publish=False)
    changed = body(
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={
                "version": item["version"],
                "data": {
                    **item["draft"],
                    "takeaway_packaging": {
                        "name": "Testbox",
                        "price_cents": 50,
                        "deposit_cents": 200,
                        "tax_rate_bps": 1900,
                        "deposit_tax_rate_bps": 1900,
                        "reusable": True,
                    },
                },
            },
        )
    )
    body(
        await client.post(
            site.path(f"/menu/{site.item_id}/publish"),
            headers=site.headers,
            json={"version": changed["version"]},
        )
    )
    order = await sent_order(
        client,
        site,
        table_id=None,
        fulfillment="takeaway",
        lines=[
            {
                "item_id": site.item_id,
                "menu_version": changed["version"],
                "quantity": 2,
            }
        ],
    )
    product, packaging, deposit = order["lines"]
    assert product["station_snapshot"]["id"] == grill["id"]
    assert [packaging["kind"], deposit["kind"]] == ["packaging", "deposit"]
    assert all(
        line["station"] == "service" and line["station_snapshot"] is None
        for line in (packaging, deposit)
    )
    assert order["total_cents"] == 2500


async def test_published_articles_and_old_open_lines_prevent_deactivation(
    client: AsyncClient, site: Site
) -> None:
    grill = await station(client, site)
    published = await route_item(client, site, grill["code"])
    original = await sent_order(
        client,
        site,
        lines=[
            {"item_id": site.item_id, "menu_version": published["published_version"], "quantity": 1}
        ],
    )
    assert (await change_station(client, site, grill, active=False)).status_code == 409
    await route_item(client, site, "kitchen")
    assert (await change_station(client, site, grill, active=False)).status_code == 409
    await serve(client, site, original)
    inactive = body(await change_station(client, site, grill, active=False))
    assert inactive["active"] is False
    assert grill["code"] not in {
        row["code"] for row in body(await client.get(site.path("/stations"), headers=site.headers))
    }
    assert grill["code"] in {
        row["code"]
        for row in body(
            await client.get(site.path("/stations?include_inactive=true"), headers=site.headers)
        )
    }


async def test_kitchen_progresses_only_requested_line_and_cannot_serve_or_configure(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    grill = await station(client, site)
    main = await route_item(client, site, grill["code"])
    drink = body(
        await client.post(
            site.path("/menu"),
            headers=site.headers,
            json={
                "sku": "BAR078",
                "data": MenuPayload(
                    name="Testgetränk", price_cents=250, tax_rate_bps=1900, station="bar"
                ).model_dump(mode="json"),
            },
        ),
        201,
    )
    body(
        await client.post(
            site.path(f"/menu/{drink['id']}/publish"), headers=site.headers, json={"version": 1}
        )
    )
    order = await sent_order(
        client,
        site,
        lines=[
            {"item_id": site.item_id, "menu_version": main["published_version"], "quantity": 1},
            {"item_id": drink["id"], "menu_version": 1, "quantity": 1},
        ],
    )
    body(
        await client.put(
            site.path("/members"),
            headers=site.headers,
            json={"user_id": str(hr_workspace.worker.id), "role": "kitchen"},
        )
    )
    path = site.path(f"/orders/{order['id']}/lines/{order['lines'][0]['line_id']}/status")
    for state in ("preparing", "ready"):
        data = {"version": order["version"], "request_key": str(uuid.uuid4()), "status": state}
        order = body(await client.post(path, headers=hr_workspace.headers("worker"), json=data))
        assert order["lines"][1]["preparation_status"] == "sent"
        assert order["lines"][0]["station_snapshot"]["id"] == grill["id"]
        assert (
            body(await client.post(path, headers=hr_workspace.headers("worker"), json=data))[
                "version"
            ]
            == order["version"]
        )
    assert (
        await client.post(
            path,
            headers=hr_workspace.headers("worker"),
            json={
                "version": order["version"],
                "request_key": str(uuid.uuid4()),
                "status": "served",
            },
        )
    ).status_code == 403
    assert (
        await client.put(
            site.path(f"/stations/{grill['id']}"),
            headers=hr_workspace.headers("worker"),
            json={
                "version": grill["version"],
                "request_key": str(uuid.uuid4()),
                "name": "Changed",
                "active": True,
            },
        )
    ).status_code == 403


async def test_inactive_or_renamed_grill_keeps_kitchen_competence_and_tip_pool(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    grill = await station(client, site)
    venue = await db_session.get(Venue, uuid.UUID(site.venue_id))
    assert venue is not None
    shift = await shift_for(db_session, venue, hr_workspace.worker, station=grill["code"])
    entry = await time_for(db_session, venue, hr_workspace.worker, pause=30)
    attribution = await link(client, site, entry, shift)
    assert attribution["station"] == "Grill"
    work = await tips.worked_minutes(db_session, venue, tips.Period.model_validate(PERIOD))
    assert work.groups == {"service": {}, "kitchen": {hr_workspace.worker.id: 210}}
    before = await work_kinds(
        db_session, uuid.UUID(site.venue_id), [grill["code"], "Küche", "Service"]
    )
    assert before == {grill["code"]: "kitchen", "Küche": "kitchen", "Service": "service"}
    body(await change_station(client, site, grill, name="Neue Grillstation", active=False))
    assert await work_kinds(db_session, uuid.UUID(site.venue_id), before) == before
    unchanged = await tips.worked_minutes(db_session, venue, tips.Period.model_validate(PERIOD))
    assert unchanged == work


async def test_new_shifts_resolve_registry_and_cannot_publish_after_deactivation(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    grill = await station(client, site)
    start = (datetime.now(UTC) + timedelta(days=14)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    data = {
        "worker_id": str(hr_workspace.worker.id),
        "station": grill["code"],
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=4)).isoformat(),
        "break_minutes": 30,
    }
    assert (
        await client.post(
            site.path("/shifts"),
            headers=site.headers,
            json={**data, "station": "unconfigured kitchen"},
        )
    ).status_code == 422
    shift = body(await client.post(site.path("/shifts"), headers=site.headers, json=data), 201)
    assert shift["station"] == grill["code"] and shift["station_label"] == "Grill"
    body(await change_station(client, site, grill, active=False))
    assert (
        await client.post(
            site.path(f"/shifts/{shift['id']}/status"),
            headers=site.headers,
            json={"version": 1, "status": "published"},
        )
    ).status_code == 409


async def test_missing_custom_station_cannot_silently_move_approved_time_to_service(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    venue = await db_session.get(Venue, uuid.UUID(site.venue_id))
    assert venue is not None
    shift = await shift_for(db_session, venue, hr_workspace.worker, station="s_missing")
    entry = await time_for(db_session, venue, hr_workspace.worker, pause=30)
    await link(client, site, entry, shift)
    with pytest.raises(HTTPException) as caught:
        await tips.worked_minutes(db_session, venue, tips.Period.model_validate(PERIOD))
    assert caught.value.status_code == 409


async def test_custom_station_replacements_keep_kitchen_qualification_and_human_label(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    grill = await station(client, site)
    request, headers, ids = await setup_request(
        client, site, db_session, hr_workspace, "sequential"
    )
    original = await db_session.get(Shift, uuid.UUID(request["shift_id"]))
    assert original is not None
    original.station = grill["code"]
    await db_session.flush()
    ranked = body(
        await client.post(site.path("/emergency-preview"), headers=site.headers, json=request)
    )
    assert [row["worker_id"] for row in ranked if row["eligible"]] == ids
    body(await client.post(site.path("/emergencies"), headers=site.headers, json=request), 201)
    offer = body(await client.get(site.path("/my-replacement-offers"), headers=headers[0]))[0]
    assert offer["station"] == "Grill"
    body(
        await client.post(
            site.path(f"/my-replacement-offers/{offer['id']}"),
            headers=headers[0],
            json={"accept": True},
        )
    )
    search = body(await client.get(site.path("/emergencies"), headers=site.headers))[0]
    replacement = await db_session.get(Shift, uuid.UUID(search["replacement_shift_id"]))
    assert replacement is not None and replacement.station == grill["code"]


async def test_legacy_free_text_shift_can_be_replaced_without_rewriting_its_evidence(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    request, headers, _ = await setup_request(client, site, db_session, hr_workspace, "sequential")
    original = await db_session.get(Shift, uuid.UUID(request["shift_id"]))
    assert original is not None
    original.station = "Küche · warme Speisen"
    await db_session.flush()
    body(await client.post(site.path("/emergencies"), headers=site.headers, json=request), 201)
    offer = body(await client.get(site.path("/my-replacement-offers"), headers=headers[0]))[0]
    assert offer["station"] == "Küche · warme Speisen"
    body(
        await client.post(
            site.path(f"/my-replacement-offers/{offer['id']}"),
            headers=headers[0],
            json={"accept": True},
        )
    )
    search = body(await client.get(site.path("/emergencies"), headers=site.headers))[0]
    replacement = await db_session.get(Shift, uuid.UUID(search["replacement_shift_id"]))
    assert replacement is not None and replacement.station == "kitchen"
    await db_session.refresh(original)
    assert original.station == "Küche · warme Speisen"


def migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/078_flintplate_operating_stations.py"
    )
    spec = importlib.util.spec_from_file_location("stations078", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_database_prevents_reclassifying_stations_and_rewriting_command_receipts(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    row = await station(client, site)
    connection = await db_session.connection()
    await connection.run_sync(migration().install_guards)
    statements = [
        (
            "UPDATE fp_operating_stations SET kind='service' WHERE id=:id",
            {"id": uuid.UUID(row["id"])},
        ),
        (
            "UPDATE fp_operating_stations SET code='other' WHERE id=:id",
            {"id": uuid.UUID(row["id"])},
        ),
        ("DELETE FROM fp_operating_stations WHERE id=:id", {"id": uuid.UUID(row["id"])}),
        ("TRUNCATE fp_operating_stations", {}),
        (
            "UPDATE fp_station_commands SET result='{}'::jsonb WHERE venue_id=:id",
            {"id": uuid.UUID(site.venue_id)},
        ),
        ("DELETE FROM fp_station_commands WHERE venue_id=:id", {"id": uuid.UUID(site.venue_id)}),
        ("TRUNCATE fp_station_commands", {}),
    ]
    for sql, params in statements:
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(sql), params)


async def test_migration_seeds_existing_venues_without_touching_paid_line_json() -> None:
    schema = "station_upgrade_" + uuid.uuid4().hex
    module = migration()
    async with test_engine.begin() as connection:
        await connection.execution_options(schema_translate_map={None: schema})
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}",public'))
        for statement in (
            "CREATE TABLE fp_venues(id uuid PRIMARY KEY)",
            "CREATE TABLE users(id uuid PRIMARY KEY)",
            "CREATE TABLE fp_menu_items(draft jsonb,published jsonb)",
            "CREATE TABLE fp_orders(lines jsonb,paid_at timestamptz,pos_requested boolean)",
            "CREATE TABLE fp_shifts(venue_id uuid,station text)",
            "INSERT INTO fp_venues VALUES(gen_random_uuid()),(gen_random_uuid())",
        ):
            await connection.execute(text(statement))
        await connection.execute(
            text("INSERT INTO fp_orders VALUES(CAST(:lines AS jsonb),now(),false)"),
            {
                "lines": json.dumps(
                    [{"station": "kitchen", "name": "Old paid item", "total_cents": 1234}]
                )
            },
        )
        before = await connection.scalar(text("SELECT lines::text FROM fp_orders"))

        def upgrade(sync):
            module.op = Operations(MigrationContext.configure(sync))
            module.upgrade()

        await connection.run_sync(upgrade)

        # Compare actual migration DDL against all inherited ORM columns, not
        # metadata.create_all(): that path hid missing updated_at before 076a.
        def columns_match(sync):
            inspector = inspect(sync)
            for model in (OperatingStation, StationCommand):
                actual = {
                    row["name"]: row["nullable"]
                    for row in inspector.get_columns(model.__tablename__, schema=schema)
                }
                expected = {column.name: column.nullable for column in model.__table__.columns}
                assert actual == expected

        await connection.run_sync(columns_match)
        assert await connection.scalar(text("SELECT count(*) FROM fp_operating_stations")) == 8
        assert await connection.scalar(text("SELECT lines::text FROM fp_orders")) == before
        with pytest.raises(DBAPIError):
            async with connection.begin_nested():
                await connection.execute(
                    text('INSERT INTO fp_menu_items VALUES(\'{"station":"s_custom"}\',null)')
                )
                await connection.run_sync(lambda sync: module.downgrade())
        await connection.run_sync(lambda sync: module.downgrade())
        assert await connection.scalar(text("SELECT lines::text FROM fp_orders")) == before
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def test_publish_and_deactivate_serialize_without_a_dangling_station() -> None:
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Station concurrency fixture", slug="station-" + uuid.uuid4().hex, status="active"
        )
        db.add(tenant)
        await db.flush()
        actor = User(
            email=f"station-{uuid.uuid4().hex}@example.invalid",
            hashed_password="synthetic",
            full_name="Station fixture",
            role="recruiter",
            tenant_id=tenant.id,
            is_active=True,
        )
        db.add(actor)
        await db.flush()
        venue = Venue(name="Concurrent station venue", tenant_id=tenant.id)
        db.add(venue)
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=actor.id, role="manager"))
        await ensure_defaults(db, venue.id)
        custom = OperatingStation(
            venue_id=venue.id, code="s_concurrency", name="Grill", kind="kitchen"
        )
        db.add(custom)
        await db.flush()
        original = MenuPayload(name="Concurrent item", price_cents=100, tax_rate_bps=1900)
        draft = await menu_payload(
            db, venue.id, original.model_copy(update={"station": custom.code})
        )
        item = MenuItem(
            venue_id=venue.id,
            sku="C078",
            draft=draft.model_dump(mode="json"),
            published=original.model_dump(mode="json"),
            version=2,
            published_version=1,
        )
        db.add(item)
        await db.flush()
        venue_id, actor_id, station_id, item_id = venue.id, actor.id, custom.id, item.id
        await db.commit()

    async def deactivate() -> int:
        async with TestSessionLocal() as db:
            user = await db.get(User, actor_id)
            assert user is not None
            try:
                await stations.update_station(
                    venue_id,
                    station_id,
                    StationUpdate(request_key=uuid.uuid4(), version=1, name="Grill", active=False),
                    user,
                    db,
                )
                await db.commit()
                return 200
            except HTTPException as error:
                await db.rollback()
                return error.status_code

    async def publish() -> int:
        async with TestSessionLocal() as db:
            user = await db.get(User, actor_id)
            assert user is not None
            try:
                await core.publish_item(venue_id, item_id, VersionInput(version=2), user, db)
                await db.commit()
                return 200
            except HTTPException as error:
                await db.rollback()
                return error.status_code

    assert sorted(await asyncio.wait_for(asyncio.gather(deactivate(), publish()), 15)) == [200, 409]
    async with TestSessionLocal() as db:
        current = await db.get(OperatingStation, station_id)
        published = await db.get(MenuItem, item_id)
        assert current is not None and published is not None and published.published is not None
        assert current.active == (published.published["station"] == current.code)


async def test_concurrent_create_retry_returns_one_station_and_one_receipt() -> None:
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Station replay fixture",
            slug="station-replay-" + uuid.uuid4().hex,
            status="active",
        )
        db.add(tenant)
        await db.flush()
        actor = User(
            email=f"station-replay-{uuid.uuid4().hex}@example.invalid",
            hashed_password="synthetic",
            full_name="Replay fixture",
            role="recruiter",
            tenant_id=tenant.id,
            is_active=True,
        )
        db.add(actor)
        await db.flush()
        venue = Venue(name="Replay venue", tenant_id=tenant.id)
        db.add(venue)
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=actor.id, role="manager"))
        await ensure_defaults(db, venue.id)
        venue_id, actor_id = venue.id, actor.id
        await db.commit()
    request = StationCreate(request_key=uuid.uuid4(), name="Kaltküche", kind="kitchen")

    async def create():
        async with TestSessionLocal() as db:
            user = await db.get(User, actor_id)
            assert user is not None
            result = await stations.create_station(venue_id, request, user, db)
            await db.commit()
            return result

    one, two = await asyncio.wait_for(asyncio.gather(create(), create()), 15)
    assert one == two
    async with TestSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(OperatingStation)
                .where(OperatingStation.venue_id == venue_id)
            )
            == 5
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(StationCommand)
                .where(StationCommand.venue_id == venue_id)
            )
            == 1
        )
