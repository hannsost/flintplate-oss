"""Saved arrangements never become resource recreation or commercial edits."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.database import get_db
from app.gastro.floor_layout_models import FloorLayoutCommand
from app.gastro.models import DiningTable, Membership, Venue
from app.main import app
from app.security import create_access_token
from app.users.models import User
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order
from tests.test_flintplate_purchase_conditions import assert_migrated_orm_columns
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]


def endpoint(site: Site, suffix: str = "") -> str:
    return site.path("/layout/profiles" + suffix)


async def tables(client: AsyncClient, site: Site) -> list[dict]:
    return body(await client.get(site.path("/tables"), headers=site.headers))


async def position(
    client: AsyncClient, site: Site, table: dict, x: int, y: int, *, key: str | None = None
) -> dict:
    return body(
        await client.post(
            site.path(f"/tables/{table['id']}/position"),
            headers=site.headers,
            json={
                "request_key": key or str(uuid.uuid4()),
                "version": table["version"],
                "x": x,
                "y": y,
            },
        ),
        201,
    )


async def table_update(client: AsyncClient, site: Site, row: dict, **fields: object) -> dict:
    return body(
        await client.put(
            site.path(f"/tables/{row['id']}"),
            headers=site.headers,
            json={**{key: value for key, value in row.items() if key != "id"}, **fields},
        )
    )


async def setup_room(client: AsyncClient, site: Site) -> dict:
    floor = body(
        await client.post(
            site.path("/floors"), headers=site.headers, json={"name": "Grundriss-Ebene", "level": 0}
        ),
        201,
    )
    room = body(
        await client.post(
            site.path("/rooms"),
            headers=site.headers,
            json={"floor_id": floor["id"], "name": "Veranstaltungsraum"},
        ),
        201,
    )
    other_room = body(
        await client.post(
            site.path("/rooms"),
            headers=site.headers,
            json={"floor_id": floor["id"], "name": "Nebenraum"},
        ),
        201,
    )
    first = next(row for row in await tables(client, site) if row["id"] == site.table_id)
    first = await table_update(
        client, site, first, room_id=room["id"], area=" Terrasse ", x=100, y=200
    )
    second = body(
        await client.post(
            site.path("/tables"),
            headers=site.headers,
            json={
                "name": "Zweiter Tisch",
                "room_id": room["id"],
                "area": first["area"],
                "x": 400,
                "y": 500,
                "seats": 4,
                "combinable_with": [first["id"]],
            },
        ),
        201,
    )
    return {"room": room, "other_room": other_room, "tables": [first, second]}


def save_input(
    setup: dict, *, profile: dict | None = None, name: str = "Abendveranstaltung"
) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "profile_id": profile["id"] if profile else None,
        "expected_version": profile["version"] if profile else 0,
        "name": name,
        "room_id": setup["room"]["id"],
        "tables": [{"table_id": row["id"], "version": row["version"]} for row in setup["tables"]],
    }


async def preview(
    client: AsyncClient, site: Site, profile: dict, revision_id: str | None = None
) -> dict:
    return body(
        await client.post(
            endpoint(site, f"/{profile['id']}/preview"),
            headers=site.headers,
            json={"version": profile["version"], "revision_id": revision_id},
        )
    )


def apply_input(review: dict) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "version": review["profile_version"],
        "revision_id": review["revision_id"],
        "fingerprint": review["fingerprint"],
    }


@pytest.mark.asyncio
async def test_position_command_preserves_resource_and_open_bill_and_replays_old_result(
    client: AsyncClient, site: Site
) -> None:
    row = next(row for row in await tables(client, site) if row["id"] == site.table_id)
    order = await sent_order(client, site)
    key = str(uuid.uuid4())
    first = await position(client, site, row, 780, 620, key=key)
    assert first == await position(client, site, row, 780, 620, key=key)
    fresh = next(t for t in await tables(client, site) if t["id"] == row["id"])
    assert first["version"] == row["version"] + 1
    assert {k: v for k, v in fresh.items() if k not in {"version", "x", "y"}} == {
        k: v for k, v in row.items() if k not in {"version", "x", "y"}
    }
    await position(client, site, fresh, 200, 100)
    assert await position(client, site, row, 780, 620, key=key) == first
    latest = next(t for t in await tables(client, site) if t["id"] == row["id"])
    assert (latest["x"], latest["y"]) == (200, 100)
    orders = body(await client.get(site.path("/orders"), headers=site.headers))
    assert next(entry for entry in orders if entry["id"] == order["id"]) == order


@pytest.mark.asyncio
async def test_save_preview_apply_and_retry_keep_exact_history_and_only_change_positions(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_room(client, site)
    outside = body(
        await client.post(
            site.path("/tables"),
            headers=site.headers,
            json={
                "name": "Bleibt im Nebenraum",
                "room_id": setup["other_room"]["id"],
                "x": 900,
                "y": 900,
            },
        ),
        201,
    )
    starts = datetime.now(UTC) + timedelta(hours=1)
    booking = body(
        await client.post(
            site.path("/reservation-groups"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "table_ids": [row["id"] for row in setup["tables"]],
                "guest_name": "Kombitisch bleibt belegt",
                "guests": 6,
                "starts_at": starts.isoformat(),
                "ends_at": (starts + timedelta(hours=1)).isoformat(),
            },
        ),
        201,
    )
    capture = save_input(setup)
    profile = body(await client.post(endpoint(site), headers=site.headers, json=capture), 201)
    assert (
        body(
            await client.post(
                endpoint(site),
                headers=site.headers,
                json={**capture, "tables": list(reversed(capture["tables"]))},
            ),
            201,
        )
        == profile
    )
    for table in setup["tables"]:
        await position(client, site, table, table["x"] + 100, table["y"] + 100)
    before = await tables(client, site)
    review = await preview(client, site, profile)
    assert not review["blocking_reasons"] and all(row["changed"] for row in review["rows"])
    assert await tables(client, site) == before
    payload = apply_input(review)
    url = endpoint(site, f"/{profile['id']}/apply")
    result = body(await client.post(url, headers=site.headers, json=payload), 201)
    assert body(await client.post(url, headers=site.headers, json=payload), 201) == result
    after = {row["id"]: row for row in await tables(client, site)}
    assert after[outside["id"]] == outside
    board = body(await client.get(site.path("/reservations/board"), headers=site.headers))
    preserved = next(row for row in board["reservations"] if row["id"] == booking["id"])
    assert preserved["table_ids"] == booking["table_ids"]
    assert (preserved["guests"], preserved["starts_at"], preserved["ends_at"]) == (
        booking["guests"],
        booking["starts_at"],
        booking["ends_at"],
    )
    assert set(result["changed_table_ids"]) == {row["id"] for row in setup["tables"]}
    for original in setup["tables"]:
        current = after[original["id"]]
        assert (current["x"], current["y"]) == (original["x"], original["y"])
        assert {k: v for k, v in current.items() if k not in {"version", "x", "y"}} == {
            k: v for k, v in original.items() if k not in {"version", "x", "y"}
        }
    moved = after[setup["tables"][0]["id"]]
    await position(client, site, moved, 850, 900)
    assert body(await client.post(url, headers=site.headers, json=payload), 201) == result
    final = {row["id"]: row for row in await tables(client, site)}
    assert (final[moved["id"]]["x"], final[moved["id"]]["y"]) == (850, 900)
    versions = body(
        await client.get(endpoint(site, f"/{profile['id']}/versions"), headers=site.headers)
    )
    assert len(versions) == 1 and versions[0]["id"] == profile["current_revision_id"]
    assert not any(
        "price" in key or "rate" in key for row in versions[0]["placements"] for key in row
    )


@pytest.mark.asyncio
async def test_stale_preview_blocks_every_move_after_full_table_update(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_room(client, site)
    profile = body(
        await client.post(endpoint(site), headers=site.headers, json=save_input(setup)), 201
    )
    for table in setup["tables"]:
        await position(client, site, table, 800, 800)
    review = await preview(client, site, profile)
    latest = next(
        row for row in await tables(client, site) if row["id"] == setup["tables"][0]["id"]
    )
    await table_update(client, site, latest, name="Zwischenzeitlich geändert")
    before = await tables(client, site)
    body(
        await client.post(
            endpoint(site, f"/{profile['id']}/apply"),
            headers=site.headers,
            json=apply_input(review),
        ),
        409,
    )
    assert await tables(client, site) == before
    body(
        await client.post(
            endpoint(site), headers=site.headers, json=save_input(setup, profile=profile)
        ),
        409,
    )


@pytest.mark.asyncio
async def test_added_deleted_or_relocated_tables_block_without_recreation(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    setup = await setup_room(client, site)
    profile = body(
        await client.post(endpoint(site), headers=site.headers, json=save_input(setup)), 201
    )
    extra = body(
        await client.post(
            site.path("/tables"),
            headers=site.headers,
            json={"name": "Späterer Tisch", "room_id": setup["room"]["id"]},
        ),
        201,
    )
    review = await preview(client, site, profile)
    assert review["added_table_ids"] == [extra["id"]]
    body(
        await client.post(
            endpoint(site, f"/{profile['id']}/apply"),
            headers=site.headers,
            json=apply_input(review),
        ),
        409,
    )
    await db_session.execute(delete(DiningTable).where(DiningTable.id == uuid.UUID(extra["id"])))
    first = next(row for row in await tables(client, site) if row["id"] == setup["tables"][0]["id"])
    await table_update(client, site, first, room_id=setup["other_room"]["id"])
    review = await preview(client, site, profile)
    assert any("Raum oder Bereich" in reason for reason in review["blocking_reasons"])
    body(
        await client.post(
            endpoint(site, f"/{profile['id']}/apply"),
            headers=site.headers,
            json=apply_input(review),
        ),
        409,
    )
    # There is no table-delete route; simulate later removal of an unused table
    # directly in this test transaction. Historical JSON must not recreate it.
    removed = setup["tables"][1]["id"]
    await db_session.execute(delete(DiningTable).where(DiningTable.id == uuid.UUID(removed)))
    review = await preview(client, site, profile)
    assert review["missing_table_ids"] == [removed]
    body(
        await client.post(
            endpoint(site, f"/{profile['id']}/apply"),
            headers=site.headers,
            json=apply_input(review),
        ),
        409,
    )
    assert removed not in {row["id"] for row in await tables(client, site)}
    history = body(
        await client.get(endpoint(site, f"/{profile['id']}/versions"), headers=site.headers)
    )
    assert removed in {row["table_id"] for row in history[0]["placements"]}


@pytest.mark.asyncio
async def test_historical_revision_can_be_applied_and_archive_is_versioned(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_room(client, site)
    initial_payload = save_input(setup)
    first = body(await client.post(endpoint(site), headers=site.headers, json=initial_payload), 201)
    await position(client, site, setup["tables"][0], 800, 900)
    setup["tables"] = [
        row for row in await tables(client, site) if row["room_id"] == setup["room"]["id"]
    ]
    second = body(
        await client.post(
            endpoint(site), headers=site.headers, json=save_input(setup, profile=first)
        ),
        201,
    )
    assert second["version"] == 2
    review = await preview(client, site, second, first["current_revision_id"])
    result = body(
        await client.post(
            endpoint(site, f"/{first['id']}/apply"), headers=site.headers, json=apply_input(review)
        ),
        201,
    )
    assert result["profile_version"] == 2 and result["revision_id"] == first["current_revision_id"]
    archive_data = {"request_key": str(uuid.uuid4()), "version": 2, "archived": True}
    archive_url = endpoint(site, f"/{first['id']}/archive")
    archived = body(await client.post(archive_url, headers=site.headers, json=archive_data), 201)
    assert archived["version"] == 3 and archived["archived"]
    assert not body(await client.get(endpoint(site), headers=site.headers))
    assert (
        len(body(await client.get(endpoint(site) + "?include_archived=true", headers=site.headers)))
        == 1
    )
    blocked = await preview(client, site, archived)
    body(
        await client.post(
            endpoint(site, f"/{first['id']}/apply"), headers=site.headers, json=apply_input(blocked)
        ),
        409,
    )
    revived = body(
        await client.post(
            archive_url,
            headers=site.headers,
            json={"request_key": str(uuid.uuid4()), "version": 3, "archived": False},
        ),
        201,
    )
    assert revived["version"] == 4 and not revived["archived"]
    assert (
        body(await client.post(archive_url, headers=site.headers, json=archive_data), 201)
        == archived
    )
    assert (
        body(await client.post(endpoint(site), headers=site.headers, json=initial_payload), 201)
        == first
    )
    history = body(
        await client.get(
            endpoint(site, f"/{first['id']}/versions?before_version=4&limit=2"),
            headers=site.headers,
        )
    )
    assert [row["version"] for row in history] == [3, 2]
    assert history[0]["previous_id"] == history[1]["id"]


@pytest.mark.asyncio
async def test_layout_roles_scope_input_bounds_and_casefolded_name_conflicts(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await setup_room(client, site)
    data = save_input(setup)
    body(await client.post(endpoint(site), headers=hr_workspace.headers("worker"), json=data), 403)
    body(
        await client.post(endpoint(site), headers=hr_workspace.headers("other_hr"), json=data), 404
    )
    profile = body(await client.post(endpoint(site), headers=site.headers, json=data), 201)
    body(
        await client.post(
            endpoint(site), headers=site.headers, json=save_input(setup, name=data["name"].upper())
        ),
        409,
    )
    body(
        await client.post(
            endpoint(site),
            headers=site.headers,
            json={**save_input(setup), "tables": data["tables"][:1]},
        ),
        409,
    )
    body(
        await client.post(
            endpoint(site),
            headers=site.headers,
            json={**save_input(setup), "tables": [data["tables"][0], data["tables"][0]]},
        ),
        422,
    )
    other = body(
        await client.post(
            "/gastro/venues", headers=site.headers, json={"name": "Fremder Grundriss"}
        ),
        201,
    )
    foreign = Site(other["id"], "", "", site.headers)
    body(await client.post(endpoint(foreign), headers=site.headers, json=data), 404)
    body(
        await client.get(endpoint(foreign, f"/{profile['id']}/versions"), headers=site.headers), 404
    )
    row = setup["tables"][0]
    for payload in (
        {"x": -1, "y": 0},
        {"x": 1001, "y": 0},
        {"x": 1.5, "y": 0},
        {"x": 1, "y": 2, "room_id": setup["other_room"]["id"]},
        {"x": 1, "y": 2, "hourly_rate_cents": 0},
    ):
        body(
            await client.post(
                site.path(f"/tables/{row['id']}/position"),
                headers=site.headers,
                json={"request_key": str(uuid.uuid4()), "version": row["version"], **payload},
            ),
            422,
        )
    review = await preview(client, site, profile)
    body(
        await client.post(
            endpoint(site, f"/{profile['id']}/apply"),
            headers=hr_workspace.headers("worker"),
            json=apply_input(review),
        ),
        403,
    )
    body(
        await client.post(
            endpoint(site, f"/{profile['id']}/archive"),
            headers=hr_workspace.headers("worker"),
            json={"request_key": str(uuid.uuid4()), "version": 1},
        ),
        403,
    )


@pytest.mark.asyncio
async def test_command_key_cannot_replay_another_path_or_kind(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_room(client, site)
    row = setup["tables"][0]
    key = str(uuid.uuid4())
    await position(client, site, row, 300, 400, key=key)
    body(
        await client.post(
            site.path(f"/tables/{setup['tables'][1]['id']}/position"),
            headers=site.headers,
            json={"request_key": key, "version": row["version"], "x": 300, "y": 400},
        ),
        409,
    )
    body(
        await client.post(
            site.path(f"/tables/{row['id']}/position"),
            headers=site.headers,
            json={"request_key": key, "version": row["version"], "x": 301, "y": 400},
        ),
        409,
    )
    body(
        await client.post(
            endpoint(site), headers=site.headers, json={**save_input(setup), "request_key": key}
        ),
        409,
    )


@pytest.mark.asyncio
async def test_concurrent_moves_and_profile_apply_use_actual_separate_transactions(
    client: AsyncClient,
) -> None:
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Layout concurrency", slug=f"layout-{uuid.uuid4().hex}", status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email=f"layout-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name="Layout manager",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Layout concurrency", tenant_id=tenant.id)
        db.add_all([user, venue])
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
        table = DiningTable(venue_id=venue.id, name="Tisch", x=100, y=100)
        db.add(table)
        await db.flush()
        site = Site(
            str(venue.id), str(table.id), "", auth_headers(create_access_token({"sub": user.email}))
        )
        await db.commit()

    async def isolated_db() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as db:
            yield db
            await db.commit()

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = isolated_db
    try:
        rows = await tables(client, site)
        profile = body(
            await client.post(
                endpoint(site),
                headers=site.headers,
                json={
                    "request_key": str(uuid.uuid4()),
                    "name": "Gesamter Betrieb",
                    "room_id": None,
                    "tables": [{"table_id": row["id"], "version": row["version"]} for row in rows],
                },
            ),
            201,
        )
        key = str(uuid.uuid4())
        move = {"request_key": key, "version": rows[0]["version"], "x": 700, "y": 800}
        responses = await asyncio.gather(
            *(
                client.post(
                    site.path(f"/tables/{site.table_id}/position"), headers=site.headers, json=move
                )
                for _ in range(2)
            )
        )
        assert all(result.status_code == 201 for result in responses)
        assert responses[0].json() == responses[1].json()
        review = await preview(client, site, profile)
        responses = await asyncio.gather(
            *(
                client.post(
                    endpoint(site, f"/{profile['id']}/apply"),
                    headers=site.headers,
                    json=apply_input(review),
                )
                for _ in range(2)
            )
        )
        assert sorted(result.status_code for result in responses) == [201, 409]
        latest = (await tables(client, site))[0]
        assert (latest["x"], latest["y"], latest["version"]) == (100, 100, 3)
        async with TestSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(FloorLayoutCommand)
                    .where(
                        FloorLayoutCommand.venue_id == uuid.UUID(site.venue_id),
                        FloorLayoutCommand.request_key == uuid.UUID(key),
                    )
                )
                == 1
            )
    finally:
        app.dependency_overrides[get_db] = original


@pytest.mark.asyncio
async def test_real_082_migration_matches_orm_and_protects_history(
    db_session: AsyncSession,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "layout082", Path("alembic/versions/082_flintplate_floor_layout_profiles.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = await db_session.connection()

    def install(sync: Connection) -> None:
        schema = f"layout_migration_{uuid.uuid4().hex}"
        old_path = sync.execute(text("SHOW search_path")).scalar_one()
        old_map = sync.get_execution_options().get("schema_translate_map")
        sync.execution_options(schema_translate_map=None)
        sync.execute(text(f'CREATE SCHEMA "{schema}"'))
        sync.execute(
            text("SELECT set_config('search_path', :path, true)"), {"path": f"{schema},public"}
        )
        try:
            for statement in (
                "CREATE TABLE fp_venues(id uuid PRIMARY KEY)",
                "CREATE TABLE users(id uuid PRIMARY KEY)",
                "CREATE TABLE fp_rooms(id uuid PRIMARY KEY,venue_id uuid NOT NULL)",
            ):
                sync.execute(text(statement))
            with Operations.context(MigrationContext.configure(sync)):
                module.upgrade()
                module.downgrade()
                module.upgrade()
            assert_migrated_orm_columns(
                sync,
                schema,
                (
                    "fp_floor_layout_profiles",
                    "fp_floor_layout_revisions",
                    "fp_floor_layout_commands",
                ),
            )
            ids = {
                name: uuid.uuid4()
                for name in (
                    "venue",
                    "user",
                    "room",
                    "profile",
                    "revision",
                    "second",
                    "command",
                    "key",
                    "table",
                )
            }
            ids["placements"] = json.dumps(
                [
                    {
                        "table_id": str(ids["table"]),
                        "version": 1,
                        "x": 100,
                        "y": 200,
                        "room_id": str(ids["room"]),
                        "area": "Restaurant",
                    }
                ]
            )
            for statement in (
                "INSERT INTO fp_venues VALUES (:venue)",
                "INSERT INTO users VALUES (:user)",
                "INSERT INTO fp_rooms VALUES (:room,:venue)",
                "INSERT INTO fp_floor_layout_profiles(id,venue_id,name,room_id) VALUES (:profile,:venue,'Original',:room)",
                "INSERT INTO fp_floor_layout_revisions(id,venue_id,profile_id,version,name,room_id,archived,placements,actor_id) VALUES (:revision,:venue,:profile,1,'Original',:room,false,CAST(:placements AS jsonb),:user)",
                "INSERT INTO fp_floor_layout_commands(id,venue_id,request_key,request_hash,kind,actor_id,result) VALUES (:command,:venue,:key,'hash','save',:user,'{}')",
            ):
                sync.execute(text(statement), ids)
            sync.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            sync.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            # Exercise the deferred COMMIT boundary explicitly inside savepoints.
            with (
                pytest.raises(DBAPIError, match="latest matching revision at commit"),
                sync.begin_nested(),
            ):
                sync.execute(
                    text(
                        "INSERT INTO fp_floor_layout_profiles(id,venue_id,name) VALUES (:id,:venue,'Missing snapshot')"
                    ),
                    {"id": uuid.uuid4(), "venue": ids["venue"]},
                )
                sync.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            with (
                pytest.raises(DBAPIError, match="latest matching revision at commit"),
                sync.begin_nested(),
            ):
                sync.execute(
                    text(
                        "INSERT INTO fp_floor_layout_revisions(id,venue_id,profile_id,previous_id,version,name,room_id,archived,placements,actor_id) VALUES (:second,:venue,:profile,:revision,2,'Neu',:room,false,CAST(:placements AS jsonb),:user)"
                    ),
                    ids,
                )
                sync.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            with pytest.raises(DBAPIError, match="matching revision"), sync.begin_nested():
                sync.execute(
                    text(
                        "UPDATE fp_floor_layout_profiles SET version=2,name='Neu' WHERE id=:profile"
                    ),
                    ids,
                )
            sync.execute(
                text(
                    "INSERT INTO fp_floor_layout_revisions(id,venue_id,profile_id,previous_id,version,name,room_id,archived,placements,actor_id) VALUES (:second,:venue,:profile,:revision,2,'Neu',:room,false,CAST(:placements AS jsonb),:user)"
                ),
                ids,
            )
            sync.execute(
                text(
                    "UPDATE fp_floor_layout_profiles SET version=2,name='Neu',updated_at=CURRENT_TIMESTAMP+INTERVAL '1 second' WHERE id=:profile"
                ),
                ids,
            )
            sync.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            sync.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            assert sync.execute(
                text("SELECT name,version FROM fp_floor_layout_profiles WHERE id=:profile"), ids
            ).one() == ("Neu", 2)
            for table in ("fp_floor_layout_revisions", "fp_floor_layout_commands"):
                for statement in (
                    f"UPDATE {table} SET updated_at=CURRENT_TIMESTAMP",
                    f"DELETE FROM {table}",
                    f"TRUNCATE {table} CASCADE",
                ):
                    with pytest.raises(DBAPIError, match="append-only"), sync.begin_nested():
                        sync.execute(text(statement))
            for statement in (
                "UPDATE fp_floor_layout_profiles SET room_id=NULL,version=3",
                "DELETE FROM fp_floor_layout_profiles",
                "TRUNCATE fp_floor_layout_profiles CASCADE",
            ):
                with pytest.raises(DBAPIError), sync.begin_nested():
                    sync.execute(text(statement))
            with (
                pytest.raises(DBAPIError, match="would erase"),
                sync.begin_nested(),
                Operations.context(MigrationContext.configure(sync)),
            ):
                module.downgrade()
            assert (
                sync.execute(
                    text("SELECT name FROM fp_floor_layout_revisions WHERE id=:revision"), ids
                ).scalar_one()
                == "Original"
            )
        finally:
            sync.execute(text("SELECT set_config('search_path', :path, true)"), {"path": old_path})
            sync.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            sync.execution_options(schema_translate_map=old_map)

    await connection.run_sync(install)
