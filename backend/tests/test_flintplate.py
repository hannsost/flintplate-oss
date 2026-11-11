"""FlintPlate's actual tenant, booking, tender and device boundaries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.models import Order, UsageSession
from app.gastro.schemas import MenuPayload
from app.worker.assignment_models import WorkerAssignment
from tests.hr_support import HRWorkspace, body


@dataclass
class Site:
    venue_id: str
    table_id: str
    item_id: str
    headers: dict[str, str]

    def path(self, suffix: str) -> str:
        return f"/gastro/venues/{self.venue_id}{suffix}"

    def order(self, **changes: object) -> dict:
        return {
            "request_key": str(uuid.uuid4()),
            "table_id": self.table_id,
            "lines": [{"item_id": self.item_id, "menu_version": 1, "quantity": 2}],
            **changes,
        }


@pytest.fixture
async def site(client: AsyncClient, hr_workspace: HRWorkspace) -> Site:
    headers = hr_workspace.headers()
    venue = body(
        await client.post("/gastro/venues", headers=headers, json={"name": "Synthetic FlintPlate"}),
        201,
    )
    base = f"/gastro/venues/{venue['id']}"
    body(
        await client.put(
            base + "/members",
            headers=headers,
            json={"user_id": str(hr_workspace.worker.id), "role": "service"},
        )
    )
    table = body(
        await client.post(base + "/tables", headers=headers, json={"name": "T01", "seats": 4}), 201
    )
    data = MenuPayload(
        name="Testgericht", price_cents=1000, tax_rate_bps=1900, cost_cents=250
    ).model_dump(mode="json")
    item = body(
        await client.post(base + "/menu", headers=headers, json={"sku": "S01", "data": data}), 201
    )
    body(
        await client.post(
            base + f"/menu/{item['id']}/publish", headers=headers, json={"version": 1}
        )
    )
    return Site(venue["id"], table["id"], item["id"], headers)


async def sent_order(client: AsyncClient, site: Site, **changes: object) -> dict:
    return body(
        await client.post(site.path("/orders"), headers=site.headers, json=site.order(**changes)),
        201,
    )


async def serve(client: AsyncClient, site: Site, order: dict) -> dict:
    for status in ("preparing", "ready", "served"):
        order = body(
            await client.post(
                site.path(f"/orders/{order['id']}/status"),
                headers=site.headers,
                json={"version": order["version"], "status": status},
            )
        )
    return order


async def pos_device(client: AsyncClient, site: Site) -> dict:
    return body(
        await client.post(
            site.path("/devices"),
            headers=site.headers,
            json={
                "name": "POS Fixture",
                "kind": "pos",
                "scopes": ["payments:write", "events:read"],
            },
        ),
        201,
    )


@pytest.mark.asyncio
async def test_request_ids_are_scoped_to_their_own_venue(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    key = str(uuid.uuid4())
    issued, sessions = [], []
    for headers in (hr_workspace.headers(), hr_workspace.headers("other_hr")):
        venue = body(
            await client.post(
                "/gastro/venues", headers=headers, json={"name": "Independent venue"}
            ),
            201,
        )
        base = f"/gastro/venues/{venue['id']}"
        resource = body(
            await client.post(
                base + "/tables",
                headers=headers,
                json={
                    "name": "Boat",
                    "kind": "pedal_boat",
                    "hourly_rate_cents": 1000,
                },
            ),
            201,
        )
        usage_input = {
            "request_key": key,
            "table_id": resource["id"],
            "guest_name": "Synthetic group",
            "duration_minutes": 30,
        }
        usage = body(await client.post(base + "/usage", headers=headers, json=usage_input), 201)
        assert (
            body(await client.post(base + "/usage", headers=headers, json=usage_input), 201)["id"]
            == usage["id"]
        )
        sessions.append(usage["id"])
        voucher_input = {
            "request_key": key,
            "amount_cents": 1000,
            "label": "Synthetic credit",
            "reference": "External payment",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        }
        voucher = body(
            await client.post(base + "/vouchers", headers=headers, json=voucher_input), 201
        )
        assert (
            body(await client.post(base + "/vouchers", headers=headers, json=voucher_input), 201)[
                "code"
            ]
            is None
        )
        issued.append(voucher["voucher"]["id"])
    assert len(set(issued)) == len(set(sessions)) == 2


@pytest.mark.asyncio
async def test_tenant_and_role_boundaries(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    assert (
        await client.get(site.path("/orders"), headers=hr_workspace.headers("other_hr"))
    ).status_code == 404
    assert (
        await client.get(site.path("/menu"), headers=hr_workspace.headers("worker"))
    ).status_code == 403
    assert (
        await client.put(
            site.path("/members"),
            headers=site.headers,
            json={"user_id": str(hr_workspace.other_worker.id), "role": "service"},
        )
    ).status_code == 404
    assert (
        await client.put(
            site.path("/members"),
            headers=site.headers,
            json={"user_id": str(hr_workspace.hr.id), "role": "service"},
        )
    ).status_code == 409
    catalog = (
        await client.get(site.path("/catalog"), headers=hr_workspace.headers("worker"))
    ).json()
    assert catalog[0]["price_cents"] == 1000 and "cost_cents" not in catalog[0]
    assert (await client.get(site.path("/orders"))).status_code in {401, 403}


@pytest.mark.asyncio
async def test_drafts_and_immutable_order_price(client: AsyncClient, site: Site) -> None:
    old = await sent_order(client, site)
    draft = body(
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={
                "version": 1,
                "data": {"name": "Neuer Name", "price_cents": 1500, "tax_rate_bps": 1900},
            },
        )
    )
    before = await sent_order(client, site)
    assert before["total_cents"] == old["total_cents"] == 2000
    assert (
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={"version": 1, "data": draft["draft"]},
        )
    ).status_code == 409
    body(
        await client.post(
            site.path(f"/menu/{site.item_id}/publish"), headers=site.headers, json={"version": 2}
        )
    )
    assert (
        await client.post(site.path("/orders"), headers=site.headers, json=site.order())
    ).status_code == 409
    new = await sent_order(
        client, site, lines=[{"item_id": site.item_id, "menu_version": 2, "quantity": 2}]
    )
    assert new["total_cents"] == 3000
    saved = (await client.get(site.path("/orders"), headers=site.headers)).json()
    original = next(r for r in saved if r["id"] == old["id"])
    assert original["lines"][0]["name"] == "Testgericht" and original["total_cents"] == 2000


@pytest.mark.asyncio
async def test_request_replay_and_status_permissions(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    request = site.order()
    one = body(await client.post(site.path("/orders"), headers=site.headers, json=request), 201)
    two = body(await client.post(site.path("/orders"), headers=site.headers, json=request), 201)
    assert one["id"] == two["id"]
    assert (
        await client.post(
            site.path("/orders"), headers=site.headers, json={**request, "note": "changed"}
        )
    ).status_code == 409
    assert (
        await client.post(
            site.path(f"/orders/{one['id']}/status"),
            headers=hr_workspace.headers("worker"),
            json={"version": 1, "status": "cancelled", "reason": "wrong"},
        )
    ).status_code == 403
    assert (
        await client.post(
            site.path(f"/orders/{one['id']}/status"),
            headers=site.headers,
            json={"version": 1, "status": "served"},
        )
    ).status_code == 409
    assert (
        await client.post(
            site.path(f"/orders/{one['id']}/checkout"), headers=site.headers, json={"version": 1}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_packaging_discount_and_voucher_ledger(client: AsyncClient, site: Site) -> None:
    payload = {
        "name": "Boxgericht",
        "price_cents": 1000,
        "tax_rate_bps": 1900,
        "takeaway_packaging": {
            "name": "Mehrwegbox",
            "price_cents": 50,
            "deposit_cents": 500,
            "tax_rate_bps": 1900,
            "deposit_tax_rate_bps": 0,
            "reusable": True,
        },
    }
    body(
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={"version": 1, "data": payload},
        )
    )
    body(
        await client.post(
            site.path(f"/menu/{site.item_id}/publish"), headers=site.headers, json={"version": 2}
        )
    )
    order = await sent_order(
        client,
        site,
        fulfillment="takeaway",
        lines=[{"item_id": site.item_id, "menu_version": 2, "quantity": 1}],
    )
    assert order["total_cents"] == 1550 and [r["kind"] for r in order["lines"]] == [
        "product",
        "packaging",
        "deposit",
    ]
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/discount"),
            headers=site.headers,
            json={"version": order["version"], "percent": 10, "reason": "Kulanz nach Wartezeit"},
        )
    )
    assert order["total_cents"] == 1445 and order["lines"][-1]["total_cents"] == 500
    voucher = body(
        await client.post(
            site.path("/vouchers"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "label": "Testgutschein",
                "amount_cents": 1000,
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "reference": "Synthetic external payment",
            },
        ),
        201,
    )
    request = {
        "version": order["version"],
        "request_key": str(uuid.uuid4()),
        "code": voucher["code"],
        "amount_cents": 800,
    }
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/voucher"), headers=site.headers, json=request
        )
    )
    replay = body(
        await client.post(
            site.path(f"/orders/{order['id']}/voucher"), headers=site.headers, json=request
        )
    )
    assert replay["voucher_cents"] == order["voucher_cents"] == 800 and order["total_cents"] == 1445
    assert (
        await client.post(
            site.path(f"/orders/{order['id']}/voucher"),
            headers=site.headers,
            json={
                **request,
                "version": order["version"],
                "request_key": str(uuid.uuid4()),
                "amount_cents": 500,
            },
        )
    ).status_code == 422
    assert (
        await client.post(
            site.path(f"/orders/{order['id']}/status"),
            headers=site.headers,
            json={"version": order["version"], "status": "cancelled", "reason": "test"},
        )
    ).status_code == 409
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/voucher-release"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    assert order["voucher_cents"] == 0
    assert (await client.get(site.path("/vouchers"), headers=site.headers)).json()[0][
        "balance_cents"
    ] == 1000


@pytest.mark.asyncio
async def test_pos_payment_exact_and_idempotent(client: AsyncClient, site: Site) -> None:
    order = await serve(client, site, await sent_order(client, site))
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    pos = await pos_device(client, site)
    headers = {"X-FlintPlate-Key": pos["token"]}
    payment = {
        "request_key": str(uuid.uuid4()),
        "order_id": order["id"],
        # Smaller amounts are intentional partial tenders; only overpayment is invalid.
        "amount_cents": 2001,
        "currency": "EUR",
        "reference": "synthetic-payment",
    }
    assert (
        await client.post("/device/v1/payments", headers=headers, json=payment)
    ).status_code == 422
    payment["amount_cents"] = 2000
    first = body(await client.post("/device/v1/payments", headers=headers, json=payment))
    replay = body(await client.post("/device/v1/payments", headers=headers, json=payment))
    assert (
        first["status"] == replay["status"] == "settled" and first["version"] == replay["version"]
    )
    assert (
        await client.post(
            "/device/v1/payments", headers=headers, json={**payment, "reference": "changed"}
        )
    ).status_code == 409
    body(await client.delete(site.path(f"/devices/{pos['device']['id']}"), headers=site.headers))
    assert (await client.get("/device/v1/events", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_rooms_and_activities_reservation_collision(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    floor = body(
        await client.post(
            site.path("/floors"), headers=site.headers, json={"name": "Am See", "level": 0}
        ),
        201,
    )
    room = body(
        await client.post(
            site.path("/rooms"),
            headers=site.headers,
            json={"name": "Steg", "floor_id": floor["id"]},
        ),
        201,
    )
    resource = body(
        await client.post(
            site.path("/tables"),
            headers=site.headers,
            json={
                "name": "Tretboot 01",
                "kind": "pedal_boat",
                "room_id": room["id"],
                "hourly_rate_cents": 2000,
                "billing_minutes": 15,
                "seats": 4,
            },
        ),
        201,
    )
    start = datetime.now(UTC) + timedelta(hours=1)
    request = {
        "table_id": resource["id"],
        "guest_name": "Synthetic Guest",
        "guests": 4,
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(),
    }
    body(await client.post(site.path("/reservations"), headers=site.headers, json=request), 201)
    assert (
        await client.post(site.path("/reservations"), headers=site.headers, json=request)
    ).status_code == 409
    usage = body(
        await client.post(
            site.path("/usage"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "table_id": resource["id"],
                "guest_name": "Test",
                "duration_minutes": 30,
            },
        ),
        201,
    )
    assert (
        await client.post(
            site.path("/usage"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "table_id": resource["id"],
                "guest_name": "Other",
                "duration_minutes": 30,
            },
        )
    ).status_code == 409
    row = (
        await db_session.execute(
            select(UsageSession).where(UsageSession.id == uuid.UUID(usage["id"]))
        )
    ).scalar_one()
    row.starts_at = datetime.now(UTC) - timedelta(minutes=16)
    await db_session.flush()
    billed = body(
        await client.post(site.path(f"/usage/{usage['id']}/finish"), headers=site.headers)
    )
    replay = body(
        await client.post(site.path(f"/usage/{usage['id']}/finish"), headers=site.headers)
    )
    assert (
        billed["total_cents"] == 1000
        and billed["id"] == replay["id"]
        and billed["status"] == "served"
    )


@pytest.mark.asyncio
async def test_gastro_shift_bridges_palmscout(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    start = datetime.now(UTC) + timedelta(days=1)
    data = {
        "worker_id": str(hr_workspace.worker.id),
        "station": "Service",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=6)).isoformat(),
        "break_minutes": 30,
    }
    shift = body(await client.post(site.path("/shifts"), headers=site.headers, json=data), 201)
    assert (
        await client.post(site.path("/shifts"), headers=site.headers, json=data)
    ).status_code == 409
    assert (
        await client.get(site.path("/shifts"), headers=hr_workspace.headers("worker"))
    ).json() == []
    body(
        await client.post(
            site.path(f"/shifts/{shift['id']}/status"),
            headers=site.headers,
            json={"version": 1, "status": "published"},
        )
    )
    assignment = (
        await db_session.execute(
            select(WorkerAssignment).where(WorkerAssignment.id == uuid.UUID(shift["assignment_id"]))
        )
    ).scalar_one()
    assert assignment.status == "confirmed"
    assert (
        len((await client.get(site.path("/shifts"), headers=hr_workspace.headers("worker"))).json())
        == 1
    )


@pytest.mark.asyncio
async def test_guest_private_scope_and_points(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    base = f"/guest/v1/{site.venue_id}"
    assert (await client.get(base + "/catalog")).status_code == 404
    body(await client.put(site.path("/guest-app"), headers=site.headers, json={"enabled": True}))
    catalog = (await client.get(base + "/catalog")).json()
    assert "cost_cents" not in catalog[0]
    # A tenant unrelated to the venue can be a guest, never a staff member.
    headers = hr_workspace.headers("other_worker")
    assert (
        await client.post(base + "/orders", headers=headers, json=site.order())
    ).status_code == 422
    order = body(
        await client.post(
            base + "/orders",
            headers=headers,
            json=site.order(table_id=None, fulfillment="takeaway"),
        ),
        201,
    )
    assert "payment_reference" not in order
    assert (await client.get(base + "/orders", headers=site.headers)).json() == []
    assert len((await client.get(base + "/orders", headers=headers)).json()) == 1
    staff_order = (
        await db_session.execute(select(Order).where(Order.id == uuid.UUID(order["id"])))
    ).scalar_one()
    from app.gastro.schemas import OrderRead

    served = await serve(
        client, site, OrderRead.model_validate(staff_order).model_dump(mode="json")
    )
    body(
        await client.post(
            site.path(f"/orders/{served['id']}/checkout"),
            headers=site.headers,
            json={"version": served["version"]},
        )
    )
    pos = await pos_device(client, site)
    payment = {
        "request_key": str(uuid.uuid4()),
        "order_id": order["id"],
        "amount_cents": 2000,
        "currency": "EUR",
        "reference": "guest-payment",
    }
    body(
        await client.post(
            "/device/v1/payments", headers={"X-FlintPlate-Key": pos["token"]}, json=payment
        )
    )
    body(
        await client.post(
            "/device/v1/payments", headers={"X-FlintPlate-Key": pos["token"]}, json=payment
        )
    )
    assert (await client.get(base + "/account", headers=headers)).json()["points"] == 20


@pytest.mark.asyncio
async def test_device_events_exclude_private_records(client: AsyncClient, site: Site) -> None:
    pos = await pos_device(client, site)
    records = (
        await client.get("/device/v1/events", headers={"X-FlintPlate-Key": pos["token"]})
    ).json()
    assert records and all(e["kind"] == "menu.published" for e in records)
    assert "cost_cents" not in records[0]["payload"]["data"]
    assert (
        await client.post(
            "/device/v1/orders", headers={"X-FlintPlate-Key": pos["token"]}, json=site.order()
        )
    ).status_code == 403
