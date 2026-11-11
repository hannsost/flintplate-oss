"""Traceable calculation from approved attribution and current immutable rates."""

from __future__ import annotations

import hashlib
import json
import uuid
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.labour_models import LabourRateRevision
from app.gastro.labour_schemas import LabourPeriod, LabourSummary
from app.gastro.models import Shift, Venue
from app.gastro.tip_models import TipTimeAttribution
from app.gastro.tips import as_utc, attributed_minutes, time_hashes
from app.users.models import User
from app.worker.time_models import TimeEntry


@dataclass(frozen=True)
class AttributedWork:
    entry: TimeEntry
    shift: Shift
    attribution: TipTimeAttribution
    start: datetime
    end: datetime


def rounded_cost(minutes: int, period: LabourPeriod) -> int:
    numerator = minutes * period.hourly_cents * (10000 + period.employer_markup_bps)
    return (numerator + 300000) // 600000


def interval_cost(
    work: AttributedWork, period: LabourPeriod, start: datetime, end: datetime
) -> int:
    # Cumulative cents anchored to the same rate/entry boundary conserve money
    # when a report is split at midnight, a rate change or a DST transition.
    before = attributed_minutes(work.entry, work.shift, period.valid_from, start)
    after = attributed_minutes(work.entry, work.shift, period.valid_from, end)
    return rounded_cost(after, period) - rounded_cost(before, period)


async def current_revisions(
    db: AsyncSession, venue_id: uuid.UUID, worker_ids: set[uuid.UUID] | None = None
) -> dict[uuid.UUID, LabourRateRevision]:
    query = select(LabourRateRevision).where(LabourRateRevision.venue_id == venue_id)
    if worker_ids is not None:
        if not worker_ids:
            return {}
        query = query.where(LabourRateRevision.worker_id.in_(worker_ids))
    rows = (
        await db.execute(
            query.distinct(LabourRateRevision.worker_id).order_by(
                LabourRateRevision.worker_id, LabourRateRevision.version.desc()
            )
        )
    ).scalars()
    return {row.worker_id: row for row in rows}


async def labour_summary(
    db: AsyncSession, venue: Venue, start: datetime, end: datetime
) -> LabourSummary:
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "Der Auswertungszeitraum benötigt eine Zeitzone.")
    start, end = as_utc(start), as_utc(end)
    if end <= start or end - start > timedelta(days=366):
        raise HTTPException(422, "Personalkostenauswertungen umfassen höchstens 366 Tage.")
    query = (
        select(TimeEntry, Shift, TipTimeAttribution)
        .join(TipTimeAttribution, TipTimeAttribution.entry_id == TimeEntry.id)
        .join(Shift, Shift.id == TipTimeAttribution.shift_id)
        .join(Venue, Venue.id == Shift.venue_id)
        .join(User, User.id == TimeEntry.worker_id)
        .where(
            TimeEntry.tenant_id == venue.tenant_id,
            Venue.tenant_id == venue.tenant_id,
            User.tenant_id == venue.tenant_id,
            Shift.worker_id == TimeEntry.worker_id,
            TimeEntry.status == "approved",
            Shift.status == "published",
            TimeEntry.clock_in < end,
            TimeEntry.clock_out > start,
            Shift.starts_at < end,
            Shift.ends_at > start,
        )
    )
    local = (await db.execute(query.where(Shift.venue_id == venue.id))).all()
    workers = {entry.worker_id for entry, _, _ in local}
    # Detect conflicting approved links in another venue as well. A caller must
    # never receive its colleagues' wages or identities from this internal check.
    rows = (
        (await db.execute(query.where(TimeEntry.worker_id.in_(workers)))).all() if workers else []
    )
    by_worker: dict[uuid.UUID, list[AttributedWork]] = defaultdict(list)
    evidence: list[list[str]] = []
    for entry, shift, attribution in rows:
        if entry.clock_out is None or not entry.net_minutes:
            continue
        if time_hashes(entry, shift) != (attribution.entry_hash, attribution.shift_hash):
            continue
        lower = max(start, as_utc(entry.clock_in), as_utc(shift.starts_at))
        upper = min(end, as_utc(entry.clock_out), as_utc(shift.ends_at))
        if lower >= upper:
            continue
        by_worker[entry.worker_id].append(AttributedWork(entry, shift, attribution, lower, upper))
        evidence.append([str(attribution.id), attribution.entry_hash, attribution.shift_hash])
    revisions = await current_revisions(db, venue.id, workers)
    known_cost = valued = unvalued = ambiguous = 0
    for worker_id, work_items in by_worker.items():
        revision = revisions.get(worker_id)
        periods = (
            [LabourPeriod.model_validate(value) for value in revision.periods] if revision else []
        )
        if revision is not None and revision.currency != venue.currency:
            periods = []
        period_starts = [period.valid_from for period in periods]
        boundaries = {start, end}
        starting: dict[datetime, list[AttributedWork]] = defaultdict(list)
        ending: dict[datetime, list[AttributedWork]] = defaultdict(list)
        for work in work_items:
            boundaries.update((work.start, work.end))
            starting[work.start].append(work)
            ending[work.end].append(work)
        for period in periods:
            if start < period.valid_from < end:
                boundaries.add(period.valid_from)
            if period.valid_until is not None and start < period.valid_until < end:
                boundaries.add(period.valid_until)
        ordered = sorted(boundaries)
        active_by_id: dict[uuid.UUID, AttributedWork] = {}
        for lower, upper in pairwise(ordered):
            for work in ending.get(lower, []):
                active_by_id.pop(work.attribution.id, None)
            for work in starting.get(lower, []):
                active_by_id[work.attribution.id] = work
            active = list(active_by_id.values())
            local_active = [work for work in active if work.shift.venue_id == venue.id]
            if not local_active:
                continue
            if len(active) != 1:
                # These are unresolved approved RECORD minutes. Deduplicate one
                # TimeEntry linked to several shifts; never cost ambiguous work.
                by_entry = {work.entry.id: work for work in local_active}
                minutes = sum(
                    attributed_minutes(work.entry, work.shift, lower, upper)
                    for work in by_entry.values()
                )
                unvalued += minutes
                ambiguous += minutes
                continue
            work = active[0]
            minutes = attributed_minutes(work.entry, work.shift, lower, upper)
            rate_index = bisect_right(period_starts, lower) - 1
            rate = periods[rate_index] if rate_index >= 0 else None
            if rate is not None and rate.valid_until is not None and rate.valid_until < upper:
                rate = None
            if rate is None:
                unvalued += minutes
                continue
            valued += minutes
            known_cost += interval_cost(work, rate, lower, upper)
    revision_ids = sorted((row.id for row in revisions.values()), key=str)
    source = {
        "method": "approved-attribution-current-rates-cumulative-cents-v1",
        "venue_id": str(venue.id),
        "currency": venue.currency,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rate_revision_ids": [str(value) for value in revision_ids],
        "attributions": sorted(evidence),
    }
    return LabourSummary(
        cost_cents=None if unvalued else known_cost,
        known_cost_cents=known_cost,
        valued_minutes=valued,
        unvalued_minutes=unvalued,
        ambiguous_minutes=ambiguous,
        rate_revision_ids=revision_ids,
        source_fingerprint=hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
    )
