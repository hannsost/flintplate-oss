"""Interview and live-support access with real database identities."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.applications.models import Application
from app.interviews.models import InterviewSchedule
from app.support.models import SupportSession
from app.ws.router import _identity, _room_access, _support_access
from tests.test_release_regressions import make_user
from tests.utils import auth_headers


async def test_websocket_uses_database_user_id_and_rejects_refresh_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, tokens = await make_user(client, db_session)
    assert await _identity(db_session, tokens["access_token"]) == (str(user.id), None, "candidate")
    assert await _identity(db_session, tokens["refresh_token"]) is None
    user.is_active = False
    await db_session.flush()
    assert await _identity(db_session, tokens["access_token"]) is None


async def test_support_signaling_requires_assigned_peer_consent_and_capability(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    requester, _ = await make_user(client, db_session, "recruiter")
    agent, _ = await make_user(client, db_session, "support")
    stranger, _ = await make_user(client, db_session, "support")
    tenant = Customer(name="Support test", slug=f"support-{uuid.uuid4().hex}", status="active")
    db_session.add(tenant)
    await db_session.flush()
    session = SupportSession(
        tenant_id=tenant.id,
        requester_id=requester.id,
        agent_id=agent.id,
        subject="Synthetic test",
        status="active",
        consent_given=True,
        dom_viewing_enabled=True,
    )
    db_session.add(session)
    await db_session.flush()
    sid = str(session.id)
    assert (
        await _support_access(db_session, sid, str(requester.id), "support.session_join")
        == "requester"
    )
    assert await _support_access(db_session, sid, str(agent.id), "support.session_join") == "agent"
    assert await _support_access(db_session, sid, str(stranger.id), "support.session_join") is None
    assert await _support_access(db_session, sid, str(agent.id), "support.control_keyboard") is None
    session.remote_control_enabled = True
    await db_session.flush()
    assert (
        await _support_access(db_session, sid, str(agent.id), "support.control_keyboard") == "agent"
    )
    assert (
        await _support_access(db_session, sid, str(requester.id), "support.control_keyboard")
        is None
    )
    session.consent_given = False
    await db_session.flush()
    assert await _support_access(db_session, sid, str(agent.id), "support.webrtc_offer") is None


async def test_interview_invites_candidate_without_opening_room_to_other_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    candidate, candidate_tokens = await make_user(client, db_session)
    recruiter, recruiter_tokens = await make_user(client, db_session, "recruiter")
    stranger, stranger_tokens = await make_user(client, db_session)
    tenant = Customer(name="Interview test", slug=f"interview-{uuid.uuid4().hex}", status="active")
    db_session.add(tenant)
    await db_session.flush()
    recruiter.tenant_id = tenant.id
    application = Application(
        user_id=candidate.id, company="Example", position="Developer", status="interview"
    )
    db_session.add(application)
    await db_session.flush()
    schedule = InterviewSchedule(
        application_id=application.id,
        proposed_by=recruiter.id,
        tenant_id=tenant.id,
        scheduled_at=datetime.now(UTC),
        status="confirmed",
    )
    db_session.add(schedule)
    await db_session.flush()
    base = "/interview-rooms"
    response = await client.get(
        f"{base}/by-schedule/{schedule.id}", headers=auth_headers(recruiter_tokens["access_token"])
    )
    assert response.status_code == 200, response.text
    room_id = response.json()["id"]
    assert not await _room_access(db_session, room_id, str(candidate.id), "interview.room_join")
    response = await client.post(
        f"{base}/{room_id}/join", headers=auth_headers(candidate_tokens["access_token"])
    )
    assert response.status_code == 200, response.text
    assert await _room_access(db_session, room_id, str(candidate.id), "interview.room_join")
    assert not await _room_access(db_session, room_id, str(stranger.id), "interview.room_join")
    for endpoint in [f"{base}/{room_id}", f"{base}/{room_id}/messages"]:
        assert (
            await client.get(endpoint, headers=auth_headers(stranger_tokens["access_token"]))
        ).status_code == 403
    assert (
        await client.post(
            f"{base}/{room_id}/end", headers=auth_headers(candidate_tokens["access_token"])
        )
    ).status_code == 403
    message = await client.post(
        f"{base}/{room_id}/messages",
        headers=auth_headers(candidate_tokens["access_token"]),
        json={"content": "Hallo Team"},
    )
    assert message.status_code == 201
    assert message.json()["sender_id"] == str(candidate.id)
    assert (
        await client.post(
            f"{base}/{room_id}/end", headers=auth_headers(recruiter_tokens["access_token"])
        )
    ).status_code == 200
    assert not await _room_access(db_session, room_id, str(candidate.id), "interview.webrtc_offer")
