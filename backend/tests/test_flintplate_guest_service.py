"""Guest identities never replace original order, stock or financial identities."""

from __future__ import annotations

import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.models import Order
from app.gastro.service_models import (
    GuestTab,
    ServiceCommand,
    ServiceRound,
    ServiceRoundChild,
    ServiceUnitAssignment,
)
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order, serve
from tests.test_flintplate_purchase_conditions import assert_migrated_orm_columns

pytest_plugins = ["tests.test_flintplate"]


async def visit(client: AsyncClient, site: Site, **changes: object) -> dict:
    return body(
        await client.post(
            site.path("/service-visits"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "tabs": [
                    {"label": "Anna", "current_table_id": site.table_id},
                    {"label": "Ben", "current_table_id": site.table_id},
                    {"kind": "shared", "current_table_id": site.table_id},
                ],
                **changes,
            },
        ),
        201,
    )


def round_input(site: Site, visit: dict) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "visit_version": visit["version"],
        "tab_versions": [{"guest_tab_id": t["id"], "version": t["version"]} for t in visit["tabs"]],
        "fulfillment": "dine_in",
        "rows": [
            {
                "cart_row_id": str(uuid.uuid4()),
                "item_id": site.item_id,
                "menu_version": 1,
                "quantity": len(visit["tabs"]),
                "assignments": [
                    {"guest_tab_id": t["id"], "units": [i]} for i, t in enumerate(visit["tabs"])
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_service_visit_is_anonymous_numbered_and_has_explicit_presence(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    first = await visit(client, site)
    assert [(t["kind"], t["number"]) for t in first["tabs"]] == [
        ("guest", 1),
        ("guest", 2),
        ("shared", 1),
    ]
    third = body(
        await client.post(
            site.path(f"/service-visits/{first['id']}/guest-tabs"),
            headers=hr_workspace.headers("worker"),
            json={
                "request_key": str(uuid.uuid4()),
                "visit_version": first["version"],
                "current_table_id": site.table_id,
            },
        ),
        201,
    )
    assert third["number"] == 3
    presence = body(await client.get(site.path("/service-presence"), headers=site.headers))
    assert presence[0]["guest_count"] == 3
    current = body(
        await client.get(site.path(f"/service-visits/{first['id']}"), headers=site.headers)
    )
    ended = body(
        await client.post(
            site.path(f"/service-visits/{first['id']}/end"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": current["version"],
                "reason": "Gäste verlassen den Betrieb",
            },
        ),
        201,
    )
    assert ended["ended_at"] and all(not t["present"] for t in ended["tabs"])
    assert body(await client.get(site.path("/service-presence"), headers=site.headers)) == []
    assert (await db_session.execute(select(func.count()).select_from(GuestTab))).scalar_one() == 4
    body(
        await client.post(
            site.path(f"/service-visits/{first['id']}/rounds"),
            headers=site.headers,
            json=round_input(site, ended),
        ),
        409,
    )


@pytest.mark.asyncio
async def test_one_round_sends_independent_originals_and_preserves_cart_unit_mapping(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    group = await visit(client, site)
    data = round_input(site, group)
    path = site.path(f"/service-visits/{group['id']}/rounds")
    result = body(await client.post(path, headers=site.headers, json=data), 201)
    assert len(result["children"]) == 3
    assert sum(child["order"]["total_cents"] for child in result["children"]) == 3000
    assert len({c["order_id"] for c in result["children"]}) == 3
    assignments = (await db_session.execute(select(ServiceUnitAssignment))).scalars().all()
    assert {a.cart_unit for a in assignments} == {0, 1, 2} and {a.unit for a in assignments} == {0}
    assert {str(a.cart_row_id) for a in assignments} == {data["rows"][0]["cart_row_id"]}
    await serve(client, site, result["children"][0]["order"])
    current = body(
        await client.get(site.path(f"/service-rounds/{result['id']}"), headers=site.headers)
    )
    assert sorted(c["order"]["status"] for c in current["children"]) == ["sent", "sent", "served"]
    assert body(await client.post(path, headers=site.headers, json=data), 201) == result
    body(
        await client.post(path, headers=site.headers, json={**data, "note": "Andere Bestellung"}),
        409,
    )
    assert (
        await db_session.execute(select(func.count()).select_from(ServiceRoundChild))
    ).scalar_one() == 3
    context = body(
        await client.get(
            site.path("/order-service-contexts")
            + "?"
            + "&".join("order_id=" + c["order_id"] for c in result["children"]),
            headers=site.headers,
        )
    )
    assert len(context) == 3 and {c["round_id"] for c in context} == {result["id"]}
    original = result["children"][1]["order"]
    body(
        await client.post(
            site.path(f"/orders/{original['id']}/append"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": original["version"],
                "lines": site.order()["lines"],
            },
        ),
        409,
    )


@pytest.mark.asyncio
async def test_roles_scope_settings_and_different_groups_share_table_safely(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    defaults = body(await client.get(site.path("/service-settings"), headers=site.headers))
    assert defaults["version"] == 0
    data = {
        "request_key": str(uuid.uuid4()),
        "version": 0,
        "workflow": "mixed",
        "guest_label_mode": "name_or_number",
    }
    body(
        await client.put(
            site.path("/service-settings"), headers=hr_workspace.headers("worker"), json=data
        ),
        403,
    )
    changed = body(
        await client.put(site.path("/service-settings"), headers=site.headers, json=data), 201
    )
    assert (
        body(await client.put(site.path("/service-settings"), headers=site.headers, json=data), 201)
        == changed
    )
    a = await visit(client, site)
    b = await visit(client, site)
    assert a["id"] != b["id"]
    body(
        await client.get(
            site.path(f"/service-visits/{a['id']}"), headers=hr_workspace.headers("other_hr")
        ),
        404,
    )
    assert (
        body(await client.get(site.path("/service-presence"), headers=site.headers))[0][
            "guest_count"
        ]
        == 4
    )
    body(
        await client.post(
            site.path("/service-visits"),
            headers=site.headers,
            json={"request_key": str(uuid.uuid4()), "tabs": [{"current_table_id": site.table_id}]},
        ),
        409,
    )


@pytest.mark.asyncio
async def test_seat_conflict_move_and_ended_visit_leave_original_bill_unchanged(
    client: AsyncClient, site: Site
) -> None:
    target = body(
        await client.post(
            site.path("/tables"), headers=site.headers, json={"name": "Other table", "seats": 2}
        ),
        201,
    )
    group = await visit(client, site, tabs=[{"current_table_id": site.table_id, "seat_label": "1"}])
    body(
        await client.post(
            site.path("/service-visits"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "tabs": [{"current_table_id": site.table_id, "seat_label": "1"}],
            },
        ),
        409,
    )
    original = body(
        await client.post(
            site.path(f"/service-visits/{group['id']}/rounds"),
            headers=site.headers,
            json=round_input(site, group),
        ),
        201,
    )["children"][0]["order"]
    tab = group["tabs"][0]
    data = {
        "request_key": str(uuid.uuid4()),
        "version": tab["version"],
        "label": "Neuer Anzeigename",
        "current_table_id": target["id"],
        "seat_label": "2",
        "present": True,
        "reason": "Gast setzt sich nach draußen",
    }
    updated = body(
        await client.post(
            site.path(f"/guest-tabs/{tab['id']}/context"), headers=site.headers, json=data
        ),
        201,
    )
    assert (
        body(
            await client.post(
                site.path(f"/guest-tabs/{tab['id']}/context"), headers=site.headers, json=data
            ),
            201,
        )
        == updated
    )
    now = body(await client.get(site.path(f"/orders/{original['id']}"), headers=site.headers))
    assert now["table_id"] == site.table_id and now["lines"] == original["lines"]
    body(
        await client.post(
            site.path(f"/orders/{original['id']}/transfer"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": now["version"],
                "table_id": target["id"],
            },
        ),
        409,
    )
    assert (
        body(await client.get(site.path("/service-presence"), headers=site.headers))[0]["table_id"]
        == target["id"]
    )


@pytest.mark.asyncio
async def test_assignment_targets_exact_legacy_unit_and_rejects_financial_binding(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    order = await sent_order(client, site)
    group = await visit(client, site)
    a, b = group["tabs"][:2]
    payload = {
        "guest_tab_id": a["id"],
        "tab_version": a["version"],
        "reason": "Stück gehört zur anwesenden Person",
        "units": [{"order_id": order["id"], "line_id": order["lines"][0]["line_id"], "unit": 1}],
    }
    preview = body(
        await client.post(
            site.path("/guest-unit-assignments/preview"), headers=site.headers, json=payload
        )
    )
    assert not preview["blockers"]
    command = {**payload, "request_key": str(uuid.uuid4()), "preview_hash": preview["preview_hash"]}
    first = body(
        await client.post(
            site.path("/guest-unit-assignments/commit"), headers=site.headers, json=command
        ),
        201,
    )
    assert (
        body(
            await client.post(
                site.path("/guest-unit-assignments/commit"), headers=site.headers, json=command
            ),
            201,
        )
        == first
    )
    second = {**payload, "guest_tab_id": b["id"], "tab_version": b["version"]}
    preview = body(
        await client.post(
            site.path("/guest-unit-assignments/preview"), headers=site.headers, json=second
        )
    )
    result = body(
        await client.post(
            site.path("/guest-unit-assignments/commit"),
            headers=site.headers,
            json={
                **second,
                "request_key": str(uuid.uuid4()),
                "preview_hash": preview["preview_hash"],
            },
        ),
        201,
    )
    assert result["assignments"][0]["version"] == 2
    assert result["assignments"][0]["before_tab_id"] == a["id"]
    history = body(
        await client.get(site.path(f"/service-visits/{group['id']}/history"), headers=site.headers)
    )
    changes = [row for row in history["items"] if row["kind"] == "units_assigned"]
    assert len(changes) == 2
    latest = next(row for row in changes if row["result"]["assignments"][0]["version"] == 2)
    assert latest["result"] == result
    assert latest["result"]["assignments"][0]["guest_tab_id"] == b["id"]
    stored = (
        await db_session.execute(select(Order).where(Order.id == uuid.UUID(order["id"])))
    ).scalar_one()
    assert stored.lines == order["lines"]
    served = await serve(client, site, order)
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": served["version"]},
        )
    )
    blocked = body(
        await client.post(
            site.path("/guest-unit-assignments/preview"), headers=site.headers, json=payload
        )
    )
    assert blocked["blockers"]


@pytest.mark.asyncio
async def test_visit_round_and_history_pages_preserve_old_records(
    client: AsyncClient, site: Site
) -> None:
    first = await visit(client, site, tabs=[{}])
    await visit(client, site, tabs=[{}])
    await visit(client, site, tabs=[{}])
    page = body(await client.get(site.path("/service-visits?limit=2"), headers=site.headers))
    assert page["has_more"]
    tail = body(
        await client.get(
            site.path("/service-visits?limit=2&before=" + page["next_before"]), headers=site.headers
        )
    )
    assert len(tail["items"]) == 1
    for _ in range(3):
        group = body(
            await client.get(site.path(f"/service-visits/{first['id']}"), headers=site.headers)
        )
        body(
            await client.post(
                site.path(f"/service-visits/{first['id']}/rounds"),
                headers=site.headers,
                json=round_input(site, group),
            ),
            201,
        )
    page = body(
        await client.get(
            site.path(f"/service-visits/{first['id']}/rounds?limit=2"), headers=site.headers
        )
    )
    assert [r["number"] for r in page["items"]] == [3, 2]
    tail = body(
        await client.get(
            site.path(
                f"/service-visits/{first['id']}/rounds?limit=2&before=" + page["next_before"]
            ),
            headers=site.headers,
        )
    )
    assert tail["items"][0]["number"] == 1
    history = body(
        await client.get(
            site.path(f"/service-visits/{first['id']}/history?limit=2"), headers=site.headers
        )
    )
    assert history["has_more"]


@pytest.mark.asyncio
async def test_real_087_guards_enforce_command_head_round_completeness_and_immutability(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    from app.gastro.service_contexts import snapshot
    from app.gastro.service_models import ServiceSettings
    from tests.test_flintplate_cash import install_cash_guards

    await install_cash_guards(db_session)
    migration = ScriptDirectory("alembic").get_revision("087").module

    def install(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.install_guards()

    await (await db_session.connection()).run_sync(install)
    group = await visit(client, site)
    result = body(
        await client.post(
            site.path(f"/service-visits/{group['id']}/rounds"),
            headers=site.headers,
            json=round_input(site, group),
        ),
        201,
    )
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE fp_guest_tabs SET label='False state',version=version+1,last_command_id=:command WHERE id=:id"
                ),
                {"command": str(uuid.uuid4()), "id": group["tabs"][0]["id"]},
            )
            await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    for table in (
        "fp_service_commands",
        "fp_service_rounds",
        "fp_service_round_children",
        "fp_service_unit_assignments",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(f"DELETE FROM {table}"))
    # A valid service-role command cannot disguise a manager-only settings change.
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            cid = uuid.uuid4()
            settings = ServiceSettings(
                venue_id=uuid.UUID(site.venue_id),
                version=1,
                last_command_id=cid,
                workflow="counter",
                guest_label_mode="number",
            )
            db_session.add(settings)
            await db_session.flush()
            db_session.add(
                ServiceCommand(
                    id=cid,
                    venue_id=settings.venue_id,
                    request_key=uuid.uuid4(),
                    request_hash="a" * 64,
                    actor_id=hr_workspace.worker.id,
                    kind="tab_context",
                    target_id=settings.id,
                    reason="Falscher Kommandotyp",
                    snapshots=[await snapshot(db_session, settings)],
                    result={},
                )
            )
            await db_session.flush()
            await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    original = result["children"][0]["order"]
    await serve(client, site, original)
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert (
        await db_session.execute(select(func.count()).select_from(ServiceCommand))
    ).scalar_one() == 2


@pytest.mark.asyncio
async def test_real_087_migration_roundtrip_projects_all_service_model_columns(
    db_session: AsyncSession,
) -> None:
    directory = ScriptDirectory("alembic")
    migration = directory.get_revision("087").module

    def check(connection: Connection) -> None:
        assert (
            connection.execute(text("SELECT current_database()")).scalar_one() == "flintplate_test"
        )
        schema = "service_chain_" + uuid.uuid4().hex
        old_path = connection.execute(text("SHOW search_path")).scalar_one()
        old_map = connection.get_execution_options().get("schema_translate_map")
        connection.execution_options(schema_translate_map=None)
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text("SELECT set_config('search_path',:path,true)"), {"path": f"{schema},public"}
        )
        try:
            with Operations.context(MigrationContext.configure(connection)):
                for revision in reversed(list(directory.walk_revisions())):
                    revision.module.upgrade()
                    if revision.revision == "087":
                        break
                migration.downgrade()
                migration.upgrade()
            assert_migrated_orm_columns(
                connection,
                schema,
                (
                    "fp_service_commands",
                    "fp_service_settings",
                    "fp_service_visits",
                    "fp_guest_tabs",
                    "fp_service_rounds",
                    "fp_service_round_children",
                    "fp_service_unit_assignments",
                ),
            )
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(
                text("SELECT set_config('search_path',:path,true)"), {"path": old_path}
            )
            connection.execution_options(schema_translate_map=old_map)

    await (await db_session.connection()).run_sync(check)


@pytest.mark.asyncio
async def test_failed_last_guest_rolls_back_the_entire_round(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    from app.database import get_db
    from app.main import app

    group = await visit(client, site)
    tabs = sorted(group["tabs"][:2], key=lambda tab: tab["id"])
    data = {
        "request_key": str(uuid.uuid4()),
        "visit_version": group["version"],
        "tab_versions": [{"guest_tab_id": tab["id"], "version": tab["version"]} for tab in tabs],
        "rows": [
            {
                "cart_row_id": str(uuid.uuid4()),
                "item_id": site.item_id,
                "menu_version": 1 if index == 0 else 999,
                "quantity": 1,
                "assignments": [{"guest_tab_id": tab["id"], "units": [0]}],
            }
            for index, tab in enumerate(tabs)
        ],
    }

    async def transaction():
        # Reproduce production rollback ownership while retaining the fixture transaction.
        async with db_session.begin_nested():
            yield db_session

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = transaction
    try:
        body(
            await client.post(
                site.path(f"/service-visits/{group['id']}/rounds"), headers=site.headers, json=data
            ),
            409,
        )
    finally:
        app.dependency_overrides[get_db] = previous
    # Independent concurrency tests commit fixtures in the run-wide schema.
    # The failed round must leave no evidence in its own isolated venue.
    venue_id = uuid.UUID(site.venue_id)
    assert (
        await db_session.execute(
            select(func.count()).select_from(ServiceRound).where(ServiceRound.venue_id == venue_id)
        )
    ).scalar_one() == 0
    assert (
        await db_session.execute(
            select(func.count()).select_from(Order).where(Order.venue_id == venue_id)
        )
    ).scalar_one() == 0
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(ServiceUnitAssignment)
            .where(ServiceUnitAssignment.venue_id == venue_id)
        )
    ).scalar_one() == 0
