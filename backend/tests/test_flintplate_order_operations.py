"""Table and kitchen lifecycle regressions: real HTTP and database snapshots."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order, serve

pytest_plugins = ["tests.test_flintplate"]


@pytest.mark.asyncio
async def test_repeat_order_preserves_original_prices_and_line_identity(
    client: AsyncClient, site: Site
) -> None:
    original = await sent_order(client, site)
    old_line = original["lines"][0]
    assert old_line["line_id"]
    served = await serve(client, site, original)
    data = {
        "request_key": str(uuid.uuid4()),
        "version": served["version"],
        "lines": [
            {
                "item_id": site.item_id,
                "menu_version": 1,
                "quantity": 1,
                "course": 2,
                "note": "Ohne Salz",
            }
        ],
    }
    path = site.path(f"/orders/{original['id']}/append")
    for _ in range(2):
        appended = body(await client.post(path, headers=site.headers, json=data))
        assert appended["total_cents"] == 3000
        assert len(appended["lines"]) == 2
        assert appended["lines"][0]["line_id"] == old_line["line_id"]
        assert appended["lines"][0]["preparation_status"] == "served"
        assert appended["lines"][1]["preparation_status"] == "sent"
        assert appended["lines"][1]["course"] == 2
        assert appended["lines"][1]["line_id"] != old_line["line_id"]
        assert appended["payment_status"] == "open"
    assert (
        await client.post(
            path,
            headers=site.headers,
            json={**data, "lines": [{"item_id": site.item_id, "menu_version": 1, "quantity": 9}]},
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_station_lines_complete_independently_then_checkout_freezes(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    order = await sent_order(
        client,
        site,
        lines=[
            {"item_id": site.item_id, "menu_version": 1, "quantity": 1},
            {"item_id": site.item_id, "menu_version": 1, "quantity": 1, "course": 2},
        ],
    )
    for index in (0, 1):
        for state in ("preparing", "ready", "served"):
            data = {"request_key": str(uuid.uuid4()), "version": order["version"], "status": state}
            path = site.path(
                f"/orders/{order['id']}/lines/{order['lines'][index]['line_id']}/status"
            )
            order = body(await client.post(path, headers=site.headers, json=data))
            repeated = body(await client.post(path, headers=site.headers, json=data))
            assert repeated["version"] == order["version"]
        if index == 0:
            assert order["fulfillment_status"] == "sent"
    assert order["fulfillment_status"] == "served"
    assert order["payment_status"] == "open"
    checkout = body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    assert checkout["payment_status"] == "requested"
    assert checkout["fulfillment_status"] == "served"
    assert (
        await client.post(
            site.path(f"/orders/{order['id']}/append"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": checkout["version"],
                "lines": [{"item_id": site.item_id, "menu_version": 1, "quantity": 1}],
            },
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_table_transfer_checks_capacity_and_access(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    order = await sent_order(client, site, guests=2)
    other = body(
        await client.post(
            site.path("/tables"), headers=site.headers, json={"name": "T02", "seats": 4}
        ),
        201,
    )
    path = site.path(f"/orders/{order['id']}/transfer")
    data = {"request_key": str(uuid.uuid4()), "version": order["version"], "table_id": other["id"]}
    assert (
        await client.post(path, headers=hr_workspace.headers("other_hr"), json=data)
    ).status_code == 404
    for _ in range(2):
        moved = body(await client.post(path, headers=site.headers, json=data))
        assert moved["table_id"] == other["id"]
        assert moved["lines"] == order["lines"]


@pytest.mark.asyncio
async def test_pending_order_keys_replay_across_the_course_upgrade(
    client: AsyncClient, site: Site, db_session
) -> None:
    import hashlib
    import json

    from sqlalchemy import select

    from app.gastro.models import Order
    from app.gastro.schemas import OrderInput

    request = site.order()
    created = await sent_order(client, site, **request)
    old_payload = OrderInput.model_validate(request).model_dump(mode="json")
    for line in old_payload["lines"]:
        line.pop("course")
    row = (
        await db_session.execute(select(Order).where(Order.id == uuid.UUID(created["id"])))
    ).scalar_one()
    row.request_hash = hashlib.sha256(
        json.dumps(old_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    await db_session.flush()
    repeated = body(
        await client.post(site.path("/orders"), headers=site.headers, json=request), 201
    )
    assert repeated["id"] == created["id"]


@pytest.mark.asyncio
async def test_active_orders_cursor_never_loses_equal_timestamp_orders(
    client: AsyncClient, site: Site
) -> None:
    created = [await sent_order(client, site) for _ in range(3)]
    seen = []
    before = ""
    for _ in range(4):
        rows = body(await client.get(site.path("/orders?limit=1" + before), headers=site.headers))
        if not rows:
            break
        seen.append(rows[0]["id"])
        before = "&before=" + rows[0]["id"]
    assert len(seen) == 3
    assert set(seen) == {order["id"] for order in created}
