"""Customer orders remain distinct from worker shifts and isolate their worker pools."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.profiles.models import CandidateProfile, Skill
from app.zeitarbeit.models import WorkAssignment
from tests.hr_support import HRWorkspace, body


@pytest.fixture(autouse=True)
async def pool_profiles(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    for user, who in [(h.worker, "worker"), (h.other_worker, "other_worker")]:
        profile = CandidateProfile(user_id=user.id, headline="Lagerlogistik")
        db_session.add(profile)
        await db_session.flush()
        db_session.add(Skill(profile_id=profile.id, name="Stapler"))
        await db_session.flush()
        assert (
            await client.get("/zeitarbeit/availability/me", headers=h.headers(who))
        ).json() is None
        body(
            await client.put(
                "/zeitarbeit/availability/me",
                headers=h.headers(who),
                json={"is_in_pool": True, "preferred_shift": "day"},
            )
        )


async def order(client: AsyncClient, h: HRWorkspace) -> str:
    data = body(
        await client.post(
            "/zeitarbeit/orders",
            headers=h.headers(),
            json={"title": "Lagerlogistik", "required_skills": ["Stapler"], "shift": "day"},
        ),
        201,
    )
    return str(data["id"])


async def test_order_matching_canvas_and_period_updates(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
) -> None:
    h = hr_workspace
    worker_id = str(h.worker.id)
    oid = await order(client, h)
    path = f"/zeitarbeit/orders/{oid}"
    stored = await db_session.get(WorkAssignment, uuid.UUID(oid))
    assert stored is not None and stored.tenant_id == h.hr.tenant_id
    assert len((await client.get("/zeitarbeit/orders", headers=h.headers())).json()) == 1
    assert (await client.get("/zeitarbeit/assignments", headers=h.headers())).json() == []
    assert body(await client.get(path, headers=h.headers()))["title"] == "Lagerlogistik"
    assert (await client.get("/zeitarbeit/orders", headers=h.headers("other_hr"))).json() == []
    assert (
        body(await client.patch(path, headers=h.headers(), json={"status": "matching"}))["status"]
        == "matching"
    )
    for _ in range(2):
        result = await client.post(path + "/match", headers=h.headers())
        assert result.status_code == 200, result.text
        matches = result.json()
        assert [m["worker_id"] for m in matches] == [worker_id]
        persisted = (await client.get(path + "/dispositions", headers=h.headers())).json()
        assert matches[0]["id"] == persisted[0]["id"]
    canvas = body(await client.get(f"/zeitarbeit/canvas/job/{oid}", headers=h.headers()))
    assert canvas["pool_size"] == 1
    assert len((await client.get("/zeitarbeit/canvas/pool", headers=h.headers())).json()) == 1
    assert (
        body(await client.get("/zeitarbeit/orders/stats", headers=h.headers()))["workers_in_pool"]
        == 1
    )
    assigned = body(
        await client.post(
            "/zeitarbeit/canvas/assign",
            headers=h.headers(),
            json={"assignment_id": oid, "worker_id": worker_id},
        ),
        201,
    )
    assert assigned["status"] == "confirmed"
    worker = body(await client.get(f"/zeitarbeit/canvas/worker/{worker_id}", headers=h.headers()))
    assert worker["active_assignments"][0]["id"] == oid
    disp_path = path + f"/dispositions/{worker_id}"
    for status in ["active", "completed", "completed"]:
        body(
            await client.patch(
                disp_path,
                headers=h.headers(),
                json={
                    "status": status,
                    "started_at": "2027-01-01",
                    "ended_at": "2027-01-31",
                    "notes": "Geprüft",
                },
            )
        )
        availability = body(
            await client.get("/zeitarbeit/availability/me", headers=h.headers("worker"))
        )
        assert Decimal(availability["total_placed_months"]) == Decimal("0.99")
    assert (
        await client.patch(
            disp_path, headers=h.headers(), json={"status": "completed", "ended_at": "2026-12-01"}
        )
    ).status_code == 422
    assert (await client.delete(path, headers=h.headers())).status_code == 204
    assert (await client.get(path, headers=h.headers())).status_code == 404


@pytest.mark.parametrize("operation", ["read", "update", "delete", "match", "canvas", "assign"])
async def test_foreign_staffing_orders_are_inaccessible(
    client: AsyncClient, hr_workspace: HRWorkspace, operation: str
) -> None:
    h = hr_workspace
    oid = await order(client, h)
    path = f"/zeitarbeit/orders/{oid}"
    method, endpoint, data = {
        "read": ("GET", path, None),
        "update": ("PATCH", path, {"title": "Foreign"}),
        "delete": ("DELETE", path, None),
        "match": ("POST", path + "/match", None),
        "canvas": ("GET", f"/zeitarbeit/canvas/job/{oid}", None),
        "assign": (
            "POST",
            "/zeitarbeit/canvas/assign",
            {"assignment_id": oid, "worker_id": str(h.other_worker.id)},
        ),
    }[operation]
    assert (
        await client.request(method, endpoint, headers=h.headers("other_hr"), json=data)
    ).status_code == 403


async def test_foreign_workers_cannot_be_viewed_or_assigned(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    oid = await order(client, h)
    foreign = str(h.other_worker.id)
    assert (
        await client.get(f"/zeitarbeit/canvas/worker/{foreign}", headers=h.headers())
    ).status_code == 404
    assert (
        await client.post(
            "/zeitarbeit/canvas/assign",
            headers=h.headers(),
            json={"assignment_id": oid, "worker_id": foreign},
        )
    ).status_code == 404
    body(
        await client.put(
            "/zeitarbeit/availability/me", headers=h.headers("worker"), json={"is_in_pool": False}
        )
    )
    assert (
        await client.get(f"/zeitarbeit/canvas/worker/{h.worker.id}", headers=h.headers())
    ).status_code == 404
