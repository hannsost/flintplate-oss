"""Bilateral, revocable demand sharing without implicit access to people."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.security import create_access_token
from app.users.models import User
from tests.hr_support import HRWorkspace, body
from tests.utils import auth_headers


async def setup(db: AsyncSession, ws: HRWorkspace) -> Customer:
    ws.hr.role = "admin"
    ws.other_hr.role = "admin"
    await db.flush()
    c = await db.get(Customer, ws.other_hr.tenant_id)
    assert c
    return c


def demand() -> dict:
    return {
        "title": "Lagerfachkräfte",
        "location": "Berlin",
        "starts_on": str(date(2026, 10, 12)),
        "headcount": 4,
        "required_skills": ["Stapler"],
    }


@pytest.mark.asyncio
async def test_partner_full_bilateral_flow_and_revocation(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    c = await setup(db_session, ws)
    p = body(
        await client.post(
            "/partners",
            headers=ws.headers(),
            json={"target_slug": c.slug, "purpose": "Zusammenarbeit bei Lageraufträgen"},
        ),
        201,
    )
    pid = p["id"]
    assert p["status"] == "pending"
    assert (await client.get(f"/partners/{pid}/demands", headers=ws.headers())).status_code == 403
    assert (
        await client.post(
            f"/partners/{pid}/decision",
            headers=ws.headers(),
            json={"version": 1, "action": "accept"},
        )
    ).status_code == 403
    incoming = body(await client.get("/partners", headers=ws.headers("other_hr")))
    assert incoming[0]["incoming"] is True
    active = body(
        await client.post(
            f"/partners/{pid}/decision",
            headers=ws.headers("other_hr"),
            json={"version": 1, "action": "accept"},
        )
    )
    assert active["status"] == "active"
    d = body(
        await client.post(f"/partners/{pid}/demands", headers=ws.headers(), json=demand()), 201
    )
    assert d["own"] is True
    other = body(await client.get(f"/partners/{pid}/demands", headers=ws.headers("other_hr")))[0]
    assert other["own"] is False and "worker_id" not in other
    assert (
        await client.put(
            f'/partners/{pid}/demands/{d["id"]}/capacity',
            headers=ws.headers(),
            json={"version": 1, "offered_count": 2},
        )
    ).status_code == 403
    assert (
        await client.put(
            f'/partners/{pid}/demands/{d["id"]}/capacity',
            headers=ws.headers("other_hr"),
            json={"version": 1, "offered_count": 5},
        )
    ).status_code == 422
    offered = body(
        await client.put(
            f'/partners/{pid}/demands/{d["id"]}/capacity',
            headers=ws.headers("other_hr"),
            json={"version": 1, "offered_count": 3},
        )
    )
    assert offered["offered_count"] == 3 and offered["version"] == 2
    assert (
        await client.put(
            f'/partners/{pid}/demands/{d["id"]}/capacity',
            headers=ws.headers("other_hr"),
            json={"version": 1, "offered_count": 1},
        )
    ).status_code == 409
    assert (
        await client.post(
            f'/partners/{pid}/demands/{d["id"]}/close',
            headers=ws.headers("other_hr"),
            json={"version": 2},
        )
    ).status_code == 403
    closed = body(
        await client.post(
            f'/partners/{pid}/demands/{d["id"]}/close', headers=ws.headers(), json={"version": 2}
        )
    )
    assert closed["status"] == "closed"
    body(
        await client.post(
            f"/partners/{pid}/decision",
            headers=ws.headers(),
            json={"version": 2, "action": "revoke"},
        )
    )
    for who in ("hr", "other_hr"):
        assert (
            await client.get(f"/partners/{pid}/demands", headers=ws.headers(who))
        ).status_code == 403
        assert (
            await client.post(f"/partners/{pid}/demands", headers=ws.headers(who), json=demand())
        ).status_code == 403
    history = body(await client.get(f"/partners/{pid}/events", headers=ws.headers()))
    assert {e["action"] for e in history} == {
        "requested",
        "accept",
        "demand_shared",
        "capacity_offered",
        "demand_closed",
        "revoke",
    }


@pytest.mark.asyncio
async def test_partner_no_self_invite_duplicates_or_third_party_access(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    c = await setup(db_session, ws)
    mine = await db_session.get(Customer, ws.hr.tenant_id)
    assert mine
    assert (
        await client.post(
            "/partners",
            headers=ws.headers(),
            json={"target_slug": mine.slug, "purpose": "Testzweck"},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/partners",
            headers=ws.headers(),
            json={"target_slug": "not-there", "purpose": "Testzweck"},
        )
    ).status_code == 404
    payload = {"target_slug": c.slug, "purpose": "Testzweck"}
    p = body(await client.post("/partners", headers=ws.headers(), json=payload), 201)
    assert (await client.post("/partners", headers=ws.headers(), json=payload)).status_code == 409
    assert (
        await client.post(
            "/partners", headers=ws.headers("other_hr"), json={**payload, "target_slug": mine.slug}
        )
    ).status_code == 409
    third = Customer(name="Dritte Firma", slug=uuid.uuid4().hex, status="active")
    db_session.add(third)
    await db_session.flush()
    u = User(
        email=f"third-{uuid.uuid4().hex}@example.com",
        role="admin",
        tenant_id=third.id,
        hashed_password="fixture",
    )
    db_session.add(u)
    await db_session.flush()
    headers = auth_headers(create_access_token({"sub": u.email}))
    for path in (f'/partners/{p["id"]}/demands', f'/partners/{p["id"]}/events'):
        assert (await client.get(path, headers=headers)).status_code == 404
    assert body(await client.get("/partners", headers=headers)) == []
    assert (
        await client.post(
            f'/partners/{p["id"]}/decision',
            headers=headers,
            json={"version": 1, "action": "accept"},
        )
    ).status_code == 404
    assert (await client.get("/partners", headers=ws.headers("worker"))).status_code == 403
    ws.hr.role = "recruiter"
    await db_session.flush()
    assert (await client.post("/partners", headers=ws.headers(), json=payload)).status_code == 403


@pytest.mark.asyncio
async def test_partner_versions_suspension_and_payload_allowlist(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    c = await setup(db_session, ws)
    p = body(
        await client.post(
            "/partners", headers=ws.headers(), json={"target_slug": c.slug, "purpose": "Testzweck"}
        ),
        201,
    )
    pid = p["id"]
    assert (
        await client.post(
            f"/partners/{pid}/decision",
            headers=ws.headers("other_hr"),
            json={"version": 9, "action": "accept"},
        )
    ).status_code == 409
    await client.post(
        f"/partners/{pid}/decision",
        headers=ws.headers("other_hr"),
        json={"version": 1, "action": "accept"},
    )
    assert (
        await client.post(
            f"/partners/{pid}/demands",
            headers=ws.headers(),
            json={**demand(), "candidate_ids": [str(ws.worker.id)]},
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/partners/{pid}/demands",
            headers=ws.headers(),
            json={**demand(), "required_skills": [" "]},
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/partners/{pid}/demands/{uuid.uuid4()}/close",
            headers=ws.headers(),
            json={"version": 1},
        )
    ).status_code == 404
    c.status = "suspended"
    await db_session.flush()
    assert (await client.get(f"/partners/{pid}/demands", headers=ws.headers())).status_code == 403
