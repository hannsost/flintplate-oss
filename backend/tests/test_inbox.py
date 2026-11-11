"""Mailbox previews are private, bounded and tied to the selected person."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import providers
from app.integrations.inbox import mailbox_previews
from tests.hr_support import HRWorkspace
from tests.test_communication import connection

BASE = "/companies/workspace"


@pytest.fixture
def provider_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTEGRATIONS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INTEGRATIONS_REDIRECT_URI", "http://localhost:3001/connections/callback")
    for name in ["GOOGLE", "MICROSOFT"]:
        monkeypatch.setenv(f"{name}_OAUTH_CLIENT_ID", "synthetic-client")
        monkeypatch.setenv(f"{name}_OAUTH_CLIENT_SECRET", "synthetic-secret")


async def test_google_previews_filter_sender_and_ignore_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    api = AsyncMock(
        side_effect=[
            {
                "messages": [{"id": "first"}, {"id": "other"}, {"id": "old"}],
                "nextPageToken": "more",
            },
            {
                "id": "first",
                "internalDate": str(int(now.timestamp() * 1000)),
                "snippet": "Danke &amp; bis bald",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Candidate <person@example.com>"},
                        {"name": "Subject", "value": "Interview"},
                    ]
                },
            },
            {
                "id": "other",
                "internalDate": str(int(now.timestamp() * 1000)),
                "snippet": "PRIVATE unrelated sender",
                "payload": {"headers": [{"name": "From", "value": "other@example.com"}]},
            },
            {
                "id": "old",
                "internalDate": str(int((now - timedelta(days=100)).timestamp() * 1000)),
                "snippet": "Old mail",
                "payload": {"headers": [{"name": "From", "value": "person@example.com"}]},
            },
        ]
    )
    monkeypatch.setattr(providers, "api", api)
    result = await mailbox_previews("google", "synthetic", "person@example.com")
    assert result.limited is True
    assert len(result.messages) == 1 and result.messages[0].preview == "Danke & bis bald"
    assert "PRIVATE" not in result.model_dump_json()
    assert all("format=metadata" in call.args[1] for call in api.await_args_list[1:])


async def test_microsoft_previews_are_bounded_and_invalid_answers_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC).isoformat()
    payload = {
        "value": [
            {
                "id": "one",
                "subject": "Next steps",
                "bodyPreview": "Available next week",
                "receivedDateTime": now,
                "from": {"emailAddress": {"address": "person@example.com"}},
            },
            {
                "id": "two",
                "subject": "Private",
                "receivedDateTime": now,
                "from": {"emailAddress": {"address": "other@example.com"}},
            },
        ],
        "@odata.nextLink": "more",
    }
    api = AsyncMock(return_value=payload)
    monkeypatch.setattr(providers, "api", api)
    result = await mailbox_previews("microsoft", "synthetic", "person@example.com")
    assert result.limited and len(result.messages) == 1
    assert result.messages[0].subject == "Next steps"
    api.return_value = {"value": [{"subject": "Malformed"}]}
    with pytest.raises(providers.IntegrationError):
        await mailbox_previews("microsoft", "synthetic", "person@example.com")
    api.side_effect = TimeoutError
    with pytest.raises(providers.IntegrationError):
        await mailbox_previews("google", "synthetic", "person@example.com")


@pytest.mark.usefixtures("provider_config")
async def test_inbox_uses_only_the_callers_connection_and_person_visibility(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await connection(db_session, hr_workspace.hr)
    api = AsyncMock(return_value={"messages": []})
    monkeypatch.setattr(providers, "api", api)
    path = f"{BASE}/messages/inbox?provider=google&person_id={hr_workspace.worker.id}"
    assert (await client.get(path, headers=hr_workspace.headers("other_hr"))).status_code == 404
    assert api.await_count == 0
    response = await client.get(path, headers=hr_workspace.headers())
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["messages"] == []
    assert (await client.get(path, headers=hr_workspace.headers("worker"))).status_code == 403


@pytest.mark.usefixtures("provider_config")
async def test_rotated_credentials_survive_a_later_business_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    from sqlalchemy import delete, select

    from app.admin.models import Customer
    from app.integrations.models import RecruitingMessage, WorkspaceConnection
    from app.integrations.router import active_connection
    from app.users.models import User
    from tests.conftest import TestSessionLocal

    # Independent committed setup is required to observe the transaction boundary.
    async with TestSessionLocal() as setup:
        tenant = Customer(name="OAuth rollback test", slug=uuid.uuid4().hex)
        setup.add(tenant)
        await setup.flush()
        user = User(
            email=f"refresh-{uuid.uuid4().hex}@example.com",
            hashed_password="unused",
            role="recruiter",
            tenant_id=tenant.id,
        )
        setup.add(user)
        await setup.flush()
        stored = await connection(setup, user)
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        user_id, connection_id, tenant_id = user.id, stored.id, tenant.id
        await setup.commit()
    try:
        exchange = AsyncMock(
            return_value=providers.Tokens(
                access_token="rotated-access", refresh_token="rotated-refresh"
            )
        )
        monkeypatch.setattr(providers, "exchange", exchange)
        async with TestSessionLocal() as business:
            user = await business.get(User, user_id)
            assert user
            draft = RecruitingMessage(
                tenant_id=user.tenant_id,
                person_id=user.id,
                author_id=user.id,
                recipient=user.email,
                subject="Rolled back",
                body="Unsaved business operation",
                status="draft",
            )
            business.add(draft)
            await business.flush()
            draft_id = draft.id
            _, token = await active_connection(business, user, "google")
            assert token == "rotated-access"
            await business.rollback()
        async with TestSessionLocal() as probe:
            stored = (
                await probe.execute(
                    select(WorkspaceConnection).where(WorkspaceConnection.id == connection_id)
                )
            ).scalar_one()
            assert providers.unseal(stored.refresh_cipher) == "rotated-refresh"
            assert await probe.get(RecruitingMessage, draft_id) is None
    finally:
        async with TestSessionLocal() as cleanup:
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.execute(delete(Customer).where(Customer.id == tenant_id))
            await cleanup.commit()
