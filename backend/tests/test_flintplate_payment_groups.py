"""Exact original-unit cents, persistent participants and independent actual tips."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.cash import drawer_balance
from app.gastro.models import Order, Venue
from app.gastro.payer_tip_models import PayerTipEntry
from app.gastro.payment_models import PaymentGroup
from app.gastro.payment_service import spread
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order, serve
from tests.test_flintplate_cash import install_cash_guards, payment, till
from tests.test_flintplate_service_presence import visit

pytest_plugins = ["tests.test_flintplate"]


async def quote(client: AsyncClient, site: Site, selection: dict) -> dict:
    return body(
        await client.post(
            site.path("/payment-groups/preview"), headers=site.headers, json=selection
        )
    )


async def pay(client: AsyncClient, site: Site, session: dict, selection: dict) -> dict:
    checked = await quote(client, site, selection)
    assert not checked["blockers"]
    return body(
        await client.post(
            site.path("/payment-groups/cash"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "quote": selection,
                "quote_hash": checked["quote_hash"],
                "session_id": session["id"],
                "received_cents": checked["amount_cents"],
                "confirmed": True,
            },
        ),
        201,
    )


async def plan(client: AsyncClient, site: Site, order: dict, people: int = 3) -> dict:
    selection = {"scope": {"order_ids": [order["id"]]}, "mode": "all"}
    checked = await quote(client, site, selection)
    return body(
        await client.post(
            site.path("/equal-split-plans"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "selection": selection,
                "quote_hash": checked["quote_hash"],
                "participants": [{"label": f"Person {i}"} for i in range(people)],
            },
        ),
        201,
    )


async def install_group_guards(db: AsyncSession) -> None:
    await install_cash_guards(db)

    def install(connection: Connection) -> None:
        from tools.payment_group_migration import install_guards

        with Operations.context(MigrationContext.configure(connection)):
            install_guards()

    await (await db.connection()).run_sync(install)


async def boundary(db: AsyncSession) -> None:
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def test_largest_remainder_keeps_every_cent_without_changing_budget() -> None:
    assert spread(5, [3, 3, 3]) == [2, 2, 1]
    assert spread(1, [0, 1000, 1000]) == [0, 1, 0]
    assert spread(0, []) == []
    with pytest.raises(Exception, match="Teilbetrag"):
        spread(4, [1, 2])


async def test_three_payers_share_original_bottle_cents_and_conserve_tax(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    await install_group_guards(db_session)
    original = order["lines"]
    allocated_tax = 0
    for cents in (333, 333, 334):
        result = await pay(
            client,
            site,
            session,
            {
                "scope": {"order_ids": [order["id"]]},
                "mode": "units",
                "units": [
                    {
                        "order_id": order["id"],
                        "line_id": original[0]["line_id"],
                        "unit": 0,
                        "amount_cents": cents,
                    }
                ],
            },
        )
        assert len(result["allocations"]) == 1
        allocated_tax += result["allocations"][0]["tax_cents"]
        assert result["entries"][0]["received_cents"] is None
        await boundary(db_session)
    remaining = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert remaining["remaining_cents"] == 1000
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert current["lines"] == original and current["paid_at"] is None
    assert allocated_tax == original[0]["tax_cents"] // 2
    assert await drawer_balance(db_session, uuid.UUID(session["id"])) == 6000


async def test_equal_plan_targets_survive_own_partial_payments(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    await install_group_guards(db_session)
    saved = await plan(client, site, order)
    assert [p["target_cents"] for p in saved["parts"]] == [667, 667, 666]
    await boundary(db_session)
    first = saved["parts"][0]
    partial = await pay(
        client,
        site,
        session,
        {"mode": "parts", "part_ids": [first["id"]], "amount_cents": 200, "new_tip_cents": 25},
    )
    assert partial["receipt_amount_cents"] == 200 and partial["amount_cents"] == 225
    await boundary(db_session)
    current = body(
        await client.get(site.path(f"/equal-split-plans/{saved['id']}"), headers=site.headers)
    )
    assert current["status"] == "open" and current["parts"][0]["remaining_cents"] == 467
    await pay(
        client, site, session, {"mode": "parts", "part_ids": [p["id"] for p in saved["parts"]]}
    )
    await boundary(db_session)
    done = body(
        await client.get(site.path(f"/equal-split-plans/{saved['id']}"), headers=site.headers)
    )
    assert done["status"] == "paid" and done["paid_cents"] == 2000
    assert [p["target_cents"] for p in done["parts"]] == [667, 667, 666]
    assert await drawer_balance(db_session, uuid.UUID(session["id"])) == 7025


async def test_foreign_payment_stales_plan_and_requires_explicit_rest_revision(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    saved = await plan(client, site, order)
    await payment(client, site, order, session, 500)
    current = body(
        await client.get(site.path(f"/equal-split-plans/{saved['id']}"), headers=site.headers)
    )
    assert current["status"] == "stale"
    assert (
        await client.post(
            site.path("/payment-groups/preview"),
            headers=site.headers,
            json={"mode": "parts", "part_ids": [saved["parts"][0]["id"]]},
        )
    ).status_code == 409
    selection = {"scope": {"order_ids": [order["id"]]}, "mode": "all"}
    checked = await quote(client, site, selection)
    command = {
        "request_key": str(uuid.uuid4()),
        "selection": selection,
        "quote_hash": checked["quote_hash"],
        "participants": [{"label": "A"}, {"label": "B"}],
        "supersedes_id": saved["id"],
        "reason": "Rest nach separater Barzahlung neu vereinbart.",
    }
    newer = body(
        await client.post(site.path("/equal-split-plans"), headers=site.headers, json=command), 201
    )
    replay = body(
        await client.post(site.path("/equal-split-plans"), headers=site.headers, json=command), 201
    )
    assert replay["id"] == newer["id"] and newer["revision"] == 2
    assert newer["total_cents"] == 1500
    old = body(
        await client.get(site.path(f"/equal-split-plans/{saved['id']}"), headers=site.headers)
    )
    assert old["status"] == "superseded" and old["next_plan_id"] == newer["id"]


async def test_quote_conflict_does_not_partially_charge_other_original(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    session = await till(client, site, hr_workspace)
    a = await serve(client, site, await sent_order(client, site))
    b = await serve(client, site, await sent_order(client, site))
    selection = {"scope": {"order_ids": [a["id"], b["id"]]}, "mode": "all"}
    checked = await quote(client, site, selection)
    await payment(client, site, a, session, 100)
    response = await client.post(
        site.path("/payment-groups/cash"),
        headers=site.headers,
        json={
            "request_key": str(uuid.uuid4()),
            "quote": selection,
            "quote_hash": checked["quote_hash"],
            "session_id": session["id"],
            "received_cents": 4000,
            "confirmed": True,
        },
    )
    assert response.status_code == 409
    assert (await db_session.execute(select(PaymentGroup.id))).first() is None
    assert (body(await client.get(site.path(f"/orders/{b['id']}/balance"), headers=site.headers)))[
        "remaining_cents"
    ] == 2000


async def test_tip_only_changes_drawer_and_distribution_without_order_payment(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    session = await till(client, site, hr_workspace)
    current = await visit(client, site)
    original = await sent_order(client, site)
    venue = await db_session.get(Venue, uuid.UUID(site.venue_id))
    assert venue is not None
    venue.tip_mode = "direct"
    await db_session.flush()
    await install_group_guards(db_session)
    group = await pay(
        client,
        site,
        session,
        {"mode": "tip_only", "payer_tab_id": current["tabs"][0]["id"], "new_tip_cents": 125},
    )
    await boundary(db_session)
    assert group["entries"] == [] and group["receipt_amount_cents"] == 0
    source = group["tip_entry_id"]
    returned = body(
        await client.post(
            site.path(f"/payer-tips/{source}/returns"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "session_id": session["id"],
                "amount_cents": 25,
                "reason": "Tatsächlich an Gast zurückgegeben.",
                "confirmed": True,
            },
        ),
        201,
    )
    assert returned["amount_cents"] == -25
    await boundary(db_session)
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    run = body(
        await client.post(
            site.path("/tips/runs"),
            headers=site.headers,
            json={"period_start": now, "period_end": now},
        ),
        201,
    )
    assert run["total_cents"] == 100 and run["orders"] == 0 and run["payer_tips"] == 1
    await boundary(db_session)
    assert (
        await client.post(
            site.path(f"/payer-tips/{source}/returns"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "session_id": session["id"],
                "amount_cents": 1,
                "reason": "Schon verteilter Betrag.",
                "confirmed": True,
            },
        )
    ).status_code == 409
    order = await db_session.get(Order, uuid.UUID(original["id"]))
    assert order is not None and order.paid_at is None and order.tip_cents == 0
    assert await drawer_balance(db_session, uuid.UUID(session["id"])) == 5100
    day = body(await client.get(site.path(f"/cash/reconciliation?day={now}"), headers=site.headers))
    assert (
        day["tip_cents"] == 100 and day["receipts"]["cash"] == 125 and day["refunds"]["cash"] == 25
    )
    export = body(
        await client.get(site.path(f"/payment-groups/export?day={now}"), headers=site.headers)
    )
    assert len(export["groups"]) == 1 and len(export["payer_tips"]) == 2


async def test_tip_return_requires_manager_actual_confirmation_and_capped_source(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    current = await visit(client, site)
    group = await pay(
        client,
        site,
        session,
        {"mode": "tip_only", "payer_tab_id": current["tabs"][0]["id"], "new_tip_cents": 100},
    )
    path = site.path(f"/payer-tips/{group['tip_entry_id']}/returns")
    command = {
        "request_key": str(uuid.uuid4()),
        "session_id": session["id"],
        "amount_cents": 100,
        "reason": "Tatsächliche Rückgabe.",
        "confirmed": True,
    }
    assert (
        await client.post(path, headers=hr_workspace.headers("worker"), json=command)
    ).status_code == 403
    assert (
        await client.post(path, headers=site.headers, json={**command, "confirmed": False})
    ).status_code == 422
    first = body(await client.post(path, headers=site.headers, json=command), 201)
    assert (
        body(await client.post(path, headers=site.headers, json=command), 201)["id"] == first["id"]
    )
    assert (
        await client.post(
            path,
            headers=site.headers,
            json={**command, "request_key": str(uuid.uuid4()), "amount_cents": 1},
        )
    ).status_code == 409


async def test_database_rejects_missing_group_children_and_mutated_tip_source(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    await install_group_guards(db_session)
    result = await pay(
        client,
        site,
        session,
        {"scope": {"order_ids": [order["id"]]}, "mode": "all", "new_tip_cents": 25},
    )
    await boundary(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE fp_payer_tip_entries SET amount_cents=26 WHERE id=:id"),
                {"id": result["tip_entry_id"]},
            )
    original = await db_session.get(PaymentGroup, uuid.UUID(result["id"]))
    assert original is not None
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            forged = PaymentGroup(
                venue_id=original.venue_id,
                session_id=original.session_id,
                actor_id=original.actor_id,
                payer_tab_id=None,
                payer_label="",
                currency="EUR",
                receipt_amount_cents=1,
                new_tip_cents=0,
                amount_cents=1,
                received_cents=1,
                change_cents=0,
                request_key=uuid.uuid4(),
                request_hash="a" * 64,
                quote_hash="a" * 64,
                source_hash="a" * 64,
                source_snapshot=[],
                quote={"mode": "all"},
                allocations=[],
            )
            db_session.add(forged)
            await db_session.flush()
            await boundary(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            tip = await db_session.get(PayerTipEntry, uuid.UUID(result["tip_entry_id"]))
            assert tip is not None
            db_session.add(
                PayerTipEntry(
                    venue_id=tip.venue_id,
                    payment_group_id=tip.payment_group_id,
                    session_id=tip.session_id,
                    original_id=tip.id,
                    kind="returned",
                    amount_cents=-26,
                    currency=tip.currency,
                    actor_id=tip.actor_id,
                    payer_tab_id=tip.payer_tab_id,
                    payer_label=tip.payer_label,
                    recipient_id=tip.recipient_id,
                    request_key=uuid.uuid4(),
                    request_hash="b" * 64,
                    reason="Forged excess return",
                )
            )
            await db_session.flush()


async def test_balance_pages_are_explicit_and_nonserved_subset_remains_visible(
    client: AsyncClient, site: Site
) -> None:
    a = await serve(client, site, await sent_order(client, site))
    b = await sent_order(client, site)
    scope = {"order_ids": [a["id"], b["id"]]}
    first = body(
        await client.post(
            site.path("/payment-groups/balance"),
            headers=site.headers,
            json={"scope": scope, "limit": 1},
        )
    )
    second = body(
        await client.post(
            site.path("/payment-groups/balance"),
            headers=site.headers,
            json={"scope": scope, "limit": 1, "before_order_id": first["next_before_order_id"]},
        )
    )
    assert first["has_more"] and not second["has_more"] and first["page_totals"]
    assert {r["order_id"] for page in (first, second) for r in page["orders"]} == {a["id"], b["id"]}
    both = await quote(client, site, {"scope": scope, "mode": "all"})
    assert {b["order_id"] for b in both["blockers"]} == {b["id"]}
    subset = await quote(
        client,
        site,
        {
            "scope": scope,
            "mode": "units",
            "units": [{"order_id": a["id"], "line_id": a["lines"][0]["line_id"], "unit": 0}],
        },
    )
    assert subset["blockers"] == []


async def test_088_migration_downgrade_upgrade_preserves_preexisting_schema(
    db_session: AsyncSession,
) -> None:
    directory = ScriptDirectory("alembic")
    revisions = list(reversed(list(directory.walk_revisions())))
    target = directory.get_revision("088")
    assert target is not None

    def check(connection: Connection) -> None:
        assert (
            connection.execute(text("SELECT current_database()")).scalar_one() == "flintplate_test"
        )
        schema = "group_roundtrip_" + uuid.uuid4().hex
        previous = connection.execute(text("SHOW search_path")).scalar_one()
        mapping = connection.get_execution_options().get("schema_translate_map")
        connection.execution_options(schema_translate_map=None)
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text("SELECT set_config('search_path',:path,true)"), {"path": f"{schema},public"}
        )
        try:
            with Operations.context(MigrationContext.configure(connection)):
                for revision in revisions:
                    revision.module.upgrade()
                target.module.downgrade()
                assert (
                    connection.execute(text("SELECT to_regclass('fp_payment_groups')")).scalar_one()
                    is None
                )
                assert (
                    connection.execute(text("SELECT to_regclass('fp_service_visits')")).scalar_one()
                    is not None
                )
                target.module.upgrade()
                connection.execute(
                    text("SELECT source_snapshot,updated_at FROM fp_payment_groups LIMIT 0")
                )
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(
                text("SELECT set_config('search_path',:path,true)"), {"path": previous}
            )
            connection.execution_options(schema_translate_map=mapping)

    await (await db_session.connection()).run_sync(check)


# Additional 088 regression cases prepared during the shared source freeze.


async def test_reserved_voucher_equal_plan_conserves_original_tax(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    from datetime import timedelta

    session = await till(client, site, hr_workspace)
    order = await sent_order(client, site)
    voucher = body(
        await client.post(
            site.path("/vouchers"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "label": "Synthetic voucher",
                "amount_cents": 1000,
                "expires_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                "reference": "Synthetic original receipt",
            },
        ),
        201,
    )
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/voucher"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": order["version"],
                "code": voucher["code"],
                "amount_cents": 800,
            },
        )
    )
    order = await serve(client, site, order)
    await install_group_guards(db_session)
    saved = await plan(client, site, order)
    assert [p["target_cents"] for p in saved["parts"]] == [400, 400, 400]
    await boundary(db_session)
    for part in saved["parts"]:
        await pay(client, site, session, {"mode": "parts", "part_ids": [part["id"]]})
        await boundary(db_session)
    balance = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert balance["remaining_cents"] == 0
    assert len([entry for entry in balance["entries"] if entry["method"] == "voucher"]) == 1
    assert sum(a["tax_cents"] for entry in balance["entries"] for a in entry["allocations"]) == sum(
        line["tax_cents"] for line in order["lines"]
    )
    assert await drawer_balance(db_session, uuid.UUID(session["id"])) == 6200


async def test_additive_tip_survives_count_close_and_original_replay(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    session = await till(client, site, hr_workspace)
    current = await visit(client, site)
    await install_group_guards(db_session)
    selection = {"mode": "tip_only", "payer_tab_id": current["tabs"][0]["id"], "new_tip_cents": 125}
    checked = await quote(client, site, selection)
    command = {
        "request_key": str(uuid.uuid4()),
        "quote": selection,
        "quote_hash": checked["quote_hash"],
        "session_id": session["id"],
        "received_cents": 200,
        "confirmed": True,
    }
    original = body(
        await client.post(site.path("/payment-groups/cash"), headers=site.headers, json=command),
        201,
    )
    await boundary(db_session)
    counted = body(
        await client.post(
            site.path(f"/cash/sessions/{session['id']}/count"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": session["version"],
                "counted_cents": 5120,
                "reason": "Fünf Cent Zähldifferenz festgestellt.",
            },
        )
    )
    assert counted["expected_cents"] == 5125 and counted["difference_cents"] == -5
    closed = body(
        await client.post(
            site.path(f"/cash/sessions/{session['id']}/close"),
            headers=site.headers,
            json={"version": counted["version"], "reason": "Differenz geprüft und dokumentiert."},
        )
    )
    assert closed["status"] == "closed"
    await boundary(db_session)
    assert (
        body(
            await client.post(
                site.path("/payment-groups/cash"), headers=site.headers, json=command
            ),
            201,
        )
        == original
    )
    assert (
        await client.post(
            site.path("/payment-groups/cash"),
            headers=site.headers,
            json={**command, "request_key": str(uuid.uuid4())},
        )
    ).status_code == 409
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE fp_cash_sessions SET expected_cents=expected_cents+1 WHERE id=:id"),
                {"id": session["id"]},
            )


async def test_database_rejects_duplicate_original_plan_budget_and_phantom_part_payment(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    from app.gastro.equal_split_models import EqualSplitPart, EqualSplitPartPayment, EqualSplitPlan

    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    await install_group_guards(db_session)
    saved = await plan(client, site, order, people=2)
    await boundary(db_session)
    original = await db_session.get(EqualSplitPlan, uuid.UUID(saved["id"]))
    assert original is not None
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            new_id = uuid.uuid4()
            db_session.add(
                EqualSplitPlan(
                    id=new_id,
                    venue_id=original.venue_id,
                    root_plan_id=new_id,
                    revision=1,
                    actor_id=original.actor_id,
                    request_key=uuid.uuid4(),
                    request_hash="c" * 64,
                    currency=original.currency,
                    total_cents=2000,
                    source_hash=original.source_hash,
                    source_snapshot=original.source_snapshot,
                    selection=original.selection,
                    reason="",
                )
            )
            await db_session.flush()
            for ordinal in range(2):
                db_session.add(
                    EqualSplitPart(
                        venue_id=original.venue_id,
                        plan_id=new_id,
                        ordinal=ordinal,
                        label="Forged duplicate bottle budget",
                        target_cents=1000,
                        unit_budgets=[
                            {
                                "order_id": order["id"],
                                "line_id": order["lines"][0]["line_id"],
                                "unit": 0,
                                "amount_cents": 1000,
                            }
                        ],
                    )
                )
            await db_session.flush()
            await boundary(db_session)
    result = await pay(
        client,
        site,
        session,
        {"scope": {"order_ids": [order["id"]]}, "mode": "amount", "amount_cents": 500},
    )
    await boundary(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            db_session.add(
                EqualSplitPartPayment(
                    venue_id=original.venue_id,
                    group_id=uuid.UUID(result["id"]),
                    part_id=uuid.UUID(saved["parts"][0]["id"]),
                    amount_cents=500,
                    allocations=[
                        {**row, "entry_id": result["entries"][0]["id"]}
                        for row in result["allocations"]
                    ],
                )
            )
            await db_session.flush()
            await boundary(db_session)


@pytest.mark.parametrize("fault", ["wrong_period", "missing_source", "unproved_order_link"])
async def test_tip_distribution_database_requires_period_and_complete_source_evidence(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession, fault: str
) -> None:
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from app.gastro.models import TipRun, TipShare
    from app.gastro.payer_tip_models import TipRunSource
    from app.gastro.payment_service import digest

    session = await till(client, site, hr_workspace)
    current = await visit(client, site)
    order = await sent_order(client, site)
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/tip"),
            headers=site.headers,
            json={"version": order["version"], "tip_cents": 100},
        )
    )
    order = await serve(client, site, order)
    await install_group_guards(db_session)
    group = await pay(
        client,
        site,
        session,
        {
            "scope": {"order_ids": [order["id"]]},
            "mode": "all",
            "new_tip_cents": 125,
            "payer_tab_id": current["tabs"][0]["id"],
        },
    )
    await boundary(db_session)
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    period = today - timedelta(days=1) if fault == "wrong_period" else today
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            run = TipRun(
                venue_id=uuid.UUID(site.venue_id),
                period_start=period,
                period_end=period,
                mode="direct",
                kitchen_bps=0,
                total_cents=125,
                orders=0,
                actor_id=hr_workspace.hr.id,
                note="Synthetic direct SQL source test",
            )
            db_session.add(run)
            await db_session.flush()
            db_session.add(
                TipShare(
                    run_id=run.id,
                    worker_id=hr_workspace.hr.id,
                    pool="direkt",
                    minutes=0,
                    share_cents=125,
                    reason="Synthetic distribution",
                )
            )
            if fault != "missing_source":
                snapshot = {
                    "payer_tip_id": group["tip_entry_id"],
                    "payment_group_id": group["id"],
                    "amount_cents": 125,
                    "received_cents": 125,
                    "timezone": "Europe/Berlin",
                }
                db_session.add(
                    TipRunSource(
                        venue_id=uuid.UUID(site.venue_id),
                        run_id=run.id,
                        kind="payer_tip",
                        payer_tip_id=uuid.UUID(group["tip_entry_id"]),
                        amount_cents=125,
                        source_hash=digest(snapshot),
                        source_snapshot=snapshot,
                    )
                )
            await db_session.flush()
            if fault == "unproved_order_link":
                await db_session.execute(
                    text("UPDATE fp_orders SET tip_run_id=:run WHERE id=:order"),
                    {"run": run.id, "order": order["id"]},
                )
            await boundary(db_session)


@pytest.mark.parametrize("handed_off", [False, True])
async def test_historical_cancelled_original_cannot_be_reopened_by_old_equal_plan(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
    handed_off: bool,
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    await install_group_guards(db_session)
    saved = await plan(client, site, order)
    await boundary(db_session)
    selection = {"mode": "parts", "part_ids": [saved["parts"][0]["id"]]}
    checked = await quote(client, site, selection)
    # Reproduce an old logical cancellation without creating fictitious modern
    # unit claims, keeping both historic handoff variants financially closed.
    await db_session.execute(
        text("UPDATE fp_orders SET status='cancelled', pos_requested=:handed WHERE id=:id"),
        {"id": order["id"], "handed": handed_off},
    )
    await boundary(db_session)
    state = body(
        await client.get(site.path(f"/equal-split-plans/{saved['id']}"), headers=site.headers)
    )
    assert state["status"] == "stale"
    assert (
        await client.post(
            site.path("/payment-groups/preview"), headers=site.headers, json=selection
        )
    ).status_code == 409
    assert (
        await client.post(
            site.path("/payment-groups/cash"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "quote": selection,
                "quote_hash": checked["quote_hash"],
                "session_id": session["id"],
                "received_cents": checked["amount_cents"],
                "confirmed": True,
            },
        )
    ).status_code == 409
    balance = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert balance["historical_cancelled"] and balance["remaining_cents"] == 0
    assert balance["entries"] == []
    assert (await db_session.execute(select(PaymentGroup.id))).first() is None
    original = await db_session.get(Order, uuid.UUID(order["id"]))
    assert original is not None and original.paid_at is None
