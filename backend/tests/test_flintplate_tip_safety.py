"""Money conservation and explicitly approved, venue-specific tip attribution."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.admin.models import Customer
from app.gastro import tips
from app.gastro.models import Membership, Order, Shift, TipRun, Venue
from app.gastro.payer_tip_models import PayerTipEntry
from app.gastro.tip_models import TipTimeAttribution
from app.users.models import User
from app.worker.assignment_models import WorkerAssignment
from app.worker.time_models import TimeEntry
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order, serve

pytest_plugins = ["tests.test_flintplate"]

START = datetime(2026, 9, 12, 8, tzinfo=UTC)
PERIOD = {"period_start": "2026-09-12", "period_end": "2026-09-12"}


async def paid_tip(
    db: AsyncSession, venue_id: uuid.UUID, cents: int, recipient: uuid.UUID | None
) -> Order:
    order = Order(
        venue_id=venue_id,
        request_key=uuid.uuid4(),
        request_hash="0" * 64,
        number="TIP-" + uuid.uuid4().hex[:12],
        lines=[],
        total_cents=1000,
        subtotal_cents=1000,
        status="settled",
        paid_at=START,
        pos_requested=True,
        tip_cents=cents,
        tip_recipient_id=recipient,
    )
    db.add(order)
    await db.flush()
    return order


async def shift_for(
    db: AsyncSession,
    venue: Venue,
    worker: User,
    start: datetime = START,
    end: datetime = START + timedelta(hours=4),
    station: str = "Service",
) -> Shift:
    assignment = WorkerAssignment(
        worker_id=worker.id,
        tenant_id=venue.tenant_id,
        start_date=start.date(),
        end_date=end.date(),
        status="active",
    )
    db.add(assignment)
    await db.flush()
    shift = Shift(
        venue_id=venue.id,
        worker_id=worker.id,
        assignment_id=assignment.id,
        starts_at=start,
        ends_at=end,
        station=station,
        status="published",
    )
    db.add(shift)
    await db.flush()
    return shift


async def time_for(
    db: AsyncSession,
    venue: Venue,
    worker: User,
    start: datetime = START,
    end: datetime = START + timedelta(hours=4),
    pause: int = 0,
    status: str = "approved",
) -> TimeEntry:
    entry = TimeEntry(
        worker_id=worker.id,
        tenant_id=venue.tenant_id,
        clock_in=start.replace(tzinfo=None),
        clock_out=end.replace(tzinfo=None),
        entry_date=start.date(),
        break_minutes=pause,
        status=status,
    )
    db.add(entry)
    await db.flush()
    return entry


async def link(client: AsyncClient, site: Site, entry: TimeEntry, shift: Shift) -> dict:
    return body(
        await client.put(
            site.path(f"/tips/time-attributions/{entry.id}/{shift.id}"), headers=site.headers
        )
    )


@pytest.mark.asyncio
async def test_direct_remainder_survives_and_can_be_distributed_in_the_same_period(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    venue = await db_session.get(Venue, uuid.UUID(site.venue_id))
    assert venue is not None
    venue.tip_mode = "direct"
    assigned = await paid_tip(db_session, venue.id, 500, hr_workspace.worker.id)
    unassigned = await paid_tip(db_session, venue.id, 500, None)
    first = body(await client.post(site.path("/tips/runs"), headers=site.headers, json=PERIOD), 201)
    assert first["total_cents"] == 500 and first["orders"] == 1
    await db_session.refresh(assigned)
    await db_session.refresh(unassigned)
    assert assigned.tip_run_id == uuid.UUID(first["id"])
    assert unassigned.tip_run_id is None
    remaining = body(
        await client.post(site.path("/tips/preview"), headers=site.headers, json=PERIOD)
    )
    assert remaining["total_cents"] == remaining["open_cents"] == 500
    assert remaining["allocated_cents"] == 0
    assert "allocated_order_ids" not in remaining

    shift = await shift_for(db_session, venue, hr_workspace.worker)
    entry = await time_for(db_session, venue, hr_workspace.worker)
    await link(client, site, entry, shift)
    second = body(
        await client.post(site.path("/tips/runs"), headers=site.headers, json=PERIOD), 201
    )
    assert second["total_cents"] == 500 and second["orders"] == 1
    assert second["id"] != first["id"]
    after = body(await client.post(site.path("/tips/preview"), headers=site.headers, json=PERIOD))
    assert after["total_cents"] == after["open_cents"] == after["allocated_cents"] == 0
    assert first["total_cents"] + second["total_cents"] + after["open_cents"] == 1000
    assert (
        await client.post(site.path("/tips/runs"), headers=site.headers, json=PERIOD)
    ).status_code == 409


@pytest.mark.asyncio
async def test_missing_service_time_does_not_consume_partial_kitchen_pot(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    venue = await db_session.get(Venue, uuid.UUID(site.venue_id))
    assert venue is not None
    venue.tip_kitchen_bps = 3000
    order = await paid_tip(db_session, venue.id, 1000, None)
    shift = await shift_for(db_session, venue, hr_workspace.worker, station="Küche")
    entry = await time_for(db_session, venue, hr_workspace.worker)
    await link(client, site, entry, shift)
    preview = body(await client.post(site.path("/tips/preview"), headers=site.headers, json=PERIOD))
    assert preview["allocated_cents"] == 0 and preview["open_cents"] == 1000
    assert (
        await client.post(site.path("/tips/runs"), headers=site.headers, json=PERIOD)
    ).status_code == 409
    await db_session.refresh(order)
    assert order.tip_run_id is None


@pytest.mark.asyncio
async def test_only_explicit_approved_attribution_counts_and_corrections_require_reattribution(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    venue = await db_session.get(Venue, uuid.UUID(site.venue_id))
    assert venue is not None
    shift = await shift_for(db_session, venue, hr_workspace.worker)
    approved = await time_for(db_session, venue, hr_workspace.worker, pause=30)
    period = tips.Period.model_validate(PERIOD)
    assert not (await tips.worked_minutes(db_session, venue, period)).minutes
    await link(client, site, approved, shift)
    await link(client, site, approved, shift)
    assert (await tips.worked_minutes(db_session, venue, period)).minutes == {
        hr_workspace.worker.id: 210
    }
    links = list((await db_session.execute(select(TipTimeAttribution))).scalars())
    assert len(links) == 1
    for status in ("draft", "submitted", "rejected", "correction_requested"):
        rejected = await time_for(db_session, venue, hr_workspace.worker, status=status)
        response = await client.put(
            site.path(f"/tips/time-attributions/{rejected.id}/{shift.id}"), headers=site.headers
        )
        assert response.status_code == 409
    approved.break_minutes = 60
    await db_session.flush()
    assert not (await tips.worked_minutes(db_session, venue, period)).minutes
    await link(client, site, approved, shift)
    assert (await tips.worked_minutes(db_session, venue, period)).minutes == {
        hr_workspace.worker.id: 180
    }


@pytest.mark.asyncio
async def test_foreign_venue_time_and_overlapping_attribution_do_not_double_count(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    venue = await db_session.get(Venue, uuid.UUID(site.venue_id))
    assert venue is not None
    other = Venue(name="Other tips", tenant_id=venue.tenant_id)
    db_session.add(other)
    await db_session.flush()
    db_session.add(Membership(venue_id=other.id, user_id=hr_workspace.hr.id, role="manager"))
    db_session.add(Membership(venue_id=other.id, user_id=hr_workspace.worker.id, role="service"))
    own_shift = await shift_for(db_session, venue, hr_workspace.worker)
    other_shift = await shift_for(db_session, other, hr_workspace.worker)
    entry = await time_for(db_session, venue, hr_workspace.worker)
    other_site = Site(str(other.id), site.table_id, site.item_id, site.headers)
    await link(client, other_site, entry, other_shift)
    assert not (
        await tips.worked_minutes(db_session, venue, tips.Period.model_validate(PERIOD))
    ).minutes
    assert (
        await client.put(
            site.path(f"/tips/time-attributions/{entry.id}/{own_shift.id}"), headers=site.headers
        )
    ).status_code == 409
    second_entry = await time_for(db_session, venue, hr_workspace.worker)
    assert (
        await client.put(
            site.path(f"/tips/time-attributions/{second_entry.id}/{own_shift.id}"),
            headers=site.headers,
        )
    ).status_code == 409
    # A venue manager cannot attribute an entry owned by another tenant/person.
    foreign_entry = await time_for(db_session, venue, hr_workspace.other_worker)
    assert (
        await client.put(
            site.path(f"/tips/time-attributions/{foreign_entry.id}/{own_shift.id}"),
            headers=site.headers,
        )
    ).status_code == 404


@pytest.mark.parametrize("day", [date(2026, 3, 29), date(2026, 10, 25), date(2026, 9, 12)])
def test_pause_midnight_and_dst_boundaries_conserve_minutes(day: date) -> None:
    zone = ZoneInfo("Europe/Berlin")
    midnight = datetime.combine(day, datetime.min.time(), zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), zone).astimezone(UTC)
    clock_in, clock_out = midnight - timedelta(hours=2), end + timedelta(hours=2)
    entry = TimeEntry(clock_in=clock_in, clock_out=clock_out, status="approved", break_minutes=73)
    shift = Shift(starts_at=clock_in, ends_at=clock_out)
    parts = [
        tips.attributed_minutes(entry, shift, clock_in, midnight),
        tips.attributed_minutes(entry, shift, midnight, end),
        tips.attributed_minutes(entry, shift, end, clock_out),
    ]
    assert sum(parts) == entry.net_minutes
    assert all(value > 0 for value in parts)


@pytest.mark.asyncio
async def test_split_duties_keep_service_and_kitchen_minutes_separate(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    venue = await db_session.get(Venue, uuid.UUID(site.venue_id))
    assert venue is not None
    midway = START + timedelta(hours=2)
    first = await shift_for(db_session, venue, hr_workspace.worker, end=midway)
    second = await shift_for(db_session, venue, hr_workspace.worker, start=midway, station="Küche")
    entry = await time_for(db_session, venue, hr_workspace.worker, pause=60)
    await link(client, site, entry, first)
    await link(client, site, entry, second)
    weights = await tips.worked_minutes(db_session, venue, tips.Period.model_validate(PERIOD))
    assert weights.minutes[hr_workspace.worker.id] == 180
    assert weights.groups["service"][hr_workspace.worker.id] == 90
    assert weights.groups["kitchen"][hr_workspace.worker.id] == 90


@pytest.mark.asyncio
async def test_staff_cannot_change_tip_after_handoff(client: AsyncClient, site: Site) -> None:
    order = await serve(client, site, await sent_order(client, site))
    handed = body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    response = await client.post(
        site.path(f"/orders/{order['id']}/tip"),
        headers=site.headers,
        json={"version": handed["version"], "tip_cents": 200},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_runs_consume_a_source_only_once(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(db_session.bind, AsyncConnection)
    sessions = async_sessionmaker(db_session.bind.engine, expire_on_commit=False, autoflush=False)
    async with sessions() as seed:
        tenant = Customer(
            name="Concurrent tip source", slug="tip-race-" + uuid.uuid4().hex, status="active"
        )
        seed.add(tenant)
        await seed.flush()
        manager = User(
            email=f"tip-race-{uuid.uuid4().hex}@example.com",
            hashed_password="unused",
            full_name="Tip manager",
            role="recruiter",
            tenant_id=tenant.id,
        )
        seed.add(manager)
        await seed.flush()
        venue = Venue(name="Concurrent tip source", tenant_id=tenant.id, tip_mode="direct")
        seed.add(venue)
        await seed.flush()
        seed.add(Membership(venue_id=venue.id, user_id=manager.id, role="manager"))
        await paid_tip(seed, venue.id, 500, manager.id)
        await seed.commit()
        venue_id, manager_id = venue.id, manager.id

    first_entered, release = asyncio.Event(), asyncio.Event()
    original = tips.distribute

    async def paused_distribution(
        db: AsyncSession,
        venue: Venue,
        data: tips.Period,
        *,
        orders: list[Order] | None = None,
        payer_tips: list[tuple[PayerTipEntry, int]] | None = None,
    ) -> tips.Distribution:
        first_entered.set()
        await release.wait()
        return await original(db, venue, data, orders=orders, payer_tips=payer_tips)

    monkeypatch.setattr(tips, "distribute", paused_distribution)

    async def run_once() -> int:
        async with sessions() as session:
            actor = await session.get(User, manager_id)
            assert actor is not None
            try:
                await tips.confirm(venue_id, tips.RunInput.model_validate(PERIOD), actor, session)
                await session.commit()
                return 201
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    first = asyncio.create_task(run_once())
    await asyncio.wait_for(first_entered.wait(), 5)
    second = asyncio.create_task(run_once())
    release.set()
    assert sorted(await asyncio.wait_for(asyncio.gather(first, second), 10)) == [201, 409]
    async with sessions() as verify:
        runs = list(
            (await verify.execute(select(TipRun).where(TipRun.venue_id == venue_id))).scalars()
        )
        assert len(runs) == 1 and runs[0].total_cents == 500
