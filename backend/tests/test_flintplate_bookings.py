"""Group occupancy, waitlist replay, extension conflicts and concurrent placement."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.gastro import bookings
from app.gastro.booking_models import ReservationResource, WaitlistEntry
from app.gastro.booking_schemas import GroupInput
from app.gastro.models import DiningTable, Membership, Reservation, Venue
from app.users.models import User
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order
from tests.test_flintplate_seating import propose

pytest_plugins = ["tests.test_flintplate"]


def request(site: Site, **changes: object) -> dict:
    start = datetime.now(UTC) + timedelta(hours=1)
    return {
        "request_key": str(uuid.uuid4()),
        "table_ids": [site.table_id],
        "guest_name": "Reservation fixture",
        "guests": 2,
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(),
        **changes,
    }


async def pair(client: AsyncClient, site: Site) -> list[str]:
    second = body(
        await client.post(
            site.path("/tables"),
            headers=site.headers,
            json={"name": "Neighbour table", "seats": 4, "combinable_with": [site.table_id]},
        ),
        201,
    )
    return [site.table_id, second["id"]]


async def test_group_is_one_booking_and_every_resource_blocks_legacy_and_guest_paths(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    ids = await pair(client, site)
    payload = request(site, table_ids=ids, guests=6)
    first = body(
        await client.post(site.path("/reservation-groups"), headers=site.headers, json=payload), 201
    )
    replay = body(
        await client.post(site.path("/reservation-groups"), headers=site.headers, json=payload), 201
    )
    assert first == replay and first["table_ids"] == ids
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(Reservation)
            .where(Reservation.venue_id == uuid.UUID(site.venue_id))
        )
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ReservationResource)
            .where(ReservationResource.reservation_id == uuid.UUID(first["id"]))
        )
        == 2
    )
    assert (
        await client.post(
            site.path("/reservation-groups"),
            headers=site.headers,
            json={**payload, "guests": 7},
        )
    ).status_code == 409
    for table_id in ids:
        assert (
            await client.post(
                site.path("/reservations"),
                headers=site.headers,
                json={
                    "table_id": table_id,
                    "guest_name": "Conflict",
                    "guests": 2,
                    "starts_at": payload["starts_at"],
                    "ends_at": payload["ends_at"],
                },
            )
        ).status_code == 409
    body(await client.put(site.path("/guest-app"), headers=site.headers, json={"enabled": True}))
    occupied = body(
        await client.get(
            f"/guest/v1/{site.venue_id}/occupied",
            params={"start": payload["starts_at"], "end": payload["ends_at"]},
        )
    )
    assert {slot["table_id"] for slot in occupied} == set(ids)
    board = body(await client.get(site.path("/reservations/board"), headers=site.headers))
    assert len(board["reservations"]) == 1 and board["reservations"][0]["table_ids"] == ids


async def test_waitlist_seat_replay_claims_one_group_and_cancelled_waiter_cannot_be_seated(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    add = {
        "request_key": str(uuid.uuid4()),
        "guest_name": "Waiting fixture",
        "guests": 2,
        "note": "Inside",
    }
    waiter = body(await client.post(site.path("/waitlist"), headers=site.headers, json=add), 201)
    assert (
        body(await client.post(site.path("/waitlist"), headers=site.headers, json=add), 201)
        == waiter
    )
    assert waiter["reservation_id"] is None
    seat = {
        "request_key": str(uuid.uuid4()),
        "version": waiter["version"],
        "table_ids": [site.table_id],
        "ends_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    row = body(
        await client.post(
            site.path(f"/waitlist/{waiter['id']}/seat"), headers=site.headers, json=seat
        ),
        201,
    )
    assert row["source"] == "waitlist" and row["status"] == "seated" and row["checked_in_at"]
    assert (
        body(
            await client.post(
                site.path(f"/waitlist/{waiter['id']}/seat"), headers=site.headers, json=seat
            ),
            201,
        )
        == row
    )
    stored = await db_session.get(WaitlistEntry, uuid.UUID(waiter["id"]))
    assert stored is not None and str(stored.reservation_id) == row["id"] and stored.version == 2
    assert (
        body(await client.get(site.path("/reservations/board"), headers=site.headers))["waitlist"]
        == []
    )
    other = body(
        await client.post(
            site.path("/waitlist"),
            headers=site.headers,
            json={**add, "request_key": str(uuid.uuid4())},
        ),
        201,
    )
    cancel = {"request_key": str(uuid.uuid4()), "version": 1, "status": "cancelled"}
    body(
        await client.post(
            site.path(f"/waitlist/{other['id']}/state"), headers=site.headers, json=cancel
        )
    )
    assert (
        await client.post(
            site.path(f"/waitlist/{other['id']}/seat"),
            headers=site.headers,
            json={**seat, "request_key": str(uuid.uuid4()), "version": 2},
        )
    ).status_code == 409


async def test_combination_proposal_acceptance_creates_one_group_and_replays_safely(
    client: AsyncClient, site: Site
) -> None:
    ids = await pair(client, site)
    proposal = await propose(client, site, guests=6)
    option = proposal["options"][0]
    payload = {"version": 1, "option_key": option["key"], "guest_name": "Shared party"}
    path = site.path(f"/decisions/{proposal['decision_id']}/accept")
    accepted = body(await client.post(path, headers=site.headers, json=payload), 201)
    assert len(accepted) == 1
    assert body(await client.post(path, headers=site.headers, json=payload), 201) == accepted
    board = body(await client.get(site.path("/reservations/board"), headers=site.headers))
    group = next(row for row in board["reservations"] if row["id"] == accepted[0])
    assert set(group["table_ids"]) == set(ids) and group["guests"] == 6


async def test_overdue_seated_remains_visible_and_blocks_admission_but_not_future_planning(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    walkin = body(
        await client.post(
            site.path("/reservation-groups"),
            headers=site.headers,
            json=request(site, source="walk_in"),
        ),
        201,
    )
    row = await db_session.get(Reservation, uuid.UUID(walkin["id"]))
    assert row is not None
    row.starts_at = datetime.now(UTC) - timedelta(days=3, hours=1)
    row.ends_at = row.starts_at + timedelta(hours=1)
    await db_session.flush()
    board = body(await client.get(site.path("/reservations/board"), headers=site.headers))
    assert any(item["id"] == walkin["id"] for item in board["reservations"])
    assert (
        await client.post(
            site.path("/reservation-groups"),
            headers=site.headers,
            json=request(site, source="walk_in"),
        )
    ).status_code == 409
    future_start = datetime.now(UTC) + timedelta(days=14)
    planned = body(
        await client.post(
            site.path("/reservation-groups"),
            headers=site.headers,
            json=request(
                site,
                starts_at=future_start.isoformat(),
                ends_at=(future_start + timedelta(hours=1)).isoformat(),
            ),
        ),
        201,
    )
    assert (
        await client.post(
            site.path(f"/reservation-groups/{planned['id']}/state"),
            headers=site.headers,
            json={"request_key": str(uuid.uuid4()), "version": 1, "status": "seated"},
        )
    ).status_code == 409


async def test_extension_checks_every_link_and_no_show_is_explicit_after_start(
    client: AsyncClient, site: Site
) -> None:
    ids = await pair(client, site)
    original = request(site, table_ids=ids, guests=6)
    group = body(
        await client.post(site.path("/reservation-groups"), headers=site.headers, json=original),
        201,
    )
    end = datetime.fromisoformat(group["ends_at"])
    body(
        await client.post(
            site.path("/reservations"),
            headers=site.headers,
            json={
                "table_id": ids[1],
                "guest_name": "Next group",
                "guests": 2,
                "starts_at": end.isoformat(),
                "ends_at": (end + timedelta(hours=1)).isoformat(),
            },
        ),
        201,
    )
    extension = {
        "request_key": str(uuid.uuid4()),
        "version": 1,
        "ends_at": (end + timedelta(minutes=30)).isoformat(),
        "reason": "Guests stay longer",
    }
    assert (
        await client.post(
            site.path(f"/reservation-groups/{group['id']}/extend"),
            headers=site.headers,
            json=extension,
        )
    ).status_code == 409
    state = {"request_key": str(uuid.uuid4()), "version": 1, "status": "no_show"}
    assert (
        await client.post(
            site.path(f"/reservation-groups/{group['id']}/state"), headers=site.headers, json=state
        )
    ).status_code == 409
    past_start = datetime.now(UTC) - timedelta(hours=2)
    past = body(
        await client.post(
            site.path("/reservation-groups"),
            headers=site.headers,
            json=request(
                site,
                starts_at=past_start.isoformat(),
                ends_at=(past_start + timedelta(hours=1)).isoformat(),
            ),
        ),
        201,
    )
    data = {**state, "request_key": str(uuid.uuid4())}
    missed = body(
        await client.post(
            site.path(f"/reservation-groups/{past['id']}/state"), headers=site.headers, json=data
        )
    )
    assert missed["status"] == "no_show" and missed["closed_at"]
    assert (
        body(
            await client.post(
                site.path(f"/reservation-groups/{past['id']}/state"),
                headers=site.headers,
                json=data,
            )
        )
        == missed
    )


async def test_open_table_bill_blocks_walkin_and_other_tenant_cannot_read_board(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await sent_order(client, site)
    assert (
        await client.post(
            site.path("/reservation-groups"),
            headers=site.headers,
            json=request(site, source="walk_in"),
        )
    ).status_code == 409
    assert (
        await client.get(site.path("/reservations/board"), headers=hr_workspace.headers("other_hr"))
    ).status_code == 404
    assert (
        await client.post(
            site.path("/waitlist"),
            headers=hr_workspace.headers("other_hr"),
            json={"request_key": str(uuid.uuid4()), "guest_name": "Foreign", "guests": 2},
        )
    ).status_code == 404


async def test_seated_extension_keeps_own_open_bill_and_replay_does_not_shrink_later_extension(
    client: AsyncClient, site: Site
) -> None:
    row = body(
        await client.post(
            site.path("/reservation-groups"),
            headers=site.headers,
            json=request(site, source="walk_in"),
        ),
        201,
    )
    await sent_order(client, site)
    original_end = datetime.fromisoformat(row["ends_at"])
    first = {
        "request_key": str(uuid.uuid4()),
        "version": row["version"],
        "ends_at": (original_end + timedelta(minutes=30)).isoformat(),
        "reason": "Guests stay for dessert",
    }
    path = site.path(f"/reservation-groups/{row['id']}/extend")
    extended = body(await client.post(path, headers=site.headers, json=first))
    assert extended["version"] == 2 and extended["status"] == "seated"
    later = {
        **first,
        "request_key": str(uuid.uuid4()),
        "version": 2,
        "ends_at": (original_end + timedelta(minutes=60)).isoformat(),
    }
    latest = body(await client.post(path, headers=site.headers, json=later))
    assert latest["version"] == 3
    assert body(await client.post(path, headers=site.headers, json=first)) == extended
    current = body(await client.get(site.path("/reservations/board"), headers=site.headers))
    assert current["reservations"][0]["ends_at"] == latest["ends_at"]


async def test_concurrent_group_retries_and_reversed_resource_order_do_not_double_book() -> None:
    # Independent committed fixtures live only in this run's disposable test schema.
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Booking concurrency", slug="booking-" + uuid.uuid4().hex, status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email="booking-" + uuid.uuid4().hex + "@example.com",
            hashed_password="unused",
            full_name="Booking operator",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Booking concurrency", tenant_id=tenant.id)
        db.add_all([user, venue])
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
        first = DiningTable(venue_id=venue.id, name="First", seats=4)
        second = DiningTable(venue_id=venue.id, name="Second", seats=4)
        db.add_all([first, second])
        await db.flush()
        first.combinable_with = [str(second.id)]
        await db.commit()
        venue_id, actor_id, ids = venue.id, user.id, [first.id, second.id]
    start = datetime.now(UTC) + timedelta(days=1)
    payload = GroupInput(
        request_key=uuid.uuid4(),
        table_ids=ids,
        guest_name="Concurrent group",
        guests=6,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )

    async def create(data: GroupInput) -> tuple[int, str]:
        async with TestSessionLocal() as db:
            actor = await db.get(User, actor_id)
            assert actor is not None
            try:
                result = await bookings.create(venue_id, data, actor, db)
                await db.commit()
                return 201, str(result.id)
            except HTTPException as error:
                await db.rollback()
                return error.status_code, ""

    replies = await asyncio.wait_for(asyncio.gather(create(payload), create(payload)), 10)
    assert replies[0] == replies[1] and replies[0][0] == 201
    later = payload.model_copy(
        update={
            "request_key": uuid.uuid4(),
            "starts_at": start + timedelta(hours=2),
            "ends_at": start + timedelta(hours=3),
        }
    )
    reverse = later.model_copy(
        update={"request_key": uuid.uuid4(), "table_ids": list(reversed(ids))}
    )
    competing = await asyncio.wait_for(asyncio.gather(create(later), create(reverse)), 10)
    assert sorted(status for status, _ in competing) == [201, 409]
