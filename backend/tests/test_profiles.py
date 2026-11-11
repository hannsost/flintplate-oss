"""Profile endpoint tests – Sprint 0.2.

Covers:
  POST   /profiles                     → 201 created, 409 duplicate
  GET    /profiles/me                  → 200 (creates empty profile on first call)
  PATCH  /profiles/{id}                → 200 success, 403 wrong owner
  POST   /profiles/me/cv               → 200 with parse_status
"""

from __future__ import annotations

import io
import uuid

from httpx import AsyncClient

from tests.utils import auth_headers, register_and_login


def _email(label: str = "") -> str:
    return f"profile-{label}-{uuid.uuid4().hex[:8]}@hireos.dev"


async def _new_user(client: AsyncClient) -> str:
    """Register a fresh user and return the access token."""
    tokens = await register_and_login(client, email=_email())
    return tokens["access_token"]


# ── 1. POST /profiles ─────────────────────────────────────────────────────────


async def test_create_profile_201(client: AsyncClient) -> None:
    token = await _new_user(client)
    response = await client.post(
        "/profiles",
        json={"headline": "Senior Python Dev", "location": "Berlin"},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["headline"] == "Senior Python Dev"
    assert data["location"] == "Berlin"
    assert "id" in data
    assert "user_id" in data


async def test_create_profile_409_duplicate(client: AsyncClient) -> None:
    token = await _new_user(client)
    first = await client.post(
        "/profiles",
        json={"headline": "First"},
        headers=auth_headers(token),
    )
    assert first.status_code == 201

    second = await client.post(
        "/profiles",
        json={"headline": "Second"},
        headers=auth_headers(token),
    )
    assert second.status_code == 409
    assert "existiert bereits" in second.json()["detail"]


# ── 2. GET /profiles/me ───────────────────────────────────────────────────────


async def test_get_my_profile_creates_on_first_call(client: AsyncClient) -> None:
    token = await _new_user(client)
    response = await client.get("/profiles/me", headers=auth_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["headline"] is None  # empty profile
    assert data["skills"] == []
    assert data["work_experiences"] == []


async def test_get_my_profile_returns_existing(client: AsyncClient) -> None:
    token = await _new_user(client)
    await client.post(
        "/profiles",
        json={"headline": "Data Engineer"},
        headers=auth_headers(token),
    )
    response = await client.get("/profiles/me", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.json()["headline"] == "Data Engineer"


# ── 3. PATCH /profiles/{id} ───────────────────────────────────────────────────


async def test_patch_profile_success(client: AsyncClient) -> None:
    token = await _new_user(client)
    create_resp = await client.post(
        "/profiles",
        json={"headline": "Junior Dev"},
        headers=auth_headers(token),
    )
    profile_id = create_resp.json()["id"]

    response = await client.patch(
        f"/profiles/{profile_id}",
        json={"headline": "Senior Dev", "location": "Hamburg"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["headline"] == "Senior Dev"
    assert data["location"] == "Hamburg"


async def test_patch_profile_403_wrong_owner(client: AsyncClient) -> None:
    # User A creates profile
    token_a = await _new_user(client)
    create_resp = await client.post(
        "/profiles",
        json={"headline": "Owner A"},
        headers=auth_headers(token_a),
    )
    profile_id = create_resp.json()["id"]

    # User B tries to patch it
    token_b = await _new_user(client)
    response = await client.patch(
        f"/profiles/{profile_id}",
        json={"headline": "Hijacked"},
        headers=auth_headers(token_b),
    )
    assert response.status_code == 403


# ── 4. POST /profiles/me/cv ───────────────────────────────────────────────────


async def test_upload_cv_returns_parse_result(client: AsyncClient) -> None:
    token = await _new_user(client)
    consent = await client.patch(
        "/users/consent",
        json={"ai_opt_in": True, "terms_accepted": True},
        headers=auth_headers(token),
    )
    assert consent.status_code == 200
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake cv content for testing")
    response = await client.post(
        "/profiles/me/cv",
        files={"file": ("cv_test.pdf", fake_pdf, "application/pdf")},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["parse_status"] == "parsed"
    assert "profile" in data
    assert "extracted_fields" in data
    assert data["profile"]["cv_original_filename"] == "cv_test.pdf"
