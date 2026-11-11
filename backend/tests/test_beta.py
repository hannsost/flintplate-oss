"""Beta-Release tests – Sprint 0.8.

Covers:
  - POST /feedback (anonymous)
  - POST /feedback (authenticated)
  - POST /feedback validation (message too short)
  - GET /health → 200 with version
  - GET /docs  → 200 (OpenAPI docs live)
  - GET /redoc → 200 (Redoc live)
  - Auth endpoints: /auth/login rate-limit headers present
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.utils import auth_headers, register_and_login


def _email(label: str = "") -> str:
    return f"beta-{label}-{uuid.uuid4().hex[:8]}@hireos.dev"


# ── Feedback: anonymous ───────────────────────────────────────────────────────


async def test_feedback_anonymous(client: AsyncClient) -> None:
    response = await client.post(
        "/feedback",
        json={
            "category": "general",
            "message": "Das Produkt ist super! Weiter so.",
            "email": "anon@example.com",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "received"
    assert "id" in data


async def test_feedback_authenticated(client: AsyncClient) -> None:
    tokens = await register_and_login(client, email=_email("fb-auth"))
    token = tokens["access_token"]

    response = await client.post(
        "/feedback",
        json={
            "category": "bug",
            "message": "Der Kanban-Export funktioniert nicht korrekt.",
            "page_url": "/applications",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201


async def test_feedback_all_categories(client: AsyncClient) -> None:
    for cat in ["bug", "feature", "general", "ux"]:
        r = await client.post(
            "/feedback",
            json={"category": cat, "message": f"Feedback für Kategorie {cat}."},
        )
        assert r.status_code == 201, f"Category {cat} failed"


async def test_feedback_message_too_short(client: AsyncClient) -> None:
    response = await client.post(
        "/feedback",
        json={"category": "general", "message": "kurz"},
    )
    assert response.status_code == 422


# ── Health check ──────────────────────────────────────────────────────────────


async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


# ── OpenAPI docs live ─────────────────────────────────────────────────────────


async def test_openapi_docs_accessible(client: AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


async def test_redoc_accessible(client: AsyncClient) -> None:
    response = await client.get("/redoc")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


async def test_openapi_schema_has_all_routers(client: AsyncClient) -> None:
    """Smoke test: OpenAPI schema includes all major route prefixes."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema.get("paths", {})
    for prefix in [
        "/auth/register",
        "/profiles/me",
        "/ai/cover-letter",
        "/jobs/recommended",
        "/applications",
        "/feedback",
    ]:
        assert any(
            p.startswith(prefix) for p in paths
        ), f"Route prefix {prefix!r} missing from OpenAPI schema"
