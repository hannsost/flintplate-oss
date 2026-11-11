"""Support consent, agent ownership, private notes and session billing records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import create_access_token
from app.support.models import SupportSession
from app.users.models import User
from tests.hr_support import HRWorkspace, body
from tests.utils import auth_headers


@pytest.fixture
async def agents(db_session: AsyncSession) -> list[dict[str, str]]:
    headers = []
    for index in range(2):
        user = User(
            email=f"agent-{uuid.uuid4().hex}@example.com",
            hashed_password="unused",
            role="support",
            full_name=f"Synthetic agent {index}",
        )
        db_session.add(user)
        await db_session.flush()
        headers.append(auth_headers(create_access_token({"sub": user.email})))
    return headers


@pytest.mark.parametrize(
    "billing,amount", [("free", None), ("per_session", 1499), ("per_minute", 500)]
)
async def test_support_lifecycle_and_private_agent_notes(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    agents: list[dict[str, str]],
    billing: str,
    amount: int | None,
) -> None:
    h = hr_workspace
    assert (await client.get("/support/config", headers=h.headers())).status_code == 403
    h.hr.role = "admin"
    await db_session.flush()
    body(await client.patch("/support/config", headers=h.headers(), json={"enabled": False}))
    assert body(await client.get("/support/config", headers=h.headers()))["enabled"] is False
    assert (
        await client.post("/support/sessions", headers=h.headers(), json={"subject": "Hilfe"})
    ).status_code == 403
    body(
        await client.patch(
            "/support/config",
            headers=h.headers(),
            json={
                "enabled": True,
                "allow_video": False,
                "billing_model": billing,
                "per_session_cents": 1499,
                "per_minute_cents": 250,
            },
        )
    )
    assert body(await client.get("/support/widget-config", headers=h.headers()))["enabled"] is True
    session = body(
        await client.post(
            "/support/sessions",
            headers=h.headers(),
            json={
                "subject": "Einsatzplanung prüfen",
                "video_enabled": True,
                "dom_viewing_enabled": True,
            },
        ),
        201,
    )
    assert session["video_enabled"] is False
    assert session["consent_given"] is False
    path = f'/support/sessions/{session["id"]}'
    assert len((await client.get("/support/sessions", headers=h.headers())).json()) == 1
    assert len((await client.get("/support/sessions", headers=agents[0])).json()) == 1
    assert len((await client.get("/support/sessions/queue", headers=agents[0])).json()) == 1
    assert (await client.get(path, headers=h.headers("other_hr"))).status_code == 403
    assert (await client.post(path + "/consent", headers=h.headers("other_hr"))).status_code == 404
    body(await client.post(path + "/accept", headers=agents[0]))
    assert (await client.post(path + "/accept", headers=agents[1])).status_code == 400
    assert body(await client.post(path + "/consent", headers=h.headers()))["consent_given"] is True
    notes = {"agent_notes": "Nur intern", "summary": "Planung erklärt"}
    assert (await client.patch(path + "/notes", headers=agents[1], json=notes)).status_code == 403
    assert (await client.post(path + "/end", headers=agents[1])).status_code == 403
    body(await client.patch(path + "/notes", headers=agents[0], json=notes))
    assert "agent_notes" not in body(await client.get(path, headers=h.headers()))
    assert body(await client.get(path, headers=agents[0]))["agent_notes"] == "Nur intern"
    stored = await db_session.get(SupportSession, uuid.UUID(session["id"]))
    assert stored is not None
    stored.started_at = datetime.now(UTC) - timedelta(seconds=125)
    await db_session.flush()
    ended = body(await client.post(path + "/end", headers=h.headers()))
    assert ended["status"] == "ended"
    assert ended["billed_amount_cents"] == amount
    assert (
        body(await client.post(path + "/end", headers=h.headers()))["ended_at"] == ended["ended_at"]
    )
    assert (await client.get("/support/sessions/queue", headers=agents[0])).json() == []


async def test_rejected_support_session_stays_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    agents: list[dict[str, str]],
) -> None:
    h = hr_workspace
    h.hr.role = "admin"
    await db_session.flush()
    body(await client.patch("/support/config", headers=h.headers(), json={"enabled": True}))
    session = body(
        await client.post("/support/sessions", headers=h.headers(), json={"subject": "Frage"}), 201
    )
    path = f'/support/sessions/{session["id"]}'
    assert body(await client.post(path + "/reject", headers=agents[0]))["status"] == "rejected"
    assert body(await client.post(path + "/end", headers=h.headers()))["status"] == "rejected"
    assert (await client.post(path + "/accept", headers=agents[0])).status_code == 400


@pytest.mark.parametrize(
    "path",
    ["/support/sessions", "/support/sessions/queue", "/support/widget-config", "/support/config"],
)
async def test_workers_cannot_access_recruiter_support(
    client: AsyncClient,
    hr_workspace: HRWorkspace,
    path: str,
) -> None:
    assert (await client.get(path, headers=hr_workspace.headers("worker"))).status_code == 403
