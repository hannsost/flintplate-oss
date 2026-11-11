"""Read-side bounds, historical discovery and stable journal export snapshots."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.models import Event, Order
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order

pytest_plugins = ["tests.test_flintplate"]


@pytest.mark.asyncio
async def test_history_paginates_closed_bons_with_tied_timestamps(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    orders = [await sent_order(client, site) for _ in range(4)]
    ids = [uuid.UUID(order["id"]) for order in orders]
    await db_session.execute(
        update(Order)
        .where(Order.id.in_(ids))
        .values(created_at=datetime(2026, 9, 1, 10, tzinfo=UTC), status="cancelled")
    )
    await db_session.flush()
    first_response = await client.get(site.path("/order-history?limit=2"), headers=site.headers)
    first = body(first_response)
    assert first_response.headers["cache-control"] == "no-store"
    assert first["has_more"] is True
    assert all(order["status"] == "cancelled" for order in first["items"])
    second = body(
        await client.get(
            site.path(f"/order-history?limit=2&before={first['next_before']}"),
            headers=site.headers,
        )
    )
    assert second["has_more"] is False
    assert second["next_before"] is None
    found = [order["id"] for order in first["items"] + second["items"]]
    assert found == sorted((str(entry) for entry in ids), reverse=True)
    assert len(set(found)) == 4
    detail = body(await client.get(site.path(f"/orders/{found[-1]}"), headers=site.headers))
    assert detail["id"] == found[-1] and detail["status"] == "cancelled"


@pytest.mark.asyncio
async def test_history_uses_local_day_boundaries_and_literal_search(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    orders = [await sent_order(client, site) for _ in range(4)]
    # Berlin's DST fallback is a 25-hour day: both repeated 02:30 times belong to it.
    instants = [
        datetime(2026, 10, 24, 21, 59, 59, tzinfo=UTC),
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 23, tzinfo=UTC),
    ]
    for order, instant in zip(orders, instants, strict=True):
        await db_session.execute(
            update(Order).where(Order.id == uuid.UUID(order["id"])).values(created_at=instant)
        )
    await db_session.flush()
    page = body(await client.get(site.path("/order-history?day=2026-10-25"), headers=site.headers))
    assert {item["id"] for item in page["items"]} == {orders[1]["id"], orders[2]["id"]}
    exact = body(
        await client.get(
            site.path("/order-history"), headers=site.headers, params={"q": orders[1]["number"]}
        )
    )
    assert [item["id"] for item in exact["items"]] == [orders[1]["id"]]
    wildcard = body(
        await client.get(site.path("/order-history"), headers=site.headers, params={"q": "%_"})
    )
    assert wildcard["items"] == []
    other_table = body(
        await client.get(site.path(f"/order-history?table_id={uuid.uuid4()}"), headers=site.headers)
    )
    assert other_table["items"] == []


@pytest.mark.asyncio
async def test_history_and_audit_enforce_roles_scope_and_bounds(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    order = await sent_order(client, site)
    assert (
        await client.get(site.path("/order-history"), headers=hr_workspace.headers("worker"))
    ).status_code == 200
    assert (
        await client.get(site.path("/audit-events"), headers=hr_workspace.headers("worker"))
    ).status_code == 403
    assert (
        await client.get(
            site.path(f"/orders/{order['id']}"), headers=hr_workspace.headers("other_hr")
        )
    ).status_code == 404
    assert (
        await client.get(site.path(f"/orders/{uuid.uuid4()}"), headers=site.headers)
    ).status_code == 404
    for path in ("/order-history", "/audit-events"):
        assert (
            await client.get(site.path(path), headers=hr_workspace.headers("other_hr"))
        ).status_code == 404
        assert (
            await client.get(site.path(path), headers=site.headers, params={"limit": 0})
        ).status_code == 422
    assert (
        await client.get(site.path("/order-history?limit=101"), headers=site.headers)
    ).status_code == 422
    assert (
        await client.get(site.path("/audit-events?limit=501"), headers=site.headers)
    ).status_code == 422
    assert (
        await client.get(site.path(f"/order-history?before={uuid.uuid4()}"), headers=site.headers)
    ).status_code == 404
    assert (
        await client.get(site.path("/audit-events?through=0&after=1"), headers=site.headers)
    ).status_code == 422
    assert (
        await client.get(site.path("/order-history?day=9999-12-31"), headers=site.headers)
    ).status_code == 422


@pytest.mark.asyncio
async def test_journal_freezes_end_and_preserves_chain_evidence_across_pages(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    order = await sent_order(client, site)
    expected = list(
        (
            await db_session.execute(
                select(Event.sequence)
                .where(Event.venue_id == uuid.UUID(site.venue_id))
                .order_by(Event.sequence)
            )
        ).scalars()
    )
    first = body(await client.get(site.path("/audit-events?limit=2"), headers=site.headers))
    upper = first["through_sequence"]
    assert upper == expected[-1]
    # A new event after export starts must not extend that export indefinitely.
    svc.event(
        db_session, uuid.UUID(site.venue_id), "history.export_test", uuid.UUID(order["id"]), {}
    )
    await db_session.flush()
    page = first
    items = list(page["items"])
    while page["has_more"]:
        previous = page["next_after"]
        page = body(
            await client.get(
                site.path(f"/audit-events?limit=2&after={previous}&through={upper}"),
                headers=site.headers,
            )
        )
        assert page["through_sequence"] == upper
        assert page["next_after"] > previous
        items.extend(page["items"])
    assert [item["sequence"] for item in items] == expected
    assert all(
        {"canonical_payload", "event_hash", "previous_hash", "audit_sequence"} <= item.keys()
        for item in items
    )
    empty = body(
        await client.get(
            site.path(f"/audit-events?after={upper}&through={upper}"), headers=site.headers
        )
    )
    assert empty["items"] == [] and empty["has_more"] is False
    assert empty["next_after"] == upper
    new = body(await client.get(site.path("/audit-events"), headers=site.headers))
    assert new["through_sequence"] > upper
