"""Reviewed corrections preserve originals, enforce roles and retain production evidence."""

from __future__ import annotations

import json
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.cancellation_models import (
    CancellationDecision,
    CancellationExecution,
    CancellationRequest,
    CancellationUnit,
)
from app.gastro.models import Event
from tests.cancellation_support import approve_cancellation
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order
from tests.test_flintplate_production import setup_recipe
from tests.test_flintplate_purchase_conditions import assert_migrated_orm_columns

pytest_plugins = ["tests.test_flintplate"]


async def request_payload(
    client: AsyncClient,
    site: Site,
    order: dict,
    *,
    whole: bool = True,
    lines: list[dict] | None = None,
) -> dict:
    selection = {
        "version": order["version"],
        "whole_order": whole,
        "lines": lines or [],
        "reason_code": "entry_error",
        "note": "Falsch aufgenommene Testbestellung",
    }
    preview = body(
        await client.post(
            site.path(f"/orders/{order['id']}/cancellations/preview"),
            headers=site.headers,
            json=selection,
        )
    )
    return {
        **selection,
        "request_key": str(uuid.uuid4()),
        "preview_hash": preview["preview_hash"],
        "approve": False,
    }


async def read_order(client: AsyncClient, site: Site, order: dict) -> dict:
    return body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))


@pytest.mark.asyncio
async def test_service_requests_manager_approves_and_direct_self_approval_is_logged(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    order = await sent_order(client, site)
    data = await request_payload(client, site, order)
    path = site.path(f"/orders/{order['id']}/cancellations")
    service = hr_workspace.headers("worker")
    body(await client.post(path, headers=service, json={**data, "approve": True}), 403)
    body(await client.post(path, headers=hr_workspace.headers("other_hr"), json=data), 404)
    request = body(await client.post(path, headers=service, json=data), 201)
    assert request["decision"] is None and request["execution"] is None
    assert (await read_order(client, site, order))["version"] == order["version"]
    decision = {
        "request_key": str(uuid.uuid4()),
        "version": order["version"],
        "preview_hash": data["preview_hash"],
        "decision": "approve",
        "note": "Durch Betriebsleitung geprüft",
    }
    decision_path = path + f"/{request['id']}/decision"
    body(await client.post(decision_path, headers=service, json=decision), 403)
    approved = body(await client.post(decision_path, headers=site.headers, json=decision), 201)
    assert approved["decision"]["actor_id"] == str(hr_workspace.hr.id)
    # The manager created the original receipt, therefore this remains explicit self-approval.
    assert approved["decision"]["self_approved"] is True
    assert approved["execution"]["money"]["unpaid_credit_cents"] == 2000
    assert approved["execution"]["money"]["refund_due_cents"] == 0
    assert (
        body(await client.post(decision_path, headers=site.headers, json=decision), 201) == approved
    )
    body(
        await client.post(
            decision_path, headers=site.headers, json={**decision, "note": "Anderer Grund"}
        ),
        409,
    )
    current = await read_order(client, site, order)
    assert current["status"] == "cancelled" and current["paid_at"] is None
    assert current["lines"] == order["lines"] and current["total_cents"] == order["total_cents"]
    assert len(current["cancelled_units"]) == 2
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CancellationExecution)
            .where(CancellationExecution.order_id == uuid.UUID(order["id"]))
        )
        == 1
    )
    event = (
        await db_session.execute(
            select(Event).where(
                Event.aggregate_id == uuid.UUID(order["id"]),
                Event.kind == "order.cancellation_decided",
            )
        )
    ).scalar_one()
    assert event.payload["self_approved"] is True


@pytest.mark.asyncio
async def test_direct_manager_replay_conflict_and_validation(
    client: AsyncClient, site: Site
) -> None:
    order = await sent_order(client, site)
    data = {**await request_payload(client, site, order), "approve": True}
    path = site.path(f"/orders/{order['id']}/cancellations")
    result = body(await client.post(path, headers=site.headers, json=data), 201)
    assert body(await client.post(path, headers=site.headers, json=data), 201) == result
    body(
        await client.post(path, headers=site.headers, json={**data, "note": "Anderer Stornogrund"}),
        409,
    )
    body(await client.post(path, headers=site.headers, json={**data, "note": " "}), 422)
    another = await sent_order(client, site)
    body(
        await client.post(
            site.path(f"/orders/{another['id']}/cancellations"), headers=site.headers, json=data
        ),
        409,
    )


@pytest.mark.asyncio
async def test_stale_request_cannot_execute_but_can_be_rejected_and_remains_visible(
    client: AsyncClient, site: Site
) -> None:
    order = await sent_order(client, site)
    payload = await request_payload(client, site, order)
    path = site.path(f"/orders/{order['id']}/cancellations")
    request = body(await client.post(path, headers=site.headers, json=payload), 201)
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/status"),
            headers=site.headers,
            json={"version": order["version"], "status": "preparing"},
        )
    )
    decision = {
        "request_key": str(uuid.uuid4()),
        "version": order["version"],
        "preview_hash": payload["preview_hash"],
        "decision": "approve",
        "note": "Aktuellen Stand geprüft",
    }
    body(
        await client.post(path + f"/{request['id']}/decision", headers=site.headers, json=decision),
        409,
    )
    rejected = body(
        await client.post(
            path + f"/{request['id']}/decision",
            headers=site.headers,
            json={**decision, "request_key": str(uuid.uuid4()), "decision": "reject"},
        ),
        201,
    )
    assert rejected["execution"] is None
    assert rejected["decision"]["decision"] == "reject"
    assert (
        body(await client.get(site.path("/cancellations?pending_only=true"), headers=site.headers))
        == []
    )
    assert len(body(await client.get(path, headers=site.headers))) == 1


@pytest.mark.asyncio
async def test_partial_cancel_before_preparation_consumes_only_remaining_units(
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
    execution = await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    assert execution["lines"][0]["stock_effect"] == "not_consumed"
    current = await read_order(client, site, order)
    assert current["lines"] == order["lines"] and len(current["cancelled_units"]) == 1
    path = site.path(f"/orders/{order['id']}/lines/{order['lines'][0]['line_id']}/status")
    data = {"request_key": str(uuid.uuid4()), "version": current["version"], "status": "preparing"}
    for _ in range(2):
        body(await client.post(path, headers=site.headers, json=data))
    snapshot = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert float(snapshot["balances"][0]["quantity"]) == 9.75
    current = await read_order(client, site, order)
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/discount"),
            headers=site.headers,
            json={
                "version": current["version"],
                "percent": 5,
                "reason": "Darf Original nicht verändern",
            },
        ),
        409,
    )
    await approve_cancellation(client, site, current, whole=True)
    assert (
        float(
            body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))[
                "balances"
            ][0]["quantity"]
        )
        == 9.75
    )


@pytest.mark.asyncio
async def test_prepared_cancellation_retains_stock_and_kitchen_receipt_until_ack(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
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
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/status"),
            headers=site.headers,
            json={"version": order["version"], "status": "preparing"},
        )
    )
    execution = await approve_cancellation(client, site, order, whole=True)
    assert execution["lines"][0]["stock_effect"] == "consumption_retained"
    assert (
        float(
            body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))[
                "balances"
            ][0]["quantity"]
        )
        == 9.5
    )
    production = (
        await db_session.execute(
            select(Event).where(
                Event.aggregate_id == uuid.UUID(order["id"]),
                Event.kind == "production.prepared_cancelled",
            )
        )
    ).scalar_one()
    assert production.payload["lines"][0]["quantity"] == 2
    queue = site.path("/cancellations/kitchen")
    assert [row["id"] for row in body(await client.get(queue, headers=site.headers))] == [
        execution["id"]
    ]
    ackpath = site.path(f"/cancellations/{execution['id']}/ack")
    key = {"request_key": str(uuid.uuid4())}
    body(await client.post(ackpath, headers=hr_workspace.headers("other_hr"), json=key), 404)
    ack = body(await client.post(ackpath, headers=hr_workspace.headers("worker"), json=key), 201)
    assert (
        body(await client.post(ackpath, headers=hr_workspace.headers("worker"), json=key), 201)
        == ack
    )
    assert body(await client.get(queue, headers=site.headers)) == []
    assert len(body(await client.get(queue + "?unacknowledged=false", headers=site.headers))) == 1


@pytest.mark.asyncio
async def test_guest_mixed_ready_sent_cannot_bypass_manager_and_unstarted_cancel_is_logged(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    body(await client.put(site.path("/guest-app"), headers=site.headers, json={"enabled": True}))
    guest = hr_workspace.headers("other_worker")
    base = f"/guest/v1/{site.venue_id}/orders"
    data = site.order(
        table_id=None,
        fulfillment="takeaway",
        lines=[
            {"item_id": site.item_id, "menu_version": 1, "quantity": 1},
            {"item_id": site.item_id, "menu_version": 1, "quantity": 1},
        ],
    )
    order = body(await client.post(base, headers=guest, json=data), 201)
    current = await read_order(client, site, order)
    for state in ("preparing", "ready"):
        current = body(
            await client.post(
                site.path(f"/orders/{order['id']}/lines/{current['lines'][0]['line_id']}/status"),
                headers=site.headers,
                json={
                    "request_key": str(uuid.uuid4()),
                    "version": current["version"],
                    "status": state,
                },
            )
        )
    assert current["status"] == "sent"
    body(await client.delete(base + f"/{order['id']}", headers=guest), 409)
    assert (await read_order(client, site, order))["lines"] == current["lines"]
    untouched = body(
        await client.post(base, headers=guest, json={**data, "request_key": str(uuid.uuid4())}), 201
    )
    body(await client.delete(base + f"/{untouched['id']}", headers=site.headers), 404)
    for _ in range(2):
        assert (await client.delete(base + f"/{untouched['id']}", headers=guest)).status_code == 204
    request = (
        await db_session.execute(
            select(CancellationRequest).where(
                CancellationRequest.order_id == uuid.UUID(untouched["id"])
            )
        )
    ).scalar_one()
    assert request.source == "guest"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CancellationExecution)
            .where(CancellationExecution.request_id == request.id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_legacy_manager_path_has_same_immutable_evidence(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    order = await sent_order(client, site)
    data = {
        "version": order["version"],
        "status": "cancelled",
        "reason": "Falsche Bestellung erfasst",
    }
    path = site.path(f"/orders/{order['id']}/status")
    first = body(await client.post(path, headers=site.headers, json=data))
    assert body(await client.post(path, headers=site.headers, json=data)) == first
    request = (
        await db_session.execute(
            select(CancellationRequest).where(
                CancellationRequest.order_id == uuid.UUID(order["id"])
            )
        )
    ).scalar_one()
    assert request.source == "legacy"
    assert (
        (
            await db_session.execute(
                select(CancellationDecision).where(CancellationDecision.request_id == request.id)
            )
        )
        .scalar_one()
        .self_approved
    )


@pytest.mark.asyncio
async def test_queue_and_kitchen_cursor_does_not_hide_older_requests(
    client: AsyncClient, site: Site
) -> None:
    created = []
    for _ in range(3):
        order = await sent_order(client, site)
        data = await request_payload(client, site, order)
        created.append(
            body(
                await client.post(
                    site.path(f"/orders/{order['id']}/cancellations"),
                    headers=site.headers,
                    json=data,
                ),
                201,
            )["id"]
        )
    first = body(await client.get(site.path("/cancellations?limit=2"), headers=site.headers))
    second = body(
        await client.get(
            site.path(f"/cancellations?limit=2&before={first[-1]['id']}"), headers=site.headers
        )
    )
    assert set(row["id"] for row in [*first, *second]) == set(created)
    assert len(first) == 2 and len(second) == 1
    for request in [*first, *second]:
        body(
            await client.post(
                site.path(f"/orders/{request['order_id']}/cancellations/{request['id']}/decision"),
                headers=site.headers,
                json={
                    "request_key": str(uuid.uuid4()),
                    "version": request["order_version"],
                    "preview_hash": request["preview"]["preview_hash"],
                    "decision": "approve",
                    "note": "Geprüfte Küchenstornierung",
                },
            ),
            201,
        )
    first = body(
        await client.get(site.path("/cancellations/kitchen?limit=2"), headers=site.headers)
    )
    second = body(
        await client.get(
            site.path(f"/cancellations/kitchen?limit=2&before={first[-1]['id']}"),
            headers=site.headers,
        )
    )
    assert len({row["id"] for row in [*first, *second]}) == 3


@pytest.mark.asyncio
async def test_085_real_migration_roundtrip_and_null_safe_approval_guards(
    db_session: AsyncSession,
) -> None:
    directory = ScriptDirectory("alembic")
    revisions = list(reversed(list(directory.walk_revisions())))
    module = directory.get_revision("085").module

    def check(connection: Connection) -> None:
        assert (
            connection.execute(text("SELECT current_database()")).scalar_one() == "flintplate_test"
        )
        schema = "cancellation_chain_" + uuid.uuid4().hex
        old_path = connection.execute(text("SHOW search_path")).scalar_one()
        old_map = connection.get_execution_options().get("schema_translate_map")
        connection.execution_options(schema_translate_map=None)
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text("SELECT set_config('search_path', :path, true)"), {"path": f"{schema},public"}
        )
        try:
            with Operations.context(MigrationContext.configure(connection)):
                for revision in revisions:
                    revision.module.upgrade()
                module.downgrade()
                module.upgrade()
            assert_migrated_orm_columns(
                connection, schema, (*module.TABLES, "fp_cancellation_checkout_acks")
            )
            # The real INSERT trigger rejects missing JSON keys before any scoped
            # fixture references; NULL must never turn the IF condition into NULL.
            for preview in (
                {},
                {
                    "order_id": None,
                    "order_version": None,
                    "lines": [],
                    "money": {"units": []},
                    "preview_hash": None,
                },
            ):
                with (
                    pytest.raises(DBAPIError, match="JSON shape|snapshot differs"),
                    connection.begin_nested(),
                ):
                    connection.execute(
                        text(
                            "INSERT INTO fp_cancellation_requests(id,venue_id,order_id,order_number,requester_id,request_key,request_hash,order_version,reason_code,note,source,selection,preview) VALUES (:id,:venue,:ord,'FP-X',:actor,:key,'hash',1,'other','Ungültiger Snapshot','staff','{}',CAST(:preview AS jsonb))"
                        ),
                        {
                            "id": uuid.uuid4(),
                            "venue": uuid.uuid4(),
                            "ord": uuid.uuid4(),
                            "actor": uuid.uuid4(),
                            "key": uuid.uuid4(),
                            "preview": json.dumps(preview),
                        },
                    )
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(
                text("SELECT set_config('search_path', :path, true)"), {"path": old_path}
            )
            connection.execution_options(schema_translate_map=old_map)

    await (await db_session.connection()).run_sync(check)


@pytest.mark.asyncio
async def test_real_cancellation_triggers_keep_originals_and_require_complete_decisions(
    client: AsyncClient,
    site: Site,
    db_session: AsyncSession,
) -> None:
    from tests.test_flintplate_cash import install_cash_guards

    original = await sent_order(client, site)
    pending_data = await request_payload(client, site, original)
    path = site.path(f"/orders/{original['id']}/cancellations")
    pending = body(await client.post(path, headers=site.headers, json=pending_data), 201)
    await install_cash_guards(db_session)
    module = ScriptDirectory("alembic").get_revision("085").module

    def install(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            module.install_guards()

    await (await db_session.connection()).run_sync(install)
    manager_id = pending["requester_id"]
    with pytest.raises(DBAPIError, match="decision lacks execution"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO fp_cancellation_decisions(id,venue_id,request_id,actor_id,request_key,request_hash,decision,note,self_approved) VALUES (:id,:venue,:request,:actor,:key,'hash','approve','Verwaiste Freigabe',true)"
                ),
                {
                    "id": uuid.uuid4(),
                    "venue": site.venue_id,
                    "request": pending["id"],
                    "actor": manager_id,
                    "key": uuid.uuid4(),
                },
            )
            await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    execution = await approve_cancellation(
        client, site, original, lines=[{"line_id": original["lines"][0]["line_id"], "quantity": 1}]
    )
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    current = await read_order(client, site, original)
    body(
        await client.post(
            site.path(f"/orders/{original['id']}/lines/{original['lines'][0]['line_id']}/status"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": current["version"],
                "status": "preparing",
            },
        )
    )
    with pytest.raises(DBAPIError, match="Immutable cancellation money snapshot"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE fp_orders SET total_cents=total_cents-1 WHERE id=:id"),
                {"id": original["id"]},
            )
    for table, key in (
        ("fp_cancellation_requests", pending["id"]),
        ("fp_cancellation_executions", execution["id"]),
    ):
        for statement in (
            f"UPDATE {table} SET updated_at=now() WHERE id=:id",
            f"DELETE FROM {table} WHERE id=:id",
            f"TRUNCATE {table} CASCADE",
        ):
            with pytest.raises(DBAPIError, match="Immutable cancellation evidence"):
                async with db_session.begin_nested():
                    await db_session.execute(text(statement), {"id": key})
    rows = (
        (
            await db_session.execute(
                select(CancellationUnit).where(
                    CancellationUnit.execution_id == uuid.UUID(execution["id"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].unit == 0


@pytest.mark.asyncio
async def test_guest_checkout_after_partial_cancellation_uses_corrected_due_and_freezes_tip(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    from tests.test_flintplate import serve
    from tests.test_flintplate_cash import install_cash_guards

    body(await client.put(site.path("/guest-app"), headers=site.headers, json={"enabled": True}))
    guest = hr_workspace.headers("other_worker")
    base = f"/guest/v1/{site.venue_id}/orders"
    order = body(
        await client.post(
            base, headers=guest, json=site.order(table_id=None, fulfillment="takeaway")
        ),
        201,
    )
    await install_cash_guards(db_session)
    await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    current = await serve(client, site, await read_order(client, site, order))
    path = base + f"/{order['id']}/payment-request"
    body(await client.post(path, headers=guest, json={"tip_cents": 100}), 409)
    assert (await read_order(client, site, order))["tip_cents"] == 0
    checked_out = body(await client.post(path, headers=guest, json={"tip_cents": 0}))
    assert checked_out["pos_requested"] is True
    assert checked_out["lines"][0]["quantity"] == 2
    assert len(checked_out["cancelled_units"]) == 1
    event = (
        await db_session.execute(
            select(Event).where(
                Event.aggregate_id == uuid.UUID(order["id"]), Event.kind == "pos.checkout_requested"
            )
        )
    ).scalar_one()
    assert event.payload["amount_due_cents"] == 1000
    assert event.payload["total_cents"] == current["total_cents"] == 2000
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_corrected_zero_due_cannot_create_another_checkout_request(
    client: AsyncClient,
    site: Site,
    db_session: AsyncSession,
) -> None:
    from tests.test_flintplate import serve
    from tests.test_flintplate_cash import install_cash_guards

    order = await sent_order(client, site)
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/discount"),
            headers=site.headers,
            json={
                "version": order["version"],
                "percent": 100,
                "reason": "Kostenlose Testportionen",
            },
        )
    )
    await install_cash_guards(db_session)
    await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    current = await serve(client, site, await read_order(client, site, order))
    response = await client.post(
        site.path(f"/orders/{order['id']}/checkout"),
        headers=site.headers,
        json={"version": current["version"]},
    )
    body(response, 409)
    assert "kein Zahlbetrag" in response.json()["detail"]
    unchanged = await read_order(client, site, order)
    assert unchanged["pos_requested"] is False and unchanged["payment_status"] == "adjusted"
    assert unchanged["paid_at"] is None and unchanged["version"] == current["version"]
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
