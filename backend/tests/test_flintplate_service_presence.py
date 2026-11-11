"""Visit presence bridges current seating and historical original receipts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.booking_service import conflicting_resources
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order, serve
from tests.test_flintplate_cash import payment, till

pytest_plugins = ["tests.test_flintplate"]


async def visit(client: AsyncClient, site: Site, guests: int = 1) -> dict:
    return body(
        await client.post(
            site.path("/service-visits"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "tabs": [{"current_table_id": site.table_id} for _ in range(guests)],
            },
        ),
        201,
    )


async def round_for(client: AsyncClient, site: Site, current: dict) -> dict:
    guest = current["tabs"][0]
    return body(
        await client.post(
            site.path(f"/service-visits/{current['id']}/rounds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "visit_version": current["version"],
                "tab_versions": [{"guest_tab_id": guest["id"], "version": guest["version"]}],
                "rows": [
                    {
                        "cart_row_id": str(uuid.uuid4()),
                        "item_id": site.item_id,
                        "menu_version": 1,
                        "quantity": 1,
                        "assignments": [{"guest_tab_id": guest["id"], "units": [0]}],
                    }
                ],
            },
        ),
        201,
    )


async def occupied(db: AsyncSession, tables: list[str], *, live: bool = True) -> set[str]:
    start = datetime.now(UTC) + (timedelta(0) if live else timedelta(days=7))
    found = await conflicting_resources(
        db,
        [uuid.UUID(value) for value in tables],
        start,
        start + timedelta(hours=1),
        live=live,
    )
    return {str(value) for value in found}


async def test_unordered_visit_blocks_live_admission_but_not_future_reservations(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    current = await visit(client, site, guests=2)
    assert len(current["tabs"]) == 2
    assert await occupied(db_session, [site.table_id]) == {site.table_id}
    assert await occupied(db_session, [site.table_id], live=False) == set()
    now = datetime.now(UTC)
    response = await client.post(
        site.path("/reservations"),
        headers=site.headers,
        json={
            "table_id": site.table_id,
            "guest_name": "Independent admission",
            "guests": 2,
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 409


async def test_paid_guest_keeps_presence_until_explicit_departure(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    current = await visit(client, site)
    sent = await round_for(client, site, current)
    order = await serve(client, site, sent["children"][0]["order"])
    session = await till(client, site, hr_workspace)
    paid = await payment(client, site, order, session, order["total_cents"])
    assert paid["paid_at"] and paid["payment_status"] == "paid"
    assert await occupied(db_session, [site.table_id]) == {site.table_id}
    fresh = body(
        await client.get(site.path(f"/service-visits/{current['id']}"), headers=site.headers)
    )
    body(
        await client.post(
            site.path(f"/service-visits/{current['id']}/end"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": fresh["version"],
                "reason": "Gast hat das Restaurant verlassen.",
            },
        ),
        201,
    )
    assert await occupied(db_session, [site.table_id]) == set()


async def test_move_uses_current_guest_place_and_preserves_original_table(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    other = body(
        await client.post(
            site.path("/tables"), headers=site.headers, json={"name": "T02", "seats": 4}
        ),
        201,
    )
    current = await visit(client, site)
    sent = await round_for(client, site, current)
    guest = current["tabs"][0]
    body(
        await client.post(
            site.path(f"/guest-tabs/{guest['id']}/context"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": guest["version"],
                "label": "",
                "current_table_id": other["id"],
                "seat_label": "",
                "present": True,
                "reason": "Gast wechselt an den ruhigeren Tisch.",
            },
        ),
        201,
    )
    assert await occupied(db_session, [site.table_id, other["id"]]) == {other["id"]}
    original = body(
        await client.get(
            site.path(f"/orders/{sent['children'][0]['order_id']}"), headers=site.headers
        )
    )
    assert original["table_id"] == site.table_id
    assert original["lines"] == sent["children"][0]["order"]["lines"]


async def test_legacy_open_receipt_still_blocks_its_original_table(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    await sent_order(client, site)
    assert await occupied(db_session, [site.table_id]) == {site.table_id}
    assert await occupied(db_session, [site.table_id], live=False) == set()
