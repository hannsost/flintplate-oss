from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.models import Membership
from app.security import create_access_token
from app.users.models import User
from app.worker.models import ALL_MODULES, WorkerSettings
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, pos_device
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]

# Payments are stamped with the real clock, so the fixtures anchor to now and the
# period spans yesterday and today in the venue timezone.
ANCHOR = datetime.now(UTC) - timedelta(hours=1)
BERLIN = ZoneInfo("Europe/Berlin")
PERIOD = {
    "period_start": (ANCHOR.astimezone(BERLIN) - timedelta(days=1)).date().isoformat(),
    "period_end": datetime.now(BERLIN).date().isoformat(),
}


def base(site: Site) -> str:
    return f"/guest/v1/{site.venue_id}"


async def open_guest_app(client: AsyncClient, site: Site, **flags: object) -> None:
    body(
        await client.put(
            site.path("/guest-app"), headers=site.headers, json={"enabled": True, **flags}
        )
    )


async def staff_member(
    client: AsyncClient, site: Site, db: AsyncSession, workspace: HRWorkspace, role: str, name: str
) -> tuple[str, dict[str, str]]:
    person = User(
        email=f"tip-{uuid.uuid4().hex}@example.com",
        hashed_password="unused",
        full_name=name,
        role="worker",
        tenant_id=workspace.hr.tenant_id,
    )
    db.add(person)
    await db.flush()
    db.add_all(
        [
            WorkerSettings(
                user_id=person.id,
                tenant_id=person.tenant_id,
                is_active=True,
                date_of_birth=date(1990, 1, 1),
                max_weekly_hours=40,
                active_modules=dict(ALL_MODULES),
            ),
            Membership(
                venue_id=uuid.UUID(site.venue_id),
                user_id=person.id,
                role=role,
                stations=["kitchen"] if role == "kitchen" else ["service"],
                competence=3,
            ),
        ]
    )
    await db.flush()
    return str(person.id), auth_headers(create_access_token({"sub": person.email}))


async def published_shift(
    client: AsyncClient, site: Site, worker_id: str, station: str, hours: int = 6
) -> None:
    start = ANCHOR - timedelta(hours=hours)
    shift = body(
        await client.post(
            site.path("/shifts"),
            headers=site.headers,
            json={
                "worker_id": worker_id,
                "station": station,
                "starts_at": start.isoformat(),
                "ends_at": ANCHOR.isoformat(),
                "break_minutes": 30,
            },
        ),
        201,
    )
    body(
        await client.post(
            site.path(f"/shifts/{shift['id']}/status"),
            headers=site.headers,
            json={"version": shift["version"], "status": "published"},
        )
    )


async def recorded_time(
    client: AsyncClient, headers: dict[str, str], hours: int, site: Site
) -> None:
    start = ANCHOR - timedelta(hours=hours)
    entry = body(
        await client.post("/worker/time", headers=headers, json={"clock_in": start.isoformat()}),
        201,
    )
    body(
        await client.patch(
            f"/worker/time/{entry['id']}",
            headers=headers,
            json={"clock_out": ANCHOR.isoformat(), "break_minutes": 0},
        )
    )
    body(await client.post(f"/worker/time/{entry['id']}/submit", headers=headers))
    body(
        await client.post(
            f"/zeitarbeit/time-entries/{entry['id']}/decision",
            headers=site.headers,
            json={"action": "approve"},
        )
    )
    candidates = body(
        await client.get(site.path("/tips/time-attributions"), headers=site.headers, params=PERIOD)
    )
    for candidate in candidates:
        if candidate["entry_id"] == entry["id"]:
            body(
                await client.put(
                    site.path(f"/tips/time-attributions/{entry['id']}/{candidate['shift_id']}"),
                    headers=site.headers,
                )
            )


async def served_takeaway(client: AsyncClient, site: Site, headers: dict[str, str]) -> dict:
    """The guest view carries no version, so the staff view drives the transitions."""
    created = body(
        await client.post(
            base(site) + "/orders",
            headers=headers,
            json=site.order(table_id=None, fulfillment="takeaway"),
        ),
        201,
    )
    rows = body(await client.get(site.path("/orders?include_closed=true"), headers=site.headers))
    order = next(row for row in rows if row["id"] == created["id"])
    for status in ("preparing", "ready", "served"):
        order = body(
            await client.post(
                site.path(f"/orders/{order['id']}/status"),
                headers=site.headers,
                json={"version": order["version"], "status": status},
            )
        )
    return order


async def settle(client: AsyncClient, site: Site, order_id: str, amount: int) -> dict:
    pos = await pos_device(client, site)
    return body(
        await client.post(
            "/device/v1/payments",
            headers={"X-FlintPlate-Key": pos["token"]},
            json={
                "request_key": str(uuid.uuid4()),
                "order_id": order_id,
                "amount_cents": amount,
                "currency": "EUR",
                "reference": f"synthetic-{uuid.uuid4().hex[:8]}",
            },
        )
    )


@pytest.mark.asyncio
async def test_table_order_needs_the_venue_to_allow_it(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site)
    guest = hr_workspace.headers("other_worker")

    response = await client.post(base(site) + "/orders", headers=guest, json=site.order())

    assert response.status_code == 422
    assert "Service" in response.json()["detail"]


@pytest.mark.asyncio
async def test_open_table_order_still_needs_the_guest_at_that_table(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site, guest_table_orders=True)
    guest = hr_workspace.headers("other_worker")

    response = await client.post(base(site) + "/orders", headers=guest, json=site.order())

    assert response.status_code == 403
    assert "Service" in response.json()["detail"]


@pytest.mark.asyncio
async def test_seated_guest_orders_to_the_own_table(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site, guest_table_orders=True)
    guest = hr_workspace.headers("other_worker")
    start = datetime.now(UTC) + timedelta(days=1)
    reservation = body(
        await client.post(
            base(site) + "/reservations",
            headers=guest,
            json={
                "table_id": site.table_id,
                "guest_name": "Gast am Tisch",
                "guests": 2,
                "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=2)).isoformat(),
            },
        ),
        201,
    )
    body(
        await client.post(
            site.path(f"/reservations/{reservation['id']}/status"),
            headers=site.headers,
            json={"version": reservation["version"], "status": "seated"},
        )
    )

    order = body(await client.post(base(site) + "/orders", headers=guest, json=site.order()), 201)

    assert order["table_id"] == site.table_id
    assert order["fulfillment"] == "dine_in"


@pytest.mark.asyncio
async def test_open_tables_drop_the_reservation_requirement(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site, guest_table_orders=True, guest_open_tables=True)
    guest = hr_workspace.headers("other_worker")

    order = body(await client.post(base(site) + "/orders", headers=guest, json=site.order()), 201)

    assert order["table_id"] == site.table_id


@pytest.mark.asyncio
async def test_guest_tip_changes_what_the_till_has_to_collect(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site)
    guest = hr_workspace.headers("other_worker")
    order = await served_takeaway(client, site, guest)

    requested = body(
        await client.post(
            base(site) + f"/orders/{order['id']}/payment-request",
            headers=guest,
            json={"tip_cents": 250},
        )
    )
    assert requested["tip_cents"] == 250
    assert requested["pos_requested"] is True

    too_much = await client.post(
        "/device/v1/payments",
        headers={"X-FlintPlate-Key": (await pos_device(client, site))["token"]},
        json={
            "request_key": str(uuid.uuid4()),
            "order_id": order["id"],
            "amount_cents": order["total_cents"] + 251,
            "currency": "EUR",
            "reference": "ohne-trinkgeld",
        },
    )
    assert too_much.status_code == 422

    settled = await settle(client, site, order["id"], order["total_cents"] + 250)
    assert settled["status"] == "settled"
    assert settled["tip_cents"] == 250


@pytest.mark.asyncio
async def test_staff_tip_needs_a_person_of_this_venue(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site)
    guest = hr_workspace.headers("other_worker")
    order = await served_takeaway(client, site, guest)

    stranger = await client.post(
        site.path(f"/orders/{order['id']}/tip"),
        headers=site.headers,
        json={"version": order["version"], "tip_cents": 300, "recipient_id": str(uuid.uuid4())},
    )
    assert stranger.status_code == 404

    updated = body(
        await client.post(
            site.path(f"/orders/{order['id']}/tip"),
            headers=site.headers,
            json={
                "version": order["version"],
                "tip_cents": 300,
                "recipient_id": str(hr_workspace.worker.id),
            },
        )
    )
    assert updated["tip_cents"] == 300
    assert updated["tip_recipient_id"] == str(hr_workspace.worker.id)


@pytest.mark.asyncio
async def test_pool_splits_by_recorded_minutes_and_adds_up(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site)
    long_id, long_headers = await staff_member(
        client, site, db_session, hr_workspace, "service", "Lange Schicht"
    )
    short_id, short_headers = await staff_member(
        client, site, db_session, hr_workspace, "service", "Kurze Schicht"
    )
    await published_shift(client, site, long_id, "Service", hours=6)
    terrace = body(
        await client.post(
            site.path("/stations"),
            headers=site.headers,
            json={"request_key": str(uuid.uuid4()), "name": "Terrasse", "kind": "service"},
        ),
        201,
    )
    await published_shift(client, site, short_id, terrace["code"], hours=3)
    await recorded_time(client, long_headers, 6, site)
    await recorded_time(client, short_headers, 3, site)
    guest = hr_workspace.headers("other_worker")
    order = await served_takeaway(client, site, guest)
    body(
        await client.post(
            base(site) + f"/orders/{order['id']}/payment-request",
            headers=guest,
            json={"tip_cents": 901},
        )
    )
    await settle(client, site, order["id"], order["total_cents"] + 901)

    result = body(
        await client.post(
            site.path("/tips/preview"),
            headers=site.headers,
            json=PERIOD,
        )
    )

    assert result["total_cents"] == 901
    assert sum(share["share_cents"] for share in result["shares"]) == 901
    shares = {share["worker_id"]: share for share in result["shares"]}
    assert shares[long_id]["share_cents"] > shares[short_id]["share_cents"]
    assert shares[long_id]["minutes"] == 360
    assert "freigegebene, dienstbezogene Minuten" in shares[long_id]["reason"]


@pytest.mark.asyncio
async def test_kitchen_share_stays_with_service_without_kitchen_time(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site, tip_kitchen_bps=3000)
    worker_id, worker_headers = await staff_member(
        client, site, db_session, hr_workspace, "service", "Nur Service"
    )
    await published_shift(client, site, worker_id, "Service", hours=5)
    await recorded_time(client, worker_headers, 5, site)
    guest = hr_workspace.headers("other_worker")
    order = await served_takeaway(client, site, guest)
    body(
        await client.post(
            base(site) + f"/orders/{order['id']}/payment-request",
            headers=guest,
            json={"tip_cents": 1000},
        )
    )
    await settle(client, site, order["id"], order["total_cents"] + 1000)

    result = body(
        await client.post(
            site.path("/tips/preview"),
            headers=site.headers,
            json=PERIOD,
        )
    )

    assert sum(share["share_cents"] for share in result["shares"]) == 1000
    assert any("Küchenanteil" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_a_confirmed_run_is_final_for_its_period(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site)
    worker_id, worker_headers = await staff_member(
        client, site, db_session, hr_workspace, "service", "Abrechnung"
    )
    await published_shift(client, site, worker_id, "Service", hours=4)
    await recorded_time(client, worker_headers, 4, site)
    guest = hr_workspace.headers("other_worker")
    order = await served_takeaway(client, site, guest)
    body(
        await client.post(
            base(site) + f"/orders/{order['id']}/payment-request",
            headers=guest,
            json={"tip_cents": 500},
        )
    )
    await settle(client, site, order["id"], order["total_cents"] + 500)
    period = PERIOD

    run = body(await client.post(site.path("/tips/runs"), headers=site.headers, json=period), 201)
    assert run["total_cents"] == 500
    assert run["orders"] == 1

    again = await client.post(site.path("/tips/runs"), headers=site.headers, json=period)
    assert again.status_code == 409

    after = body(await client.post(site.path("/tips/preview"), headers=site.headers, json=period))
    assert after["total_cents"] == 0
    assert any("kein bestätigtes Trinkgeld" in note for note in after["notes"])

    history = body(await client.get(site.path("/tips/runs"), headers=site.headers))
    assert history[0]["shares"][0]["share_cents"] == 500


@pytest.mark.asyncio
async def test_direct_mode_pays_the_person_on_the_bill(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site, tip_mode="direct")
    worker_id, worker_headers = await staff_member(
        client, site, db_session, hr_workspace, "service", "Bedienung"
    )
    await published_shift(client, site, worker_id, "Service", hours=4)
    await recorded_time(client, worker_headers, 4, site)
    guest = hr_workspace.headers("other_worker")
    order = await served_takeaway(client, site, guest)
    tipped = body(
        await client.post(
            site.path(f"/orders/{order['id']}/tip"),
            headers=site.headers,
            json={"version": order["version"], "tip_cents": 700, "recipient_id": worker_id},
        )
    )
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": tipped["version"]},
        )
    )
    await settle(client, site, order["id"], order["total_cents"] + 700)

    result = body(
        await client.post(
            site.path("/tips/preview"),
            headers=site.headers,
            json=PERIOD,
        )
    )

    assert result["mode"] == "direct"
    named = next(share for share in result["shares"] if share["worker_id"] == worker_id)
    assert named["share_cents"] == 700
    assert "Direkt" in named["reason"]


@pytest.mark.asyncio
async def test_guest_takes_an_order_back_only_before_the_kitchen_starts(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await open_guest_app(client, site)
    guest = hr_workspace.headers("other_worker")
    created = body(
        await client.post(
            base(site) + "/orders",
            headers=guest,
            json=site.order(table_id=None, fulfillment="takeaway"),
        ),
        201,
    )

    assert (
        await client.delete(base(site) + f"/orders/{created['id']}", headers=guest)
    ).status_code == 204
    assert (
        await client.delete(base(site) + f"/orders/{created['id']}", headers=guest)
    ).status_code == 204

    running = await served_takeaway(client, site, guest)
    late = await client.delete(base(site) + f"/orders/{running['id']}", headers=guest)
    assert late.status_code == 409
    assert "Service" in late.json()["detail"]
