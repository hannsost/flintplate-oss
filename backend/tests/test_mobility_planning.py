"""Test assignment optimality against an independent exhaustive oracle and tenant data."""

from __future__ import annotations

import itertools
import random
import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.absences.models import Absence
from app.mobility.planner import Person, PlanInput, optimise
from app.worker.assignment_models import WorkerAssignment
from tests.hr_support import HRWorkspace, body


def inputs(worker_ids: list[uuid.UUID]) -> dict:
    return {
        "title": "Frühschicht",
        "shift_start": "2026-10-12T08:00:00+02:00",
        "shift_end": "2026-10-12T16:00:00+02:00",
        "arrival_buffer_minutes": 15,
        "demands": [{"key": "lager", "title": "Lager", "headcount": 2, "required_skills": []}],
        "trips": [
            {
                "key": "van",
                "demand_key": "lager",
                "pickup": "Bahnhof",
                "vehicle": "Bus 1",
                "seats": 2,
                "outbound_minutes": 20,
                "return_minutes": 30,
                "source": "Routenplaner, manuell geprüft",
            }
        ],
        "workers": [
            {
                "worker_id": str(uid),
                "pickup": "Bahnhof",
                "available_from": "2026-10-12T06:00:00+02:00",
                "available_until": "2026-10-12T19:00:00+02:00",
                "max_commute_minutes": 60,
            }
            for uid in worker_ids
        ],
    }


def test_scarce_skill_is_not_lost_by_greedy_shortest_route() -> None:
    ids = [uuid.uuid4(), uuid.uuid4()]
    raw = inputs(ids)
    raw["demands"] = [
        {"key": "general", "title": "Packen", "headcount": 1, "required_skills": []},
        {"key": "special", "title": "Stapler", "headcount": 1, "required_skills": ["Stapler"]},
    ]
    raw["trips"] = [
        {
            **raw["trips"][0],
            "key": "short",
            "demand_key": "general",
            "vehicle": "Bus A",
            "outbound_minutes": 5,
            "return_minutes": 5,
        },
        {**raw["trips"][0], "key": "long", "demand_key": "special", "vehicle": "Bus B"},
    ]
    result = optimise(
        PlanInput.model_validate(raw),
        {ids[0]: Person("Spezialistin", {"stapler"}), ids[1]: Person("Generalist", set())},
    )
    assert len(result.allocations) == 2
    assert next(a for a in result.allocations if a.worker_id == ids[0]).demand_key == "special"
    assert result.total_travel_minutes == 60


def test_optimizer_matches_exhaustive_optimum_for_small_networks() -> None:
    rng = random.Random(81)
    for _ in range(40):
        ids = [uuid.uuid4() for _ in range(4)]
        raw = inputs(ids)
        raw["demands"] = [
            {
                "key": str(i),
                "title": str(i),
                "headcount": rng.randint(1, 3),
                "required_skills": [str(i)] if rng.random() < 0.7 else [],
            }
            for i in range(2)
        ]
        raw["trips"] = [
            {
                **raw["trips"][0],
                "key": str(i),
                "vehicle": str(i),
                "demand_key": str(i % 2),
                "seats": rng.randint(1, 3),
                "outbound_minutes": rng.randint(1, 50),
                "return_minutes": rng.randint(1, 50),
            }
            for i in range(3)
        ]
        people = {
            uid: Person(str(i), {str(k) for k in range(2) if rng.random() < 0.7})
            for i, uid in enumerate(ids)
        }
        data = PlanInput.model_validate(raw)
        best = (0, 0)
        for choices in itertools.product([-1, 0, 1, 2], repeat=4):
            used = [i for i in choices if i >= 0]
            if any(used.count(ti) > t.seats for ti, t in enumerate(data.trips)):
                continue
            if any(
                sum(data.trips[ti].demand_key == d.key for ti in used) > d.headcount
                for d in data.demands
            ):
                continue
            if any(
                not set(data.demands[int(data.trips[ti].demand_key)].required_skills).issubset(
                    people[ids[wi]].skills
                )
                for wi, ti in enumerate(choices)
                if ti >= 0
            ):
                continue
            cost = sum(
                data.trips[ti].outbound_minutes + data.trips[ti].return_minutes for ti in used
            )
            best = max(best, (len(used), -cost))
        result = optimise(data, people)
        assert (len(result.allocations), -result.total_travel_minutes) == best


@pytest.mark.parametrize(
    "blocked", ["skill", "pickup", "availability", "commute", "conflict", "capacity"]
)
def test_constraints_explain_unfilled_places(blocked: str) -> None:
    ids = [uuid.uuid4(), uuid.uuid4()]
    raw = inputs(ids)
    person = Person("A", set(), conflict=blocked == "conflict")
    if blocked == "skill":
        raw["demands"][0]["required_skills"] = ["Stapler"]
    if blocked == "pickup":
        raw["workers"][0]["pickup"] = "Anderer Treffpunkt"
    if blocked == "availability":
        raw["workers"][0]["available_until"] = "2026-10-12T16:10:00+02:00"
    if blocked == "commute":
        raw["workers"][0]["max_commute_minutes"] = 10
    if blocked == "capacity":
        raw["trips"][0]["seats"] = 1
    result = optimise(PlanInput.model_validate(raw), {ids[0]: person, ids[1]: Person("B", set())})
    assert result.demands[0].unfilled >= 1 and result.unassigned


@pytest.mark.parametrize(
    "bad",
    [
        "duplicate_worker",
        "duplicate_vehicle",
        "unknown_demand",
        "naive",
        "too_long",
        "negative_seats",
        "unknown_field",
        "empty_skill",
        "timezone",
    ],
)
def test_invalid_plans_are_rejected(bad: str) -> None:
    raw = inputs([uuid.uuid4()])
    if bad == "duplicate_worker":
        raw["workers"].append(raw["workers"][0])
    if bad == "duplicate_vehicle":
        raw["trips"].append({**raw["trips"][0], "key": "other"})
    if bad == "unknown_demand":
        raw["trips"][0]["demand_key"] = "nope"
    if bad == "naive":
        raw["shift_start"] = "2026-10-12T08:00:00"
    if bad == "too_long":
        raw["shift_end"] = "2026-10-13T10:00:00+02:00"
    if bad == "negative_seats":
        raw["trips"][0]["seats"] = -1
    if bad == "unknown_field":
        raw["protected_trait_score"] = 100
    if bad == "empty_skill":
        raw["demands"][0]["required_skills"] = [" "]
    if bad == "timezone":
        raw["time_zone"] = "Not/A_Zone"
    with pytest.raises(ValidationError):
        PlanInput.model_validate(raw)


@pytest.mark.asyncio
async def test_plan_persistence_scope_and_conflicts(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    workers = body(await client.get("/mobility/workers", headers=ws.headers()))
    assert [w["id"] for w in workers] == [str(ws.worker.id)]
    raw = inputs([ws.worker.id])
    saved = body(await client.post("/mobility/plans", headers=ws.headers(), json=raw), 201)
    assert len(saved["result"]["allocations"]) == 1
    assert saved["result"]["allocations"][0]["departure"].startswith("2026-10-12T07:25")
    assert len(body(await client.get("/mobility/plans", headers=ws.headers()))) == 1
    assert (
        body(await client.get(f'/mobility/plans/{saved["id"]}', headers=ws.headers()))["id"]
        == saved["id"]
    )
    assert (
        await client.get(f'/mobility/plans/{saved["id"]}', headers=ws.headers("other_hr"))
    ).status_code == 404
    assert body(await client.get("/mobility/plans", headers=ws.headers("other_hr"))) == []
    assert (await client.get("/mobility/workers", headers=ws.headers("worker"))).status_code == 403
    assert (
        await client.post(
            "/mobility/plans", headers=ws.headers(), json=inputs([ws.other_worker.id])
        )
    ).status_code == 404
    db_session.add(
        Absence(
            worker_id=ws.worker.id,
            tenant_id=ws.hr.tenant_id,
            absence_type="sick",
            start_date=date(2026, 10, 12),
            end_date=date(2026, 10, 12),
            status="approved",
        )
    )
    await db_session.flush()
    conflict = body(await client.post("/mobility/plans", headers=ws.headers(), json=raw), 201)
    assert conflict["result"]["allocations"] == []
    assert "sick" not in str(conflict["result"])


@pytest.mark.asyncio
async def test_assignment_and_return_after_midnight_block_availability(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    db_session.add(
        WorkerAssignment(
            worker_id=ws.worker.id,
            tenant_id=ws.hr.tenant_id,
            start_date=date(2026, 10, 13),
            end_date=date(2026, 10, 13),
            status="confirmed",
        )
    )
    await db_session.flush()
    raw = inputs([ws.worker.id])
    raw.update(shift_start="2026-10-12T16:00:00+02:00", shift_end="2026-10-12T23:50:00+02:00")
    raw["workers"][0]["available_until"] = "2026-10-13T01:00:00+02:00"
    result = body(await client.post("/mobility/plans", headers=ws.headers(), json=raw), 201)
    assert result["result"]["allocations"] == []
