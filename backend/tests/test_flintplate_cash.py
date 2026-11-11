"""Till cash conservation, mixed tenders, source refunds and settlement guards."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import cash
from app.gastro.models import (
    GuestAccount,
    LoyaltyEntry,
    Order,
    TipRun,
    TipShare,
    Voucher,
    VoucherEntry,
)
from tests.cancellation_support import approve_cancellation
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, pos_device, sent_order, serve

pytest_plugins = ["tests.test_flintplate"]


async def install_cash_guards(db_session: AsyncSession) -> None:
    connection = await db_session.connection()

    def install(sync_connection) -> None:
        spec = importlib.util.spec_from_file_location(
            "cash_migration", Path("alembic/versions/072_flintplate_cash_ledger.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(sync_connection)):
            module.install_guards()
            from tools.cancellation_money_migration import install_money_guards

            install_money_guards()

    await connection.run_sync(install)


async def till(
    client: AsyncClient, site: Site, workspace: HRWorkspace, opening: int = 5000
) -> dict:
    register = body(
        await client.post(
            site.path("/cash/registers"), headers=site.headers, json={"name": "Test drawer"}
        ),
        201,
    )
    payload = {
        "request_key": str(uuid.uuid4()),
        "register_id": register["id"],
        "operator_id": str(workspace.hr.id),
        "opening_cents": opening,
    }
    session = body(
        await client.post(site.path("/cash/sessions"), headers=site.headers, json=payload), 201
    )
    replay = body(
        await client.post(site.path("/cash/sessions"), headers=site.headers, json=payload), 201
    )
    assert replay["id"] == session["id"]
    assert session["expected_cents"] is None
    return session


async def payment(
    client: AsyncClient, site: Site, order: dict, session: dict, amount: int, **extra: object
) -> dict:
    return body(
        await client.post(
            site.path(f"/orders/{order['id']}/cash-payments"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": order["version"],
                "session_id": session["id"],
                "amount_cents": amount,
                **extra,
            },
        )
    )


@pytest.mark.asyncio
async def test_cash_then_external_partial_payment_and_retry_preserve_exact_amounts(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    payload = {
        "request_key": str(uuid.uuid4()),
        "version": order["version"],
        "session_id": session["id"],
        "amount_cents": 500,
        "received_cents": 1000,
    }
    first = body(
        await client.post(
            site.path(f"/orders/{order['id']}/cash-payments"), headers=site.headers, json=payload
        )
    )
    assert first["payment_status"] == "partial" and first["paid_at"] is None
    replay = body(
        await client.post(
            site.path(f"/orders/{order['id']}/cash-payments"), headers=site.headers, json=payload
        )
    )
    assert replay["version"] == first["version"]
    assert (
        await client.post(
            site.path(f"/orders/{order['id']}/cash-payments"),
            headers=site.headers,
            json={**payload, "amount_cents": 501},
        )
    ).status_code == 409
    remaining = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert remaining["paid_cents"] == 500 and remaining["remaining_cents"] == 1500
    assert remaining["entries"][0]["change_cents"] == 500
    pos = await pos_device(client, site)
    external = {
        "request_key": str(uuid.uuid4()),
        "order_id": order["id"],
        "amount_cents": 1500,
        "reference": "external-" + uuid.uuid4().hex,
        "currency": "EUR",
    }
    settled = body(
        await client.post(
            "/device/v1/payments", headers={"X-FlintPlate-Key": pos["token"]}, json=external
        )
    )
    assert settled["payment_status"] == "paid" and settled["paid_at"]
    after = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert after["remaining_cents"] == 0
    assert sum(e["amount_cents"] for e in after["entries"]) == 2000
    assert sum(a["tax_cents"] for e in after["entries"] for a in e["allocations"]) == sum(
        line["tax_cents"] for line in order["lines"]
    )
    # Another order cannot reuse the same external proof reference.
    second = await serve(client, site, await sent_order(client, site))
    body(
        await client.post(
            site.path(f"/orders/{second['id']}/checkout"),
            headers=site.headers,
            json={"version": second["version"]},
        )
    )
    assert (
        await client.post(
            "/device/v1/payments",
            headers={"X-FlintPlate-Key": pos["token"]},
            json={
                **external,
                "order_id": second["id"],
                "request_key": str(uuid.uuid4()),
                "amount_cents": 2000,
            },
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_position_person_and_voucher_splits_keep_tax_tip_and_voucher_sources(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    order = await sent_order(client, site)
    voucher = body(
        await client.post(
            site.path("/vouchers"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "label": "Source",
                "amount_cents": 1000,
                "expires_at": (datetime.now(UTC) + timedelta(days=365)).isoformat(),
                "reference": "test external receipt",
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
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/tip"),
            headers=site.headers,
            json={"version": order["version"], "tip_cents": 200},
        )
    )
    order = await serve(client, site, order)
    line_id = order["lines"][0]["line_id"]
    first = body(
        await client.post(
            site.path(f"/orders/{order['id']}/cash-payments"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": order["version"],
                "session_id": session["id"],
                "mode": "items",
                "items": [{"line_id": line_id, "quantity": 1}],
            },
        )
    )
    remaining = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert remaining["remaining_cents"] == 800 and remaining["remaining_tip_cents"] == 200
    second = await payment(
        client, site, first, session, 0, mode="equal", people=2, payer="Person 2"
    )
    assert second["payment_status"] == "partial"
    settled = await payment(client, site, second, session, 400, payer="Person 3")
    assert settled["payment_status"] == "paid"
    report = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert sum(e["amount_cents"] for e in report["entries"]) == 2200
    assert (
        sum(
            a["amount_cents"]
            for e in report["entries"]
            for a in e["allocations"]
            if a["kind"] == "tip"
        )
        == 200
    )
    assert sum(a["tax_cents"] for e in report["entries"] for a in e["allocations"]) == sum(
        line["tax_cents"] for line in order["lines"]
    )
    voucher_entry = next(e for e in report["entries"] if e["method"] == "voucher")
    cancellation = await approve_cancellation(client, site, order, whole=True)
    refund = {
        "request_key": str(uuid.uuid4()),
        "amount_cents": 800,
        "reason": "Return voucher source",
        "cancellation_id": cancellation["id"],
        "confirmed": True,
    }
    first_refund = body(
        await client.post(
            site.path(f"/cash/payments/{voucher_entry['id']}/refunds"),
            headers=site.headers,
            json=refund,
        ),
        201,
    )
    repeated = body(
        await client.post(
            site.path(f"/cash/payments/{voucher_entry['id']}/refunds"),
            headers=site.headers,
            json=refund,
        ),
        201,
    )
    assert first_refund["id"] == repeated["id"]
    stored = await db_session.get(Voucher, uuid.UUID(voucher["voucher"]["id"]))
    assert stored is not None and stored.balance_cents == 1000


@pytest.mark.asyncio
async def test_refunds_keep_original_and_counting_is_blind_final_and_reasoned(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    await payment(client, site, order, session, 2000)
    entries = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )["entries"]
    cancellation = await approve_cancellation(client, site, order, whole=True)
    refund = body(
        await client.post(
            site.path(f"/cash/payments/{entries[0]['id']}/refunds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "amount_cents": 100,
                "session_id": session["id"],
                "reason": "Return part",
                "cancellation_id": cancellation["id"],
                "confirmed": True,
            },
        ),
        201,
    )
    assert refund["amount_cents"] == -100 and refund["original_id"] == entries[0]["id"]
    for amount in (1000, -500):
        body(
            await client.post(
                site.path(f"/cash/sessions/{session['id']}/movements"),
                headers=site.headers,
                json={
                    "request_key": str(uuid.uuid4()),
                    "amount_cents": amount,
                    "reason": "Float adjustment",
                },
            ),
            201,
        )
    current = body(await client.get(site.path("/cash/sessions"), headers=site.headers))[0]
    assert current["expected_cents"] is None
    counted = body(
        await client.post(
            site.path(f"/cash/sessions/{session['id']}/count"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": current["version"],
                "counted_cents": 7399,
            },
        )
    )
    assert counted["expected_cents"] == 7400 and counted["difference_cents"] == -1
    assert (
        await client.post(
            site.path(f"/cash/sessions/{session['id']}/movements"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "amount_cents": 1,
                "reason": "Attempt after count",
            },
        )
    ).status_code == 409
    assert (
        await client.post(
            site.path(f"/cash/sessions/{session['id']}/close"),
            headers=site.headers,
            json={"version": counted["version"]},
        )
    ).status_code == 422
    closed = body(
        await client.post(
            site.path(f"/cash/sessions/{session['id']}/close"),
            headers=site.headers,
            json={"version": counted["version"], "reason": "One cent cash discrepancy"},
        )
    )
    assert closed["status"] == "closed"
    assert (
        await client.post(
            site.path(f"/cash/payments/{entries[0]['id']}/refunds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "amount_cents": 2000,
                "session_id": session["id"],
                "reason": "Over-refund",
                "cancellation_id": cancellation["id"],
                "confirmed": True,
            },
        )
    ).status_code in {409, 422}


@pytest.mark.asyncio
async def test_service_cannot_manage_drawers_or_use_another_operators_cash(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    worker = hr_workspace.headers("worker")
    assert (
        await client.post(
            site.path("/cash/registers"), headers=worker, json={"name": "Unauthorised"}
        )
    ).status_code == 403
    order = await serve(client, site, await sent_order(client, site))
    assert (
        await client.post(
            site.path(f"/orders/{order['id']}/cash-payments"),
            headers=worker,
            json={
                "request_key": str(uuid.uuid4()),
                "version": order["version"],
                "session_id": session["id"],
                "amount_cents": 100,
            },
        )
    ).status_code == 404
    assert (
        await client.get(site.path("/cash/sessions"), headers=hr_workspace.headers("other_worker"))
    ).status_code == 404


def test_unit_allocations_conserve_all_cents_and_tax_across_small_partials() -> None:
    order = Order(
        id=uuid.uuid4(),
        tip_cents=17,
        voucher_cents=0,
        lines=[
            {
                "line_id": str(uuid.uuid4()),
                "name": "Tax item",
                "kind": "product",
                "quantity": 3,
                "total_cents": 1001,
                "tax_cents": 160,
            }
        ],
    )
    units = cash.units_for(order, [])
    paid, tax = 0, 0
    for amount in [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 410]:
        rows = cash.allocate(amount, units)
        assert sum(int(str(row["amount_cents"])) for row in rows) == amount
        for row in rows:
            unit = next(unit for unit in units if unit.key == (row["line_id"], row["unit"]))
            unit.paid += int(str(row["amount_cents"]))
            tax += int(str(row["tax_cents"]))
        paid += amount
    assert paid == 1018 and sum(unit.remaining for unit in units) == 0 and tax == 160


@pytest.mark.asyncio
async def test_database_guards_reject_ledger_mutation_and_unproved_settlement(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    await install_cash_guards(db_session)
    run = TipRun(
        venue_id=site.venue_id,
        period_start=datetime.now(UTC).date(),
        period_end=datetime.now(UTC).date(),
        mode="direct",
        total_cents=0,
        actor_id=hr_workspace.hr.id,
    )
    account = GuestAccount(venue_id=site.venue_id, user_id=hr_workspace.hr.id)
    voucher = Voucher(
        venue_id=site.venue_id,
        code_digest=uuid.uuid4().hex,
        label="Immutable evidence",
        initial_cents=100,
        balance_cents=100,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        reference="test receipt",
        request_key=uuid.uuid4(),
    )
    db_session.add_all([run, account, voucher])
    await db_session.flush()
    db_session.add_all(
        [
            TipShare(run_id=run.id, worker_id=hr_workspace.hr.id, pool="service", share_cents=0),
            LoyaltyEntry(
                account_id=account.id, order_id=uuid.UUID(order["id"]), points=0, reason="test"
            ),
            VoucherEntry(
                venue_id=site.venue_id,
                voucher_id=voucher.id,
                amount_cents=100,
                request_key=uuid.uuid4(),
                request_hash="test",
                kind="issue",
                actor_id=hr_workspace.hr.id,
            ),
        ]
    )
    await db_session.flush()
    for table in ("fp_voucher_entries", "fp_loyalty_entries", "fp_tip_runs", "fp_tip_shares"):
        for statement in (
            f"UPDATE {table} SET updated_at=now()",
            f"DELETE FROM {table}",
            f"TRUNCATE {table} CASCADE",
        ):
            with pytest.raises(DBAPIError, match="ledger"):
                async with db_session.begin_nested():
                    await db_session.execute(text(statement))
    with pytest.raises(DBAPIError, match="ledger"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE fp_cash_entries SET amount_cents=0 WHERE session_id=:id"),
                {"id": session["id"]},
            )
    with pytest.raises(DBAPIError, match="ledger"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE fp_orders SET paid_at=now(),payment_status='paid' WHERE id=:id"),
                {"id": order["id"]},
            )
            await db_session.execute(text("SET CONSTRAINTS fp_orders_ledger_guard IMMEDIATE"))
    handed = body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    with pytest.raises(DBAPIError, match="checkout"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE fp_orders SET total_cents=1 WHERE id=:id"), {"id": order["id"]}
            )
    settled = await payment(client, site, handed, session, 2000)
    assert settled["paid_at"]
    entry = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )["entries"][0]
    cancellation = await approve_cancellation(client, site, settled, whole=True)
    returned = body(
        await client.post(
            site.path(f"/cash/payments/{entry['id']}/refunds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "amount_cents": 2000,
                "session_id": session["id"],
                "reason": "Guarded actual return",
                "cancellation_id": cancellation["id"],
                "confirmed": True,
            },
        ),
        201,
    )
    assert returned["amount_cents"] == -2000
    await db_session.execute(
        text("SET CONSTRAINTS fp_orders_ledger_guard, fp_cash_entries_order_guard IMMEDIATE")
    )


@pytest.mark.asyncio
async def test_legacy_paid_bill_without_pos_handoff_cannot_rewrite_money_or_payment_state(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    # Historical rows predate both the ledger and the mandatory POS handoff.
    created = await sent_order(client, site)
    legacy = await db_session.get(Order, uuid.UUID(created["id"]))
    assert legacy is not None
    legacy.paid_at = datetime.now(UTC)
    legacy.payment_status = "paid"
    legacy.status = "settled"
    legacy.pos_requested = False
    await db_session.flush()
    await install_cash_guards(db_session)
    for change in (
        "total_cents=1",
        "tip_cents=10",
        "lines='[]'::jsonb",
        "payment_status='unpaid'",
        "status='served'",
        "paid_at=NULL",
    ):
        with pytest.raises(DBAPIError, match="checkout|ledger"):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(f"UPDATE fp_orders SET {change} WHERE id=:id"), {"id": created["id"]}
                )
                await db_session.execute(text("SET CONSTRAINTS fp_orders_ledger_guard IMMEDIATE"))
    # An unchanged historical money snapshot remains maintainable: metadata
    # versioning must not invent a backfilled payment or force a POS handoff.
    await db_session.execute(
        text("UPDATE fp_orders SET version=version+1 WHERE id=:id"), {"id": created["id"]}
    )
    await db_session.execute(text("SET CONSTRAINTS fp_orders_ledger_guard IMMEDIATE"))
    await db_session.refresh(legacy)
    assert legacy.total_cents == created["total_cents"]
    assert legacy.payment_status == "paid" and legacy.status == "settled"
    assert legacy.paid_at is not None and legacy.pos_requested is False
