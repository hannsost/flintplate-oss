"""Actual cost evidence, unchanged payroll attribution, UTC/DST and money conservation."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.gastro import labour
from app.gastro.labour_models import LabourRateRevision
from app.gastro.labour_schemas import LabourRevisionInput
from app.gastro.labour_service import labour_summary
from app.gastro.models import Membership, Venue
from app.gastro.tip_models import TipTimeAttribution
from app.gastro.tips import time_hashes
from app.users.models import User
from app.worker.models import WorkerSettings
from tests.conftest import TestSessionLocal, test_engine
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.test_flintplate_tip_safety import START, link, shift_for, time_for

pytest_plugins = ["tests.test_flintplate"]


def period(start=START, end=None, hourly=1200, markup=0):
    return {
        "valid_from": start.isoformat(),
        "valid_until": end.isoformat() if end else None,
        "hourly_cents": hourly,
        "employer_markup_bps": markup,
        "source_reference": "Synthetic payroll calculation source",
    }


def revision(periods=None, **changes):
    return {
        "request_key": str(uuid.uuid4()),
        "version": 0,
        "reason": "Documented synthetic calculation basis",
        "source_reference": "Synthetic document 080",
        "periods": periods if periods is not None else [period()],
        **changes,
    }


async def save(client, site, worker_id, data=None):
    return body(
        await client.post(
            site.path(f"/labour-rates/{worker_id}"), headers=site.headers, json=data or revision()
        ),
        201,
    )


async def approved_work(
    client, site, db, workspace, start=START, end=START + timedelta(hours=4), pause=30
):
    venue = await db.get(Venue, uuid.UUID(site.venue_id))
    shift = await shift_for(db, venue, workspace.worker, start=start, end=end)
    entry = await time_for(db, venue, workspace.worker, start=start, end=end, pause=pause)
    await link(client, site, entry, shift)
    return venue, entry, shift


async def test_manager_only_rates_and_cross_tenant_worker_boundaries(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
):
    path = site.path(f"/labour-rates/{hr_workspace.worker.id}")
    assert (
        await client.get(site.path("/labour-rates"), headers=hr_workspace.headers("worker"))
    ).status_code == 403
    assert (
        await client.post(path, headers=hr_workspace.headers("worker"), json=revision())
    ).status_code == 403
    assert (
        await client.get(site.path("/labour-rates"), headers=hr_workspace.headers("other_hr"))
    ).status_code == 404
    assert (
        await client.post(
            site.path(f"/labour-rates/{hr_workspace.other_worker.id}"),
            headers=site.headers,
            json=revision(),
        )
    ).status_code == 404
    result = await save(client, site, hr_workspace.worker.id)
    rows = body(await client.get(site.path("/labour-rates"), headers=site.headers))
    assert (
        next(row for row in rows if row["worker_id"] == str(hr_workspace.worker.id))["current"]
        == result
    )
    assert (
        await client.get(
            site.path(f"/labour-rates/{hr_workspace.other_worker.id}/revisions/{result['id']}"),
            headers=site.headers,
        )
    ).status_code == 404


async def test_revision_sources_overlap_validation_and_exact_replay(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
):
    path = site.path(f"/labour-rates/{hr_workspace.worker.id}")
    invalid = [
        revision([period(), period(START + timedelta(hours=1))]),
        revision([period(end=START)]),
        revision(source_reference=" "),
        revision([{**period(), "valid_from": "2026-09-12T08:00:00"}]),
        revision([{**period(), "hourly_cents": True}]),
    ]
    for data in invalid:
        assert (await client.post(path, headers=site.headers, json=data)).status_code == 422
    first_input = revision()
    first = await save(client, site, hr_workspace.worker.id, first_input)
    second = await save(
        client,
        site,
        hr_workspace.worker.id,
        revision([period(hourly=1500)], version=1, reason="Corrected synthetic source"),
    )
    assert second["previous_id"] == first["id"] and second["version"] == 2
    assert await save(client, site, hr_workspace.worker.id, first_input) == first
    assert (
        await client.post(
            path, headers=site.headers, json={**first_input, "reason": "Different data"}
        )
    ).status_code == 409
    assert (await client.post(path, headers=site.headers, json=revision())).status_code == 409
    history = body(await client.get(path + "/revisions", headers=site.headers))
    assert [row["id"] for row in history] == [second["id"], first["id"]]
    assert body(await client.get(path + "/revisions?before_version=2", headers=site.headers)) == [
        first
    ]
    assert body(await client.get(path + f"/revisions/{first['id']}", headers=site.headers)) == first


async def test_rates_split_approved_pause_minutes_and_employer_markup(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    venue, _, _ = await approved_work(client, site, db_session, hr_workspace)
    middle = START + timedelta(hours=2)
    saved = await save(
        client,
        site,
        hr_workspace.worker.id,
        revision([period(end=middle, markup=2000), period(middle, hourly=1800)]),
    )
    whole = await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    first = await labour_summary(db_session, venue, START, middle)
    second = await labour_summary(db_session, venue, middle, START + timedelta(hours=4))
    assert (
        whole.cost_cents,
        whole.known_cost_cents,
        whole.valued_minutes,
        whole.unvalued_minutes,
    ) == (5670, 5670, 210, 0)
    assert first.valued_minutes == second.valued_minutes == 105
    assert first.known_cost_cents + second.known_cost_cents == whole.known_cost_cents
    assert whole.rate_revision_ids == [uuid.UUID(saved["id"])]
    assert whole.basis == "current_immutable_rate_revisions"
    response = await client.get(
        site.path("/labour-summary"),
        headers=site.headers,
        params={"start": START.isoformat(), "end": (START + timedelta(hours=4)).isoformat()},
    )
    assert body(response) == whole.model_dump(mode="json")


async def test_gaps_remain_unvalued_while_explicit_zero_rate_and_known_cost_survive(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    venue, _, _ = await approved_work(client, site, db_session, hr_workspace)
    await save(
        client,
        site,
        hr_workspace.worker.id,
        revision(
            [period(end=START + timedelta(hours=1)), period(START + timedelta(hours=3), hourly=0)]
        ),
    )
    result = await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    assert result.cost_cents is None and result.known_cost_cents == 1040
    assert result.valued_minutes == result.unvalued_minutes == 105


async def test_current_worker_setting_is_never_used_as_historical_rate(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    venue, _, _ = await approved_work(client, site, db_session, hr_workspace)
    settings = (
        await db_session.execute(
            select(WorkerSettings).where(WorkerSettings.user_id == hr_workspace.worker.id)
        )
    ).scalar_one()
    settings.hourly_rate = Decimal("19.99")
    await db_session.flush()
    first = await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    settings.hourly_rate = Decimal("99.99")
    await db_session.flush()
    second = await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    assert first == second
    assert first.cost_cents is None and first.known_cost_cents == first.valued_minutes == 0
    assert first.unvalued_minutes == 210


async def test_rate_correction_changes_live_basis_but_old_revision_stays_retrievable(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    venue, _, _ = await approved_work(client, site, db_session, hr_workspace)
    old = await save(client, site, hr_workspace.worker.id)
    before = await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    new = await save(
        client, site, hr_workspace.worker.id, revision([period(hourly=1800)], version=1)
    )
    after = await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    assert before.known_cost_cents == 4200 and after.known_cost_cents == 6300
    assert before.source_fingerprint != after.source_fingerprint
    assert after.rate_revision_ids == [uuid.UUID(new["id"])]
    assert (
        body(
            await client.get(
                site.path(f"/labour-rates/{hr_workspace.worker.id}/revisions/{old['id']}"),
                headers=site.headers,
            )
        )
        == old
    )


async def test_stale_attribution_and_unapproved_time_are_never_costed(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    venue, entry, shift = await approved_work(client, site, db_session, hr_workspace)
    await save(client, site, hr_workspace.worker.id)
    entry.break_minutes = 31
    await db_session.flush()
    result = await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    assert result.valued_minutes == result.unvalued_minutes == result.known_cost_cents == 0
    attribution = (
        await db_session.execute(
            select(TipTimeAttribution).where(TipTimeAttribution.entry_id == entry.id)
        )
    ).scalar_one()
    entry.status = "submitted"
    attribution.entry_hash, attribution.shift_hash = time_hashes(entry, shift)
    await db_session.flush()
    assert (
        await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    ).known_cost_cents == 0


async def test_cross_venue_ambiguous_attribution_is_open_and_not_doubled(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    venue, entry, _ = await approved_work(client, site, db_session, hr_workspace)
    await save(client, site, hr_workspace.worker.id)
    other = Venue(name="Other synthetic operation", tenant_id=venue.tenant_id)
    db_session.add(other)
    await db_session.flush()
    shift = await shift_for(db_session, other, hr_workspace.worker)
    eh, sh = time_hashes(entry, shift)
    db_session.add(
        TipTimeAttribution(
            entry_id=entry.id,
            shift_id=shift.id,
            actor_id=hr_workspace.hr.id,
            entry_hash=eh,
            shift_hash=sh,
        )
    )
    await db_session.flush()
    result = await labour_summary(db_session, venue, START, START + timedelta(hours=4))
    assert result.cost_cents is None and result.known_cost_cents == result.valued_minutes == 0
    assert result.unvalued_minutes == result.ambiguous_minutes == 210


async def test_dst_and_midnight_splits_conserve_pause_minutes_and_cents(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    start = datetime.fromisoformat("2026-10-24T23:30:00+02:00").astimezone(UTC)
    end = datetime.fromisoformat("2026-10-25T03:30:00+01:00").astimezone(UTC)
    middle = datetime.fromisoformat("2026-10-25T02:30:00+01:00").astimezone(UTC)
    midnight = datetime.fromisoformat("2026-10-25T00:00:00+02:00").astimezone(UTC)
    venue, _, _ = await approved_work(client, site, db_session, hr_workspace, start, end)
    await save(
        client,
        site,
        hr_workspace.worker.id,
        revision([period(start, middle), period(middle, hourly=1800)]),
    )
    whole = await labour_summary(db_session, venue, start, end)
    before = await labour_summary(db_session, venue, start, midnight)
    after = await labour_summary(db_session, venue, midnight, end)
    assert whole.valued_minutes == 270 and whole.known_cost_cents == 5940
    assert before.valued_minutes + after.valued_minutes == whole.valued_minutes
    assert before.known_cost_cents + after.known_cost_cents == whole.known_cost_cents


async def test_cent_rounding_is_conserved_across_tiny_report_windows(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    venue, _, _ = await approved_work(
        client, site, db_session, hr_workspace, START, START + timedelta(minutes=3), pause=0
    )
    await save(client, site, hr_workspace.worker.id, revision([period(hourly=1000)]))
    slices = [
        await labour_summary(
            db_session, venue, START + timedelta(minutes=i), START + timedelta(minutes=i + 1)
        )
        for i in range(3)
    ]
    whole = await labour_summary(db_session, venue, START, START + timedelta(minutes=3))
    assert [row.known_cost_cents for row in slices] == [17, 16, 17]
    assert whole.known_cost_cents == sum(row.known_cost_cents for row in slices) == 50


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/080_flintplate_labour_rates.py"
    spec = importlib.util.spec_from_file_location("labour080", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_database_guards_preserve_rate_evidence_and_refuse_overlap(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
):
    connection = await db_session.connection()
    await connection.run_sync(migration().install_guards)
    saved = await save(client, site, hr_workspace.worker.id)
    for sql in (
        "UPDATE fp_labour_rate_revisions SET periods='[]'::jsonb WHERE id=:id",
        "DELETE FROM fp_labour_rate_revisions WHERE id=:id",
        "TRUNCATE fp_labour_rate_revisions",
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(sql), {"id": uuid.UUID(saved["id"])})
    for bad_periods in (
        [period(), period(START + timedelta(hours=1))],
        [{**period(), "source_reference": " "}],
        [{**period(), "valid_from": "2026-09-12T08:00:00"}],
        [{**period(), "hourly_cents": -1}],
    ):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                db_session.add(
                    LabourRateRevision(
                        venue_id=uuid.UUID(site.venue_id),
                        worker_id=hr_workspace.worker.id,
                        previous_id=uuid.UUID(saved["id"]),
                        version=2,
                        currency="EUR",
                        request_key=uuid.uuid4(),
                        request_hash="0" * 64,
                        actor_id=hr_workspace.hr.id,
                        reason="Synthetic malformed direct insert",
                        source_reference="Synthetic source",
                        periods=bad_periods,
                    )
                )
                await db_session.flush()
    valid = await save(
        client,
        site,
        hr_workspace.worker.id,
        revision(
            [period(end=START + timedelta(hours=1)), period(START + timedelta(hours=1))], version=1
        ),
    )
    assert valid["version"] == 2


async def test_real_migration_has_every_inherited_column_and_non_destructive_downgrade():
    schema = "labour_upgrade_" + uuid.uuid4().hex
    module = migration()
    async with test_engine.begin() as connection:
        await connection.execution_options(schema_translate_map={None: schema})
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}",public'))
        for sql in (
            "CREATE TABLE fp_venues(id uuid PRIMARY KEY,tenant_id uuid,currency text)",
            "CREATE TABLE users(id uuid PRIMARY KEY,tenant_id uuid)",
            "CREATE TABLE fp_memberships(venue_id uuid,user_id uuid)",
        ):
            await connection.execute(text(sql))

        def upgrade(sync):
            module.op = Operations(MigrationContext.configure(sync))
            module.upgrade()

        await connection.run_sync(upgrade)

        def columns_match(sync):
            actual = {
                row["name"]: row["nullable"]
                for row in inspect(sync).get_columns("fp_labour_rate_revisions", schema=schema)
            }
            expected = {
                column.name: column.nullable for column in LabourRateRevision.__table__.columns
            }
            assert actual == expected

        await connection.run_sync(columns_match)
        tenant_id, venue_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await connection.execute(
            text("INSERT INTO fp_venues VALUES(:venue,:tenant,'EUR')"),
            {"venue": venue_id, "tenant": tenant_id},
        )
        await connection.execute(
            text("INSERT INTO users VALUES(:worker,:tenant)"),
            {"worker": user_id, "tenant": tenant_id},
        )
        await connection.execute(
            text("INSERT INTO fp_memberships VALUES(:venue,:worker)"),
            {"venue": venue_id, "worker": user_id},
        )
        with pytest.raises(DBAPIError, match="explicit restore plan"):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "INSERT INTO fp_labour_rate_revisions(id,venue_id,worker_id,version,currency,request_key,request_hash,actor_id,reason,source_reference,periods) VALUES(:id,:venue,:worker,1,'EUR',:key,:hash,:worker,'Synthetic basis','Synthetic source',CAST(:periods AS jsonb))"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "venue": venue_id,
                        "worker": user_id,
                        "key": uuid.uuid4(),
                        "hash": "0" * 64,
                        "periods": json.dumps([period()]),
                    },
                )
                await connection.run_sync(lambda sync: module.downgrade())
        assert await connection.scalar(text("SELECT count(*) FROM fp_labour_rate_revisions")) == 0
        await connection.run_sync(lambda sync: module.downgrade())
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def test_concurrent_correctors_cannot_overwrite_each_other():
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Labour concurrency", slug="labour-" + uuid.uuid4().hex, status="active"
        )
        db.add(tenant)
        await db.flush()
        actor = User(
            email=f"labour-{uuid.uuid4().hex}@example.invalid",
            hashed_password="synthetic",
            full_name="Synthetic manager",
            role="recruiter",
            tenant_id=tenant.id,
            is_active=True,
        )
        db.add(actor)
        await db.flush()
        venue = Venue(name="Labour operation", tenant_id=tenant.id)
        db.add(venue)
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=actor.id, role="manager"))
        await db.flush()
        await labour.revise(
            venue.id, actor.id, LabourRevisionInput.model_validate(revision()), actor, db
        )
        venue_id, user_id = venue.id, actor.id
        await db.commit()

    async def correct(hourly):
        async with TestSessionLocal() as db:
            actor = await db.get(User, user_id)
            try:
                row = await labour.revise(
                    venue_id,
                    user_id,
                    LabourRevisionInput.model_validate(
                        revision([period(hourly=hourly)], version=1)
                    ),
                    actor,
                    db,
                )
                await db.commit()
                return row.version
            except HTTPException as error:
                await db.rollback()
                return error.status_code

    assert sorted(await asyncio.wait_for(asyncio.gather(correct(1800), correct(1900)), 15)) == [
        2,
        409,
    ]
    async with TestSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(LabourRateRevision)
                .where(LabourRateRevision.venue_id == venue_id)
            )
            == 2
        )
