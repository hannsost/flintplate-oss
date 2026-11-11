"""Regression coverage for defects found during the PalmSCOUT release audit."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer, CustomerModule
from app.config import Settings
from app.security import create_access_token, decode_token
from app.users.models import User
from tests.utils import auth_headers, register_and_login


def test_compose_only_configuration_does_not_break_api() -> None:
    settings = Settings(_env_file=None, secret_key="test-only-key", POSTGRES_USER="test")
    assert settings.secret_key == "test-only-key"


async def make_user(
    client: AsyncClient, db: AsyncSession, role: str = "candidate"
) -> tuple[User, dict[str, str]]:
    email = f"release-{uuid.uuid4().hex}@example.com"
    tokens = await register_and_login(client, email=email)
    user = await db.scalar(select(User).where(User.email == email))
    assert user is not None
    user.role = role
    await db.flush()
    return user, tokens


async def test_refresh_preserves_current_role_and_tenant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, tokens = await make_user(client, db_session, "recruiter")
    tenant = Customer(
        name="Test HR", slug=f"test-{uuid.uuid4().hex}", plan="enterprise", status="active"
    )
    db_session.add(tenant)
    await db_session.flush()
    user.tenant_id = tenant.id
    await db_session.flush()
    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    payload = decode_token(response.json()["access_token"])
    assert payload["role"] == "recruiter"
    assert payload["tenant_id"] == str(tenant.id)
    assert response.json()["refresh_token"] != tokens["refresh_token"]


async def test_disabled_user_cannot_refresh(client: AsyncClient, db_session: AsyncSession) -> None:
    user, tokens = await make_user(client, db_session)
    user.is_active = False
    await db_session.flush()
    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


@pytest.mark.parametrize("password", ["", "short", "x" * 73])
async def test_password_reset_rejects_invalid_passwords(client: AsyncClient, password: str) -> None:
    response = await client.post(
        "/auth/reset-password", json={"token": "invalid", "new_password": password}
    )
    assert response.status_code == 422


async def test_ai_consent_is_required_and_revocation_takes_effect(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.generators import cover_letter

    generator = AsyncMock()
    monkeypatch.setattr(cover_letter, "generate_cover_letter", generator)
    tokens = await register_and_login(client, email=f"consent-{uuid.uuid4().hex}@example.com")
    headers = auth_headers(tokens["access_token"])
    payload = {"company": "Test HR", "position": "Developer", "tone": "professionell"}
    response = await client.post("/ai/cover-letter", headers=headers, json=payload)
    assert response.status_code == 403
    generator.assert_not_awaited()
    for consent in [True, False]:
        response = await client.patch(
            "/users/consent", headers=headers, json={"ai_opt_in": consent, "terms_accepted": True}
        )
        assert response.status_code == 200
    response = await client.post("/ai/cover-letter", headers=headers, json=payload)
    assert response.status_code == 403
    generator.assert_not_awaited()
    assert (await client.get("/ai/cover-letters", headers=headers)).status_code == 200


@pytest.mark.parametrize("route", ["/maps/data", "/zeitarbeit/pool", "/zeitarbeit/assignments"])
async def test_recruiter_without_tenant_cannot_read_business_data(
    client: AsyncClient, db_session: AsyncSession, route: str
) -> None:
    _, tokens = await make_user(client, db_session, "recruiter")
    response = await client.get(route, headers=auth_headers(tokens["access_token"]))
    assert response.status_code == 403


async def test_admin_stats_accept_real_module_keys(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, tokens = await make_user(client, db_session, "admin")
    tenant = Customer(
        name="Test HR", slug=f"test-{uuid.uuid4().hex}", plan="enterprise", status="active"
    )
    db_session.add(tenant)
    await db_session.flush()
    db_session.add(
        CustomerModule(customer_id=tenant.id, module_key="kanban_pipeline", enabled=True)
    )
    await db_session.flush()
    response = await client.get("/admin/stats", headers=auth_headers(tokens["access_token"]))
    assert response.status_code == 200
    assert {"module_key": "kanban_pipeline", "count": 1} in response.json()["top_modules"]


async def test_recruiter_interview_list_handles_empty_result(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, tokens = await make_user(client, db_session, "recruiter")
    response = await client.get(
        "/jobs/recruiter/interviews", headers=auth_headers(tokens["access_token"])
    )
    assert response.status_code == 200


def test_tokens_issued_in_same_second_are_unique() -> None:
    first = create_access_token({"sub": "test@example.com"})
    second = create_access_token({"sub": "test@example.com"})
    assert first != second


@pytest.mark.parametrize(
    "workspace_type", ["internal_hr", "recruiter_agency", "solo_recruiter", "zeitarbeit"]
)
async def test_company_onboarding_creates_isolated_usable_workspace(
    client: AsyncClient, db_session: AsyncSession, workspace_type: str
) -> None:
    user, tokens = await make_user(client, db_session)
    headers = auth_headers(tokens["access_token"])
    response = await client.post(
        "/companies/",
        headers=headers,
        json={"name": "Example HR", "workspace_type": workspace_type},
    )
    assert response.status_code == 201, response.text
    me = (await client.get("/users/me", headers=headers)).json()
    assert me["role"] == "admin"
    assert me["company_id"] == response.json()["id"]
    assert me["tenant_id"]
    workspace = (await client.get("/users/workspace", headers=headers)).json()
    assert workspace["id"] == me["tenant_id"]
    assert workspace["type"] == workspace_type
    assert workspace["status"] == "trial"
    assert workspace["trial_ends_at"]
    assert set(workspace) == {"id", "name", "type", "status", "trial_ends_at"}
    assert "kanban_pipeline" in (await client.get("/users/my-modules", headers=headers)).json()
    assert (await client.get("/zeitarbeit/assignments", headers=headers)).status_code == 200
    assert (
        await client.post("/companies/", headers=headers, json={"name": "Another Company"})
    ).status_code == 409
    # A second account must receive a different organization even with the same company name.
    _, other_tokens = await make_user(client, db_session)
    other_headers = auth_headers(other_tokens["access_token"])
    assert (
        await client.post("/companies/", headers=other_headers, json={"name": "Example HR"})
    ).status_code == 201
    other_workspace = (await client.get("/users/workspace", headers=other_headers)).json()
    assert other_workspace["id"] != me["tenant_id"]


async def test_worker_cannot_promote_self_through_company_onboarding(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, tokens = await make_user(client, db_session, "worker")
    headers = auth_headers(tokens["access_token"])
    response = await client.post("/companies/", headers=headers, json={"name": "Example HR"})
    assert response.status_code == 403
    assert (await client.get("/users/me", headers=headers)).json()["role"] == "worker"


@pytest.mark.parametrize(
    "restriction", ["suspended", "expired_trial", "expired_module", "usage_limit"]
)
async def test_module_access_respects_workspace_lifecycle(
    client: AsyncClient, db_session: AsyncSession, restriction: str
) -> None:
    from datetime import UTC, datetime, timedelta

    user, tokens = await make_user(client, db_session, "recruiter")
    tenant = Customer(
        name="Test HR", slug=f"test-{uuid.uuid4().hex}", plan="enterprise", status="active"
    )
    db_session.add(tenant)
    await db_session.flush()
    user.tenant_id = tenant.id
    module = CustomerModule(customer_id=tenant.id, module_key="ai_cv_parser", enabled=True)
    db_session.add(module)
    await db_session.flush()
    headers = auth_headers(tokens["access_token"])
    assert (await client.get("/users/my-modules", headers=headers)).json() == ["ai_cv_parser"]
    past = datetime.now(UTC) - timedelta(days=1)
    if restriction == "suspended":
        tenant.status = "suspended"
    elif restriction == "expired_trial":
        tenant.status = "trial"
        tenant.trial_ends_at = past
    elif restriction == "expired_module":
        module.expires_at = past
    else:
        module.usage_limit = 2
        module.usage_current = 2
    await db_session.flush()
    assert (await client.get("/users/my-modules", headers=headers)).json() == []


async def test_refresh_token_can_only_be_used_once(client: AsyncClient) -> None:
    tokens = await register_and_login(client, email=f"refresh-{uuid.uuid4().hex}@example.com")
    payload = {"refresh_token": tokens["refresh_token"]}
    first = await client.post("/auth/refresh", json=payload)
    assert first.status_code == 200
    assert (await client.post("/auth/refresh", json=payload)).status_code == 401
    assert (
        await client.post("/auth/refresh", json={"refresh_token": first.json()["refresh_token"]})
    ).status_code == 200


async def test_password_change_invalidates_access_and_refresh_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, tokens = await make_user(client, db_session)
    headers = auth_headers(tokens["access_token"])
    assert (
        await client.patch("/users/me", headers=headers, json={"password": "ChangedPassword123!"})
    ).status_code == 200
    assert (await client.get("/users/me", headers=headers)).status_code == 401
    assert (
        await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401
    login = await client.post(
        "/auth/login", data={"username": user.email, "password": "ChangedPassword123!"}
    )
    assert login.status_code == 200
    assert (
        await client.get("/users/me", headers=auth_headers(login.json()["access_token"]))
    ).status_code == 200


@pytest.mark.parametrize("password", ["x" * 73, "ü" * 37, "🔒" * 19])
async def test_registration_rejects_passwords_bcrypt_would_truncate(
    client: AsyncClient, password: str
) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": f"long-{uuid.uuid4().hex}@example.com", "password": password},
    )
    assert response.status_code == 422
