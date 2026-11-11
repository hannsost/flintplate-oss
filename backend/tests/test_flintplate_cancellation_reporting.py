"""A waiver must not become income; a refund approval must not become a payout."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order, serve
from tests.test_flintplate_cash import payment, till

pytest_plugins = ["tests.test_flintplate"]


async def cancel_line(client: AsyncClient, site: Site, order: dict, line: dict) -> dict:
    selection = {
        "version": order["version"],
        "lines": [{"line_id": line["line_id"], "quantity": line["quantity"]}],
        "reason_code": "quality",
        "note": "Synthetische Reklamation für die Reporting-Abnahme",
    }
    path = site.path(f"/orders/{order['id']}/cancellations")
    preview = body(await client.post(path + "/preview", headers=site.headers, json=selection))
    result = body(
        await client.post(
            path,
            headers=site.headers,
            json={
                **selection,
                "preview_hash": preview["preview_hash"],
                "request_key": str(uuid.uuid4()),
                "approve": True,
            },
        ),
        201,
    )
    return result["execution"]


async def two_lines(client: AsyncClient, site: Site) -> dict:
    return await serve(
        client,
        site,
        await sent_order(
            client,
            site,
            lines=[
                {"item_id": site.item_id, "menu_version": 1, "quantity": 1, "note": note}
                for note in ("Erster Gast", "Zweiter Gast")
            ],
        ),
    )


@pytest.mark.asyncio
async def test_unpaid_line_waiver_closes_remainder_without_fabricating_payment_or_revenue(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    order = await two_lines(client, site)
    first, second = order["lines"]
    order = await payment(
        client,
        site,
        order,
        session,
        1000,
        mode="items",
        items=[{"line_id": first["line_id"], "quantity": 1}],
    )
    assert order["paid_at"] is None
    before = body(await client.get(site.path("/overview"), headers=site.headers))
    assert before["open_total_cents"] == 1000
    assert before["settled_total_cents"] == 1000
    execution = await cancel_line(client, site, order, second)
    assert execution["money"]["unpaid_credit_cents"] == 1000
    assert execution["money"]["refund_due_cents"] == 0
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert current["paid_at"] is None and current["total_cents"] == 2000
    balance = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert balance["remaining_cents"] == 0
    assert len(balance["entries"]) == 1 and balance["entries"][0]["amount_cents"] == 1000
    after = body(await client.get(site.path("/overview"), headers=site.headers))
    assert after["open_total_cents"] == 0 and after["settled_total_cents"] == 1000
    insights = body(await client.get(site.path("/insights"), headers=site.headers))
    expected = first["total_cents"] - first["tax_cents"]
    assert insights["revenue_before_refunds_net_cents"] == expected
    assert insights["revenue_net_cents"] == expected
    assert insights["unpaid_cancellation_net_cents"] == second["total_cents"] - second["tax_cents"]


@pytest.mark.asyncio
async def test_approved_paid_cancellation_is_not_a_cash_refund_until_confirmed(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    session = await till(client, site, hr_workspace)
    order = await two_lines(client, site)
    order = await payment(client, site, order, session, 2000)
    execution = await cancel_line(client, site, order, order["lines"][1])
    before = body(await client.get(site.path("/overview"), headers=site.headers))
    assert before["settled_total_cents"] == 2000
    balance = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert balance["refund_due_cents"] == 1000 and balance["refunded_cents"] == 0
    source = balance["refund_claims"][0]["original_id"]
    refund = body(
        await client.post(
            site.path(f"/cash/payments/{source}/refunds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "amount_cents": 300,
                "session_id": session["id"],
                "reason": "Teilbetrag tatsächlich zurückgegeben",
                "cancellation_id": execution["id"],
                "confirmed": True,
            },
        ),
        201,
    )
    after = body(await client.get(site.path("/overview"), headers=site.headers))
    assert after["settled_total_cents"] == 1700
    balance = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert balance["refund_due_cents"] == 700 and balance["refunded_cents"] == 300
    insights = body(await client.get(site.path("/insights"), headers=site.headers))
    returned_net = sum(row["amount_cents"] - row["tax_cents"] for row in refund["allocations"])
    original_net = sum(line["total_cents"] - line["tax_cents"] for line in order["lines"])
    assert insights["revenue_net_cents"] == original_net - returned_net
    assert insights["refunded_net_cents"] == returned_net
    assert insights["unpaid_cancellation_net_cents"] == 0


@pytest.mark.asyncio
async def test_overview_does_not_mix_reads_before_and_after_a_concurrent_payment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.admin.models import Customer
    from app.database import get_db
    from app.gastro.models import Membership, Order, Venue
    from app.main import app
    from app.security import create_access_token
    from app.users.models import User
    from tests.conftest import TestSessionLocal
    from tests.utils import auth_headers

    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Snapshot concurrency", slug=f"snapshot-{uuid.uuid4().hex}", status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email=f"snapshot-{uuid.uuid4().hex}@example.test",
            hashed_password="synthetic-unused",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Concurrent reporting", tenant_id=tenant.id)
        db.add_all([user, venue])
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
        order = Order(
            venue_id=venue.id,
            actor_id=user.id,
            request_key=uuid.uuid4(),
            request_hash="f" * 64,
            number="SNAPSHOT-TEST",
            status="served",
            fulfillment_status="served",
            lines=[
                {
                    "line_id": str(uuid.uuid4()),
                    "item_id": str(uuid.uuid4()),
                    "name": "Synthetic receipt",
                    "sku": "SNAPSHOT",
                    "menu_version": 1,
                    "quantity": 1,
                    "price_cents": 1000,
                    "tax_rate_bps": 0,
                    "tax_cents": 0,
                    "total_cents": 1000,
                    "allergens": [],
                    "station": "kitchen",
                    "note": "",
                    "kind": "product",
                    "preparation_status": "served",
                }
            ],
            subtotal_cents=1000,
            total_cents=1000,
            currency="EUR",
        )
        db.add(order)
        await db.commit()
        headers = auth_headers(create_access_token({"sub": user.email}))
        base = f"/gastro/venues/{venue.id}"
        order_id, operator_id = str(order.id), str(user.id)

    async def independent_session() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as db:
            yield db
            await db.commit()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = independent_session
    paused, release = asyncio.Event(), asyncio.Event()
    original_execute = AsyncSession.execute

    async def pause_after_day_ledger(self, statement, *args, **kwargs):
        result = await original_execute(self, statement, *args, **kwargs)
        if "fp_cash_entries.created_at >=" in str(statement) and not paused.is_set():
            paused.set()
            await asyncio.wait_for(release.wait(), timeout=15)
        return result

    task = None
    try:
        register = body(
            await client.post(
                base + "/cash/registers", headers=headers, json={"name": "Snapshot drawer"}
            ),
            201,
        )
        session = body(
            await client.post(
                base + "/cash/sessions",
                headers=headers,
                json={
                    "request_key": str(uuid.uuid4()),
                    "register_id": register["id"],
                    "operator_id": operator_id,
                    "opening_cents": 0,
                },
            ),
            201,
        )
        monkeypatch.setattr(AsyncSession, "execute", pause_after_day_ledger)
        task = asyncio.create_task(client.get(base + "/overview", headers=headers))
        await asyncio.wait_for(paused.wait(), timeout=15)
        paid = body(
            await client.post(
                base + f"/orders/{order_id}/cash-payments",
                headers=headers,
                json={
                    "request_key": str(uuid.uuid4()),
                    "version": 1,
                    "session_id": session["id"],
                    "amount_cents": 1000,
                },
            )
        )
        assert paid["paid_at"] is not None
        release.set()
        snapshot = body(await asyncio.wait_for(task, timeout=15))
        assert snapshot["active_orders"] == 1
        assert snapshot["open_total_cents"] == 1000
        assert snapshot["settled_total_cents"] == 0
        fresh = body(await client.get(base + "/overview", headers=headers))
        assert fresh["active_orders"] == 0 and fresh["open_total_cents"] == 0
        assert fresh["settled_total_cents"] == 1000
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        app.dependency_overrides[get_db] = previous
