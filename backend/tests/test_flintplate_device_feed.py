"""POS sees local cash, mixed tenders and refunds without crossing venue scope."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.cancellation_support import approve_cancellation
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, pos_device, sent_order, serve
from tests.test_flintplate_cash import payment, till

pytest_plugins = ["tests.test_flintplate"]


async def test_pos_refreshes_local_partials_and_linked_refunds(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    pos = await pos_device(client, site)
    headers = {"X-FlintPlate-Key": pos["token"]}
    drawer = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    await payment(client, site, order, drawer, 500)
    events = body(await client.get("/device/v1/events", headers=headers))
    assert any(
        event["kind"] == "payment.partially_confirmed"
        and event["aggregate_id"] == order["id"]
        and event["payload"]["remaining_cents"] == 1500
        for event in events
    )
    cursor = max(event["sequence"] for event in events)
    response = await client.get(f"/device/v1/orders/{order['id']}/balance", headers=headers)
    balance = body(response)
    assert "no-store" in response.headers["cache-control"]
    assert balance["remaining_cents"] == 1500 and balance["paid_cents"] == 500
    original = balance["entries"][0]
    snapshot = body(await client.get(f"/device/v1/orders/{order['id']}", headers=headers))
    assert snapshot["payment_status"] == "partial" and snapshot["currency"] == "EUR"
    body(
        await client.post(
            "/device/v1/payments",
            headers=headers,
            json={
                "request_key": str(uuid.uuid4()),
                "order_id": order["id"],
                "amount_cents": balance["remaining_cents"],
                "currency": snapshot["currency"],
                "reference": "simulated-pos-" + uuid.uuid4().hex,
            },
        )
    )
    # Both units carry 250 cents of the original cash tender. Approve both,
    # then repay only its 500-cent claim; external claims remain outstanding.
    cancellation = await approve_cancellation(client, site, order, whole=True)
    corrected_balance = body(
        await client.get(f"/device/v1/orders/{order['id']}/balance", headers=headers)
    )
    assert corrected_balance["checkout_blocked"]
    assert corrected_balance["refund_due_cents"] == 2000
    refund_path = site.path(f"/cash/payments/{original['id']}/refunds")
    refund_data = {
        "request_key": str(uuid.uuid4()),
        "cancellation_id": cancellation["id"],
        "amount_cents": 500,
        "session_id": drawer["id"],
        "reason": "Physically returned test cash",
        "confirmed": True,
    }
    assert (
        await client.post(refund_path, headers=site.headers, json=refund_data)
    ).status_code == 409
    body(
        await client.post(
            f"/device/v1/orders/{order['id']}/checkout-corrections",
            headers=headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": corrected_balance["version"],
                "cancellation_version": cancellation["result_version"],
                "remaining_cents": corrected_balance["remaining_cents"],
                "cancelled_cents": corrected_balance["cancelled_cents"],
                "reference": "Synthetic POS reconciled the cancelled mixed tender",
                "confirmed": True,
                "no_pending_payments": True,
            },
        ),
        201,
    )
    body(await client.post(refund_path, headers=site.headers, json=refund_data), 201)
    later = body(await client.get(f"/device/v1/events?after={cursor}", headers=headers))
    assert any(event["kind"] == "payment.confirmed" for event in later)
    assert any(
        event["kind"] == "payment.refunded" and event["payload"]["original_id"] == original["id"]
        for event in later
    )
    assert all(event["sequence"] > cursor for event in later)
    final = body(await client.get(f"/device/v1/orders/{order['id']}/balance", headers=headers))
    assert final["remaining_cents"] == 0 and final["refunded_cents"] == 500
    assert final["refund_due_cents"] == 1500 and not final["checkout_blocked"]
    cash_claim = next(
        claim for claim in final["refund_claims"] if claim["original_id"] == original["id"]
    )
    assert cash_claim["remaining_cents"] == 0 and cash_claim["refunded_cents"] == 500
    assert any(entry["original_id"] == original["id"] for entry in final["entries"])


async def test_pos_reads_require_payment_scope_and_live_same_venue_key(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    order = await sent_order(client, site)
    pos = await pos_device(client, site)
    other_venue = body(
        await client.post(
            "/gastro/venues",
            headers=hr_workspace.headers("other_hr"),
            json={"name": "Other tenant fixture"},
        ),
        201,
    )
    other = body(
        await client.post(
            f"/gastro/venues/{other_venue['id']}/devices",
            headers=hr_workspace.headers("other_hr"),
            json={"name": "Other POS", "kind": "pos", "scopes": ["payments:write"]},
        ),
        201,
    )
    kitchen = body(
        await client.post(
            site.path("/devices"),
            headers=site.headers,
            json={"name": "Kitchen events only", "kind": "kitchen", "scopes": ["events:read"]},
        ),
        201,
    )
    for suffix in ("", "/balance"):
        path = f"/device/v1/orders/{order['id']}{suffix}"
        assert (await client.get(path)).status_code == 401
        assert (
            await client.get(path, headers={"X-FlintPlate-Key": other["token"]})
        ).status_code == 404
        assert (
            await client.get(path, headers={"X-FlintPlate-Key": kitchen["token"]})
        ).status_code == 403
    body(await client.delete(site.path(f"/devices/{pos['device']['id']}"), headers=site.headers))
    for suffix in ("", "/balance"):
        assert (
            await client.get(
                f"/device/v1/orders/{order['id']}{suffix}",
                headers={"X-FlintPlate-Key": pos["token"]},
            )
        ).status_code == 401
