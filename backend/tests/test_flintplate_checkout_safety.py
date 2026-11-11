"""Regression coverage for the audited checkout and voucher lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, pos_device
from tests.test_flintplate_tips import base, open_guest_app, served_takeaway

pytest_plugins = ["tests.test_flintplate"]


@pytest.mark.asyncio
async def test_guest_checkout_is_one_frozen_pos_snapshot(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site)
    guest = hr_workspace.headers("other_worker")
    order = await served_takeaway(client, site, guest)
    device = await pos_device(client, site)
    endpoint = base(site) + f"/orders/{order['id']}/payment-request"
    for _ in range(2):
        body(await client.post(endpoint, headers=guest, json={"tip_cents": 250}))
    assert (await client.post(endpoint, headers=guest, json={"tip_cents": 900})).status_code == 409
    # A retried service handoff with the last visible version must not duplicate it.
    frozen = body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    events = body(
        await client.get("/device/v1/events", headers={"X-FlintPlate-Key": device["token"]})
    )
    checkouts = [
        e
        for e in events
        if e["kind"] == "pos.checkout_requested" and e["aggregate_id"] == order["id"]
    ]
    assert len(checkouts) == 1
    payload = checkouts[0]["payload"]
    assert payload["tip_cents"] == 250
    assert payload["amount_due_cents"] == 2250
    assert payload["version"] == frozen["version"]
    assert len(payload["lines"]) == 1
    payment = {
        "request_key": str(uuid.uuid4()),
        "order_id": order["id"],
        "amount_cents": 2250,
        "currency": "EUR",
        "reference": "synthetic-frozen-checkout",
    }
    for _ in range(2):
        paid = body(
            await client.post(
                "/device/v1/payments", headers={"X-FlintPlate-Key": device["token"]}, json=payment
            )
        )
        assert paid["tip_cents"] == 250 and paid["status"] == "settled"


@pytest.mark.asyncio
async def test_guest_cancel_releases_voucher_exactly_once(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site)
    guest = hr_workspace.headers("other_worker")
    order = body(
        await client.post(
            base(site) + "/orders",
            headers=guest,
            json=site.order(table_id=None, fulfillment="takeaway"),
        ),
        201,
    )
    voucher = body(
        await client.post(
            site.path("/vouchers"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "label": "Synthetic voucher",
                "amount_cents": 3000,
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "reference": "synthetic-gift",
            },
        ),
        201,
    )
    rows = body(await client.get(site.path("/orders"), headers=site.headers))
    staff = next(row for row in rows if row["id"] == order["id"])
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/voucher"),
            headers=site.headers,
            json={
                "version": staff["version"],
                "request_key": str(uuid.uuid4()),
                "code": voucher["code"],
                "amount_cents": 1200,
            },
        )
    )
    for _ in range(2):
        assert (
            await client.delete(base(site) + f"/orders/{order['id']}", headers=guest)
        ).status_code == 204
    vouchers = body(await client.get(site.path("/vouchers"), headers=site.headers))
    assert next(v for v in vouchers if v["id"] == voucher["voucher"]["id"])["balance_cents"] == 3000
    rows = body(await client.get(site.path("/orders?include_closed=true"), headers=site.headers))
    cancelled = next(row for row in rows if row["id"] == order["id"])
    assert cancelled["voucher_cents"] == 0 and cancelled["status"] == "cancelled"
