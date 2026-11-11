"""Auth endpoint tests – Sprint 0.1.

Requires a running test-DB (see conftest.py / CI env vars).
Each test uses a unique email to avoid constraint conflicts across the test run.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.utils import auth_headers, register_and_login, register_user


def _email(label: str = "") -> str:
    """Generate a unique email per test to avoid UNIQUE constraint collisions."""
    return f"test-{label}-{uuid.uuid4().hex[:8]}@hireos.dev"


# ── 1. Register ────────────────────────────────────────────────────────────────


async def test_register_success(client: AsyncClient) -> None:
    response = await register_user(client, email=_email("reg"))
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_register_duplicate_email(client: AsyncClient) -> None:
    email = _email("dup")
    first = await register_user(client, email=email)
    assert first.status_code == 201

    second = await register_user(client, email=email)
    assert second.status_code == 409
    assert "registriert" in second.json()["detail"].lower()


# ── 2. Login ───────────────────────────────────────────────────────────────────


async def test_login_success(client: AsyncClient) -> None:
    email = _email("login")
    password = "LoginPass99!"
    await register_user(client, email=email, password=password)

    response = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient) -> None:
    email = _email("wrongpw")
    await register_user(client, email=email, password="CorrectPass1!")

    response = await client.post(
        "/auth/login",
        data={"username": email, "password": "WrongPass999!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 401


# ── 3. Refresh ─────────────────────────────────────────────────────────────────


async def test_refresh_token(client: AsyncClient) -> None:
    email = _email("refresh")
    tokens = await register_and_login(client, email=email)
    old_access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    response = await client.post("/auth/refresh", json={"refresh_token": refresh})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["access_token"] != old_access  # new token issued


# ── 4. /users/me ───────────────────────────────────────────────────────────────


async def test_get_me_authenticated(client: AsyncClient) -> None:
    email = _email("me")
    tokens = await register_and_login(client, email=email)
    access = tokens["access_token"]

    response = await client.get("/users/me", headers=auth_headers(access))
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == email
    assert "id" in data


async def test_get_me_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/users/me")
    assert response.status_code == 401


# ── 5. /users/consent ─────────────────────────────────────────────────────────


async def test_consent_update(client: AsyncClient) -> None:
    email = _email("consent")
    tokens = await register_and_login(client, email=email)
    access = tokens["access_token"]

    response = await client.patch(
        "/users/consent",
        json={"ai_opt_in": True, "terms_accepted": True},
        headers=auth_headers(access),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ai_opt_in"] is True
    assert data["terms_accepted"] is True
    assert data["ai_opt_in_at"] is not None  # timestamp gesetzt
    assert data["terms_accepted_at"] is not None


async def test_consent_revoke_ai_opt_in(client: AsyncClient) -> None:
    """DSGVO: ai_opt_in_at muss None sein nach Widerruf."""
    email = _email("revoke")
    tokens = await register_and_login(client, email=email)
    access = tokens["access_token"]
    headers = auth_headers(access)

    # Erst einwilligen
    await client.patch(
        "/users/consent",
        json={"ai_opt_in": True, "terms_accepted": True},
        headers=headers,
    )

    # Dann widerrufen
    response = await client.patch(
        "/users/consent",
        json={"ai_opt_in": False, "terms_accepted": True},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ai_opt_in"] is False
    assert data["ai_opt_in_at"] is None  # DSGVO: Timestamp gelöscht
