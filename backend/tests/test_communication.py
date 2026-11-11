"""Communication boundaries, OAuth lifecycle and booking conflict regression tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application, ApplicationStatus
from app.integrations import providers
from app.integrations.models import AuthorizationRequest, WorkspaceConnection
from app.interviews.models import InterviewSchedule
from app.jobs.models import JobPosting
from app.users.models import User
from tests.hr_support import HRWorkspace

BASE = "/companies/workspace"


@pytest.fixture
def provider_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTEGRATIONS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INTEGRATIONS_REDIRECT_URI", "http://localhost:3001/connections/callback")
    for name in ["GOOGLE", "MICROSOFT"]:
        monkeypatch.setenv(f"{name}_OAUTH_CLIENT_ID", "synthetic-client")
        monkeypatch.setenv(f"{name}_OAUTH_CLIENT_SECRET", "synthetic-secret")


async def connection(db: AsyncSession, user: User, provider: str = "google") -> WorkspaceConnection:
    value = WorkspaceConnection(
        user_id=user.id,
        tenant_id=user.tenant_id,
        provider=provider,
        email=user.email,
        access_cipher=providers.seal("synthetic-access"),
        refresh_cipher=providers.seal("synthetic-refresh"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(value)
    await db.flush()
    return value


async def application(db: AsyncSession, hr: User, candidate: User) -> Application:
    job = JobPosting(
        title="Synthetic booking role", company="Tests", owner_id=hr.id, tenant_id=hr.tenant_id
    )
    db.add(job)
    await db.flush()
    record = Application(
        user_id=candidate.id,
        job_id=job.id,
        company="Tests",
        position=job.title,
        status=ApplicationStatus.APPLIED,
    )
    db.add(record)
    await db.flush()
    return record


async def test_unconfigured_connections_are_explicit_and_do_not_authorize(
    client: AsyncClient, hr_workspace: HRWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    result = await client.get(f"{BASE}/connections", headers=hr_workspace.headers())
    assert result.status_code == 200, result.text
    assert result.json()[0]["configured"] is False
    assert (
        await client.post(f"{BASE}/connections/google/authorize", headers=hr_workspace.headers())
    ).status_code == 503
    assert (
        await client.get(f"{BASE}/connections", headers=hr_workspace.headers("worker"))
    ).status_code == 403


@pytest.mark.usefixtures("provider_config")
async def test_oauth_state_is_bound_one_use_and_credentials_are_encrypted(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = await client.post(
        f"{BASE}/connections/google/authorize", headers=hr_workspace.headers()
    )
    assert issued.status_code == 200, issued.text
    query = parse_qs(urlparse(issued.json()["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    state = query["state"][0]
    request = (await db_session.execute(select(AuthorizationRequest))).scalar_one()
    assert request.state_digest != state
    assert len(providers.unseal(request.verifier_cipher)) >= 43
    monkeypatch.setattr(
        providers,
        "exchange",
        AsyncMock(
            return_value=providers.Tokens(
                access_token="synthetic-access", refresh_token="synthetic-refresh"
            )
        ),
    )
    monkeypatch.setattr(providers, "account_email", AsyncMock(return_value="connected@example.com"))
    assert (
        await client.post(
            f"{BASE}/connections/callback",
            headers=hr_workspace.headers("other_hr"),
            json={"state": state, "code": "code"},
        )
    ).status_code == 410
    response = await client.post(
        f"{BASE}/connections/callback",
        headers=hr_workspace.headers(),
        json={"state": state, "code": "code"},
    )
    assert response.status_code == 200, response.text
    assert "synthetic-access" not in response.text
    stored = (await db_session.execute(select(WorkspaceConnection))).scalar_one()
    assert stored.access_cipher != "synthetic-access"
    assert providers.unseal(stored.access_cipher) == "synthetic-access"
    assert (
        await client.post(
            f"{BASE}/connections/callback",
            headers=hr_workspace.headers(),
            json={"state": state, "code": "code"},
        )
    ).status_code == 410
    other = (
        await client.get(f"{BASE}/connections", headers=hr_workspace.headers("other_hr"))
    ).json()
    assert all(not item["connected"] for item in other)
    # Disconnect also invalidates an authorization that has not returned yet.
    pending = (
        await client.post(f"{BASE}/connections/google/authorize", headers=hr_workspace.headers())
    ).json()
    pending_state = parse_qs(urlparse(pending["url"]).query)["state"][0]
    assert (
        await client.delete(f"{BASE}/connections/google", headers=hr_workspace.headers())
    ).status_code == 204
    assert (
        await client.post(
            f"{BASE}/connections/callback",
            headers=hr_workspace.headers(),
            json={"state": pending_state, "code": "code"},
        )
    ).status_code == 410


@pytest.mark.usefixtures("provider_config")
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_messages_require_preview_confirmation_and_never_send_twice(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    ambiguous: bool,
) -> None:
    await connection(db_session, hr_workspace.hr)
    send = AsyncMock(
        side_effect=providers.IntegrationError("Temporary failure") if ambiguous else None,
        return_value="remote-message",
    )
    monkeypatch.setattr(providers, "send_email", send)
    data = {
        "person_id": str(hr_workspace.worker.id),
        "subject": "Interview",
        "body": "Bitte wähle einen Termin.",
    }
    draft = await client.post(f"{BASE}/messages", headers=hr_workspace.headers(), json=data)
    assert draft.status_code == 201, draft.text
    message_id = draft.json()["id"]
    assert send.await_count == 0
    assert (
        await client.get(
            f"{BASE}/messages?person_id={hr_workspace.worker.id}",
            headers=hr_workspace.headers("other_hr"),
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"{BASE}/messages/{message_id}", headers=hr_workspace.headers("other_hr"), json=data
        )
    ).status_code == 404
    exported = await client.get(f"{BASE}/messages/{message_id}/eml", headers=hr_workspace.headers())
    assert exported.status_code == 200
    assert "Subject: Interview" in exported.text
    assert (
        await client.post(
            f"{BASE}/messages/{message_id}/send",
            headers=hr_workspace.headers(),
            json={"provider": "google", "confirmed": False},
        )
    ).status_code == 422
    sent = await client.post(
        f"{BASE}/messages/{message_id}/send",
        headers=hr_workspace.headers(),
        json={"provider": "google", "confirmed": True},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == ("unknown" if ambiguous else "accepted")
    assert (
        await client.post(
            f"{BASE}/messages/{message_id}/send",
            headers=hr_workspace.headers(),
            json={"provider": "google", "confirmed": True},
        )
    ).status_code == 409
    assert send.await_count == 1
    assert (
        await client.delete(f"{BASE}/messages/{message_id}", headers=hr_workspace.headers())
    ).status_code == 409


async def test_drafts_can_be_edited_and_deleted_but_not_redirected(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    headers = hr_workspace.headers()
    data = {"person_id": str(hr_workspace.worker.id), "subject": "Draft", "body": "Hello"}
    bad = await client.post(
        f"{BASE}/messages",
        headers=headers,
        json={**data, "subject": "Injected\r\nBcc: hidden@example.com"},
    )
    assert bad.status_code == 422
    created = await client.post(f"{BASE}/messages", headers=headers, json=data)
    identifier = created.json()["id"]
    assert (
        await client.patch(
            f"{BASE}/messages/{identifier}",
            headers=headers,
            json={**data, "person_id": str(hr_workspace.other_worker.id)},
        )
    ).status_code == 409
    edited = await client.patch(
        f"{BASE}/messages/{identifier}", headers=headers, json={**data, "body": "Updated"}
    )
    assert edited.json()["body"] == "Updated"
    assert (
        await client.post(
            f"{BASE}/messages/{identifier}/send",
            headers=headers,
            json={"provider": "google", "confirmed": True},
        )
    ).status_code == 409
    assert (
        await client.delete(f"{BASE}/messages/{identifier}", headers=headers)
    ).status_code == 204


async def test_candidate_books_available_slot_once_and_other_users_cannot(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    app = await application(db_session, hr_workspace.hr, hr_workspace.worker)
    slot = datetime.now(UTC) + timedelta(days=2)
    issued = await client.post(
        f"{BASE}/bookings",
        headers=hr_workspace.headers(),
        json={"application_id": str(app.id), "slots": [slot.isoformat()], "duration_minutes": 45},
    )
    assert issued.status_code == 201, issued.text
    secret = issued.json()["token"]
    assert (
        await client.post(
            f"{BASE}/bookings/preview",
            headers=hr_workspace.headers("other_worker"),
            json={"token": secret},
        )
    ).status_code == 403
    preview = await client.post(
        f"{BASE}/bookings/preview", headers=hr_workspace.headers("worker"), json={"token": secret}
    )
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["slots"]) == 1
    assert (
        await client.post(
            f"{BASE}/bookings/reserve",
            headers=hr_workspace.headers(),
            json={"token": secret, "scheduled_at": slot.isoformat()},
        )
    ).status_code == 403
    reserved = await client.post(
        f"{BASE}/bookings/reserve",
        headers=hr_workspace.headers("worker"),
        json={"token": secret, "scheduled_at": slot.isoformat()},
    )
    assert reserved.status_code == 201, reserved.text
    schedule = await db_session.get(InterviewSchedule, uuid.UUID(reserved.json()["schedule_id"]))
    assert schedule and schedule.duration_minutes == 45 and schedule.status == "confirmed"
    assert (
        await client.post(
            f"{BASE}/bookings/reserve",
            headers=hr_workspace.headers("worker"),
            json={"token": secret, "scheduled_at": slot.isoformat()},
        )
    ).status_code == 409
    assert (
        await client.get(f"{BASE}/bookings?application_id={app.id}", headers=hr_workspace.headers())
    ).json()[0]["booked_at"]


@pytest.mark.usefixtures("provider_config")
async def test_busy_calendars_fail_closed_and_bookings_can_be_revoked(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await connection(db_session, hr_workspace.hr)
    app = await application(db_session, hr_workspace.hr, hr_workspace.worker)
    slot = datetime.now(UTC) + timedelta(days=2)
    busy = AsyncMock(return_value=[(slot, slot + timedelta(hours=1))])
    monkeypatch.setattr(providers, "busy_intervals", busy)
    data = {"application_id": str(app.id), "slots": [slot.isoformat()]}
    assert (
        await client.post(f"{BASE}/bookings", headers=hr_workspace.headers(), json=data)
    ).status_code == 409
    busy.side_effect = providers.IntegrationError("Calendar unavailable")
    assert (
        await client.post(f"{BASE}/bookings", headers=hr_workspace.headers(), json=data)
    ).status_code == 503
    busy.side_effect, busy.return_value = None, []
    issued = await client.post(f"{BASE}/bookings", headers=hr_workspace.headers(), json=data)
    assert issued.status_code == 201, issued.text
    secret = issued.json()["token"]
    # A newly busy slot disappears when the candidate opens the invitation.
    busy.return_value = [(slot, slot + timedelta(hours=1))]
    assert (
        await client.post(
            f"{BASE}/bookings/preview",
            headers=hr_workspace.headers("worker"),
            json={"token": secret},
        )
    ).json()["slots"] == []
    assert (
        await client.post(
            f"{BASE}/bookings/reserve",
            headers=hr_workspace.headers("worker"),
            json={"token": secret, "scheduled_at": slot.isoformat()},
        )
    ).status_code == 409
    assert (
        await client.delete(
            f"{BASE}/bookings/{issued.json()['id']}", headers=hr_workspace.headers()
        )
    ).status_code == 204
    assert (
        await client.post(
            f"{BASE}/bookings/preview",
            headers=hr_workspace.headers("worker"),
            json={"token": secret},
        )
    ).status_code == 410


@pytest.mark.usefixtures("provider_config")
async def test_calendar_delivery_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await connection(db_session, hr_workspace.hr)
    app = await application(db_session, hr_workspace.hr, hr_workspace.worker)
    schedule = InterviewSchedule(
        application_id=app.id,
        proposed_by=hr_workspace.hr.id,
        tenant_id=hr_workspace.hr.tenant_id,
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
        status="confirmed",
    )
    db_session.add(schedule)
    await db_session.flush()
    create = AsyncMock(return_value="remote-event")
    monkeypatch.setattr(providers, "create_event", create)
    update = AsyncMock()
    remove = AsyncMock()
    monkeypatch.setattr(providers, "update_event", update)
    monkeypatch.setattr(providers, "delete_event", remove)
    for _ in range(2):
        response = await client.post(
            f"{BASE}/calendar/{schedule.id}/sync",
            headers=hr_workspace.headers(),
            json={"provider": "google"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "confirmed"
    assert create.await_count == 1
    assert update.await_count == 1
    schedule.status = "cancelled"
    await db_session.flush()
    removed = await client.post(
        f"{BASE}/calendar/{schedule.id}/sync",
        headers=hr_workspace.headers(),
        json={"provider": "google"},
    )
    assert removed.status_code == 200 and removed.json()["status"] == "removed"
    assert remove.await_count == 1
    assert (
        await client.post(
            f"{BASE}/calendar/{schedule.id}/sync",
            headers=hr_workspace.headers("other_hr"),
            json={"provider": "google"},
        )
    ).status_code == 404


@pytest.mark.usefixtures("provider_config")
async def test_official_provider_payloads_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append((request.method, request.url.path))
        if request.method in {"PATCH", "DELETE"}:
            assert b"remote%2Fevent" in request.url.raw_path
            return httpx.Response(404 if request.method == "DELETE" else 200, json={"id": "event"})
        if request.url.path.endswith("/sendMail"):
            assert b'"contentType":"Text"' in request.content
            return httpx.Response(202)
        if request.url.path.endswith("/messages/send"):
            assert b'"raw":' in request.content
            return httpx.Response(200, json={"id": "message"})
        if request.url.path.endswith("/freeBusy"):
            return httpx.Response(200, json={"calendars": {"primary": {"busy": []}}})
        return httpx.Response(200, json={"id": "event"})

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(handle), **kwargs),
    )
    now = datetime.now(UTC)
    for provider in ["google", "microsoft"]:
        await providers.send_email(
            provider, "secret", "sender@example.com", "to@example.com", "Subject", "Body"
        )
        assert (
            await providers.create_event(
                provider, "secret", str(uuid.uuid4()), "Interview", now, now + timedelta(minutes=30)
            )
            == "event"
        )
        await providers.update_event(
            provider, "secret", "remote/event", "Updated", now, now + timedelta(minutes=30)
        )
        await providers.delete_event(provider, "secret", "remote/event")
    assert await providers.busy_intervals("google", "secret", now, now + timedelta(days=1)) == []
    assert len(captured) == 9


@pytest.mark.usefixtures("provider_config")
async def test_tokens_and_busy_payloads_are_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = httpx.AsyncClient
    payload: dict = {
        "access_token": "synthetic-access",
        "refresh_token": "synthetic-refresh",
        "scope": "User.Read https://graph.microsoft.com/Calendars.ReadWrite Mail.Send Mail.Read",
    }

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            assert (
                b"code_verifier=verifier" in request.content
                or b"grant_type=refresh_token" in request.content
            )
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(handle), **kwargs),
    )
    tokens = await providers.exchange("microsoft", code="code", verifier="verifier")
    assert tokens.access_token.get_secret_value() == "synthetic-access"
    assert "synthetic-access" not in repr(tokens)
    payload["scope"] = "User.Read"
    with pytest.raises(providers.IntegrationError, match="Rechte|rechte"):
        await providers.exchange("microsoft", code="code", verifier="verifier")
    await providers.exchange("microsoft", refresh_token="synthetic-refresh")
    now = datetime.now(UTC)
    for invalid in [
        None,
        [{"start": "bad", "end": "bad"}],
        [{"start": "2026-01-01T10:00:00", "end": "2026-01-01T11:00:00"}],
    ]:
        payload = {"calendars": {"primary": {"busy": invalid}}}
        with pytest.raises(providers.IntegrationError):
            await providers.busy_intervals("google", "secret", now, now + timedelta(days=1))
    payload = {
        "value": [
            {
                "showAs": "busy",
                "start": {"dateTime": "2026-01-01T10:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-01-01T11:00:00.0000000", "timeZone": "UTC"},
            }
        ]
    }
    result = await providers.busy_intervals("microsoft", "secret", now, now + timedelta(days=1))
    assert result[0][1] - result[0][0] == timedelta(hours=1)
    payload["@odata.nextLink"] = "more"
    with pytest.raises(providers.IntegrationError):
        await providers.busy_intervals("microsoft", "secret", now, now + timedelta(days=1))


async def test_manual_interviews_and_self_booking_share_conflict_checks(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    from fastapi import HTTPException

    from app.interviews.schemas import InterviewScheduleCreate
    from app.interviews.service import propose_interview

    app = await application(db_session, hr_workspace.hr, hr_workspace.worker)
    slot = datetime.now(UTC) + timedelta(days=3)
    data = {"application_id": str(app.id), "slots": [slot.isoformat()]}
    old = await client.post(f"{BASE}/bookings", headers=hr_workspace.headers(), json=data)
    issued = await client.post(f"{BASE}/bookings", headers=hr_workspace.headers(), json=data)
    assert (
        await client.post(
            f"{BASE}/bookings/preview",
            headers=hr_workspace.headers("worker"),
            json={"token": old.json()["token"]},
        )
    ).status_code == 410
    assert (
        await client.post(
            f"{BASE}/bookings/reserve",
            headers=hr_workspace.headers("worker"),
            json={"token": issued.json()["token"], "scheduled_at": slot.isoformat()},
        )
    ).status_code == 201
    with pytest.raises(HTTPException) as conflict:
        await propose_interview(
            db_session,
            app.id,
            hr_workspace.hr.id,
            InterviewScheduleCreate(scheduled_at=slot + timedelta(minutes=15)),
            hr_workspace.worker.id,
            app.position,
            hr_workspace.hr.tenant_id,
        )
    assert conflict.value.status_code == 409
    assert (
        await client.post(f"{BASE}/bookings", headers=hr_workspace.headers(), json=data)
    ).status_code == 409
    # Adjacent appointments are allowed; overlapping ones are not.
    await propose_interview(
        db_session,
        app.id,
        hr_workspace.hr.id,
        InterviewScheduleCreate(scheduled_at=slot + timedelta(minutes=30)),
        hr_workspace.worker.id,
        app.position,
        hr_workspace.hr.tenant_id,
    )
