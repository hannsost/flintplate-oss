"""Venue tasks are human reports with immutable assignment and revision evidence."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import Connection, MetaData, Table, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.agents.models import Agent
from app.gastro.models import Event
from app.gastro.task_models import TaskCommand
from app.users.models import User
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.test_flintplate_purchase_conditions import assert_migrated_orm_columns

pytest_plugins = ["tests.test_flintplate"]


async def create(
    client: AsyncClient, site: Site, workspace: HRWorkspace, **changes: object
) -> dict:
    return body(
        await client.post(
            site.path("/tasks"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "assigned_to": str(workspace.worker.id),
                "title": "Terrasse für Abendservice vorbereiten",
                "description": "Tische abwischen und Menükarten auslegen.",
                "due_at": "2026-10-25T02:30:00+01:00",
                "priority": "high",
                **changes,
            },
        ),
        201,
    )


async def act(
    client: AsyncClient,
    site: Site,
    task: dict,
    action: str,
    headers: dict[str, str],
    **changes: object,
) -> dict:
    return body(
        await client.post(
            site.path(f"/tasks/{task['id']}/action"),
            headers=headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": task["version"],
                "action": action,
                "note": "",
                **changes,
            },
        ),
        201,
    )


@pytest.mark.asyncio
async def test_manager_assigns_actual_member_and_worker_finishes_in_one_action(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    task = await create(client, site, hr_workspace)
    assert task["require_completion_note"] is False
    result = await act(client, site, task, "done", hr_workspace.headers("worker"))
    assert (
        result["status"] == "done" and result["completed_at"] is not None and result["version"] == 2
    )
    assert result["worker_note"] is None
    history = body(
        await client.get(
            site.path(f"/tasks/{task['id']}/history"), headers=hr_workspace.headers("worker")
        )
    )
    assert [entry["kind"] for entry in history["items"]] == ["done", "create"]
    assert history["items"][0]["actor_id"] == str(hr_workspace.worker.id)
    assert history["items"][0]["before"]["status"] == "open"
    event = (
        await db_session.execute(
            select(Event).where(
                Event.aggregate_id == uuid.UUID(task["id"]), Event.kind == "task.done"
            )
        )
    ).scalar_one()
    assert event.actor_id == hr_workspace.worker.id


@pytest.mark.asyncio
async def test_completion_note_is_enforced_only_for_explicitly_marked_task(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    task = await create(client, site, hr_workspace, require_completion_note=True)
    path = site.path(f"/tasks/{task['id']}/action")
    data = {"request_key": str(uuid.uuid4()), "version": task["version"], "action": "done"}
    body(await client.post(path, headers=hr_workspace.headers("worker"), json=data), 422)
    result = await act(
        client,
        site,
        task,
        "done",
        hr_workspace.headers("worker"),
        note="Terrasse gereinigt, zwölf Plätze vorbereitet.",
    )
    assert result["worker_note"].startswith("Terrasse gereinigt")
    body(
        await client.post(
            path,
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": result["version"],
                "action": "reopen",
            },
        ),
        422,
    )
    reopened = await act(
        client,
        site,
        result,
        "reopen",
        site.headers,
        note="Zusätzliche Kontrolle nach Regen erforderlich",
    )
    assert reopened["status"] == "open" and reopened["completed_at"] is None


@pytest.mark.asyncio
async def test_service_cannot_assign_manage_others_or_bypass_legacy_task_routes(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    worker = hr_workspace.headers("worker")
    data = {
        "request_key": str(uuid.uuid4()),
        "assigned_to": str(hr_workspace.worker.id),
        "title": "Unzulässige Zuweisung",
    }
    body(await client.post(site.path("/tasks"), headers=worker, json=data), 403)
    body(
        await client.post(
            site.path("/tasks"),
            headers=site.headers,
            json={**data, "assigned_to": str(hr_workspace.other_worker.id)},
        ),
        422,
    )
    task = await create(client, site, hr_workspace)
    body(
        await client.post(
            site.path(f"/tasks/{task['id']}/action"),
            headers=worker,
            json={
                "request_key": str(uuid.uuid4()),
                "version": 1,
                "action": "cancel",
                "note": "Nicht durch Mitarbeitende erlaubt",
            },
        ),
        403,
    )
    body(await client.get(site.path("/tasks?mine=false"), headers=worker), 403)
    body(
        await client.get(
            site.path(f"/tasks/{task['id']}"), headers=hr_workspace.headers("other_hr")
        ),
        404,
    )
    body(
        await client.patch(
            f"/zeitarbeit/tasks/{task['id']}", headers=site.headers, json={"status": "done"}
        ),
        409,
    )
    body(await client.delete(f"/zeitarbeit/tasks/{task['id']}", headers=site.headers), 409)
    body(
        await client.patch(
            f"/worker/tasks/{task['id']}", headers=worker, json={"status": "cancelled"}
        ),
        409,
    )
    assert task["id"] not in {
        row["id"] for row in body(await client.get("/zeitarbeit/tasks", headers=site.headers))
    }
    assert task["id"] not in {
        row["id"] for row in body(await client.get("/worker/tasks", headers=worker))
    }
    reassigned = await act(
        client,
        site,
        task,
        "reassign",
        site.headers,
        assigned_to=str(hr_workspace.hr.id),
        note="Schichtwechsel: Leitung übernimmt",
    )
    body(await client.get(site.path(f"/tasks/{task['id']}"), headers=worker), 404)
    body(await client.get(site.path(f"/tasks/{task['id']}/history"), headers=worker), 404)
    assert reassigned["assigned_to"] == str(hr_workspace.hr.id)


@pytest.mark.asyncio
async def test_same_request_replays_snapshot_and_conflicting_payload_or_version_is_rejected(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    key = str(uuid.uuid4())
    task = await create(client, site, hr_workspace, request_key=key)
    assert await create(client, site, hr_workspace, request_key=key) == task
    path = site.path(f"/tasks/{task['id']}/action")
    data = {"request_key": str(uuid.uuid4()), "version": 1, "action": "start", "note": "Übernommen"}
    result = body(await client.post(path, headers=hr_workspace.headers("worker"), json=data), 201)
    assert (
        body(await client.post(path, headers=hr_workspace.headers("worker"), json=data), 201)
        == result
    )
    body(
        await client.post(
            path, headers=hr_workspace.headers("worker"), json={**data, "note": "Anderer Inhalt"}
        ),
        409,
    )
    body(
        await client.post(
            path,
            headers=hr_workspace.headers("worker"),
            json={**data, "request_key": str(uuid.uuid4()), "action": "done"},
        ),
        409,
    )
    await act(client, site, result, "done", hr_workspace.headers("worker"))
    assert (
        body(await client.post(path, headers=hr_workspace.headers("worker"), json=data), 201)
        == result
    )


@pytest.mark.asyncio
async def test_task_and_history_pages_preserve_older_entries(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    tasks = [
        await create(client, site, hr_workspace, title=f"Aufgabe {index}") for index in range(3)
    ]
    first = body(await client.get(site.path("/tasks?limit=2"), headers=site.headers))
    second = body(
        await client.get(
            site.path(f"/tasks?limit=2&before={first['next_before']}"), headers=site.headers
        )
    )
    assert first["has_more"] and not second["has_more"]
    assert {row["id"] for row in [*first["items"], *second["items"]]} == {
        row["id"] for row in tasks
    }
    task = await act(client, site, tasks[0], "start", hr_workspace.headers("worker"))
    task = await act(client, site, task, "done", hr_workspace.headers("worker"))
    first = body(
        await client.get(site.path(f"/tasks/{task['id']}/history?limit=2"), headers=site.headers)
    )
    second = body(
        await client.get(
            site.path(f"/tasks/{task['id']}/history?limit=2&before={first['next_before']}"),
            headers=site.headers,
        )
    )
    assert [row["kind"] for row in [*first["items"], *second["items"]]] == [
        "done",
        "start",
        "create",
    ]


@pytest.mark.asyncio
async def test_actual_086_task_guards_require_manager_commands_and_preserve_history(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    module = ScriptDirectory("alembic").get_revision("086").module

    def install(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            module.install_guards()

    await (await db_session.connection()).run_sync(install)
    task = await create(client, site, hr_workspace)
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    with pytest.raises(DBAPIError, match="matching immutable command"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE tasks SET status='done',completed_at=now(),version=version+1 WHERE id=:id"
                ),
                {"id": task["id"]},
            )
            await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    done = await act(client, site, task, "done", hr_workspace.headers("worker"))
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    for statement in (
        "DELETE FROM tasks WHERE id=:id",
        "UPDATE tasks SET venue_id=NULL,version=version+1 WHERE id=:id",
        "DELETE FROM fp_task_commands WHERE task_id=:id",
        "UPDATE fp_task_commands SET note='Verschleiert' WHERE task_id=:id",
        "TRUNCATE fp_task_commands CASCADE",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(statement), {"id": task["id"]})
    assert done["status"] == "done"
    assert (
        len(
            (
                await db_session.execute(
                    select(TaskCommand).where(TaskCommand.task_id == uuid.UUID(task["id"]))
                )
            )
            .scalars()
            .all()
        )
        == 2
    )


@pytest.mark.asyncio
async def test_real_086_migration_roundtrip_matches_task_and_command_models(
    db_session: AsyncSession,
) -> None:
    directory = ScriptDirectory("alembic")
    revisions = list(reversed(list(directory.walk_revisions())))
    migration = directory.get_revision("086").module

    def check(connection: Connection) -> None:
        assert (
            connection.execute(text("SELECT current_database()")).scalar_one() == "flintplate_test"
        )
        schema = "tasks_chain_" + uuid.uuid4().hex
        old_path = connection.execute(text("SHOW search_path")).scalar_one()
        old_map = connection.get_execution_options().get("schema_translate_map")
        connection.execution_options(schema_translate_map=None)
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text("SELECT set_config('search_path',:path,true)"), {"path": f"{schema},public"}
        )
        try:
            with Operations.context(MigrationContext.configure(connection)):
                for revision in revisions:
                    if revision.revision == "086":
                        break
                    revision.module.upgrade()
                tenant_id, person_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                connection.execute(
                    Customer.__table__.insert().values(
                        id=tenant_id, name="Legacy tasks", slug="legacy-tasks"
                    )
                )
                connection.execute(
                    User.__table__.insert().values(
                        id=person_id,
                        tenant_id=tenant_id,
                        email="legacy@example.com",
                        hashed_password="unused",
                        role="worker",
                    )
                )
                connection.execute(
                    Agent.__table__.insert().values(
                        id=agent_id, tenant_id=tenant_id, name="Synthetic old agent"
                    )
                )
                legacy_tasks = Table("tasks", MetaData(), autoload_with=connection)
                for kind in ("human", "agent"):
                    for status in ("open", "in_progress", "done", "cancelled"):
                        connection.execute(
                            legacy_tasks.insert().values(
                                id=uuid.uuid4(),
                                tenant_id=tenant_id,
                                assigned_to=person_id if kind == "human" else None,
                                assigned_agent_id=agent_id if kind == "agent" else None,
                                assigned_by=person_id,
                                title=f"Legacy {kind} {status}",
                                due_date=date(2026, 10, 25),
                                priority="medium",
                                status=status,
                                worker_note="Existing note",
                                completed_at=None,
                            )
                        )
                before = (
                    connection.execute(text("SELECT to_jsonb(t) FROM tasks t ORDER BY id"))
                    .scalars()
                    .all()
                )
                migration.upgrade()
                after = (
                    connection.execute(
                        text(
                            "SELECT to_jsonb(t)-ARRAY['venue_id','due_at','version','require_completion_note'] FROM tasks t ORDER BY id"
                        )
                    )
                    .scalars()
                    .all()
                )
                assert after == before
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM tasks WHERE venue_id IS NULL AND due_at IS NULL AND version=1 AND require_completion_note=false"
                        )
                    ).scalar_one()
                    == 8
                )
                migration.downgrade()
                assert (
                    connection.execute(text("SELECT to_jsonb(t) FROM tasks t ORDER BY id"))
                    .scalars()
                    .all()
                    == before
                )
                migration.upgrade()
                # Old task updates remain legal without a FlintPlate command.
                connection.execute(text("UPDATE tasks SET worker_note='Legacy continuation'"))
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            assert_migrated_orm_columns(connection, schema, ("tasks", "fp_task_commands"))
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(
                text("SELECT set_config('search_path',:path,true)"), {"path": old_path}
            )
            connection.execution_options(schema_translate_map=old_map)

    await (await db_session.connection()).run_sync(check)
