"""Test helper utilities shared across test modules."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient, Response


async def register_user(
    client: AsyncClient,
    email: str = "test@hireos.dev",
    password: str = "TestPass123!",
    full_name: str = "Test User",
) -> Response:
    return await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )


async def login_user(
    client: AsyncClient,
    email: str = "test@hireos.dev",
    password: str = "TestPass123!",
) -> tuple[str, str]:
    """Login and return (access_token, refresh_token)."""
    response = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    data = response.json()
    return data["access_token"], data["refresh_token"]


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def register_and_login(
    client: AsyncClient,
    email: str = "test@hireos.dev",
    password: str = "TestPass123!",
    ai_consent: bool = False,
) -> dict[str, Any]:
    """Register a user and return full token response dict."""
    reg = await register_user(client, email, password)
    reg.raise_for_status()
    if ai_consent:
        consent = await client.patch(
            "/users/consent",
            json={"ai_opt_in": True, "terms_accepted": True},
            headers=auth_headers(reg.json()["access_token"]),
        )
        consent.raise_for_status()
    return reg.json()  # type: ignore[no-any-return]
