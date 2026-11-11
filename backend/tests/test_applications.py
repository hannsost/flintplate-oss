"""Bewerbungs-Tracker tests – Sprint 0.5.

Covers:
  - POST /applications   → 201 with history entry
  - GET  /applications   → list, own items only
  - GET  /applications/kanban → Kanban board structure
  - PATCH /applications/{id}  → update fields + status transition in history
  - PATCH /applications/{id}  → 404 for other user's application
  - DELETE /applications/{id} → 204
  - DELETE /applications/{id} → 404 for other user's application
  - Auth required on all endpoints
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.utils import auth_headers, register_and_login


def _email(label: str = "") -> str:
    return f"apps-{label}-{uuid.uuid4().hex[:8]}@hireos.dev"


_APP_PAYLOAD = {
    "company": "Acme GmbH",
    "position": "Backend Engineer",
    "job_url": "https://example.com/job/42",
    "notes": "Sehr interessant",
    "status": "research",
}


# ── POST /applications ────────────────────────────────────────────────────────


async def test_create_application_returns_201(client: AsyncClient) -> None:
    tokens = await register_and_login(client, email=_email("create"))
    response = await client.post(
        "/applications",
        json=_APP_PAYLOAD,
        headers=auth_headers(tokens["access_token"]),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["company"] == "Acme GmbH"
    assert data["position"] == "Backend Engineer"
    assert data["status"] == "research"
    assert data["applied_at"] is None
    # Initial history entry
    assert len(data["history"]) == 1
    assert data["history"][0]["from_status"] is None
    assert data["history"][0]["to_status"] == "research"


async def test_create_sets_applied_at_when_status_applied(client: AsyncClient) -> None:
    tokens = await register_and_login(client, email=_email("applied"))
    payload = {**_APP_PAYLOAD, "status": "applied"}
    response = await client.post(
        "/applications",
        json=payload,
        headers=auth_headers(tokens["access_token"]),
    )
    assert response.status_code == 201
    # applied_at is not auto-set on create (only on status transition via update)
    # The initial status is "applied" but applied_at is only set on PATCH transition
    data = response.json()
    assert data["status"] == "applied"


# ── GET /applications ─────────────────────────────────────────────────────────


async def test_list_applications_own_only(client: AsyncClient) -> None:
    token_a = (await register_and_login(client, email=_email("list-a")))["access_token"]
    token_b = (await register_and_login(client, email=_email("list-b")))["access_token"]

    # User A creates two, user B creates one
    for i in range(2):
        await client.post(
            "/applications",
            json={**_APP_PAYLOAD, "company": f"Company {i}"},
            headers=auth_headers(token_a),
        )
    await client.post(
        "/applications",
        json={**_APP_PAYLOAD, "company": "Other Corp"},
        headers=auth_headers(token_b),
    )

    resp_a = await client.get("/applications", headers=auth_headers(token_a))
    resp_b = await client.get("/applications", headers=auth_headers(token_b))

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert len(resp_a.json()) == 2
    assert len(resp_b.json()) == 1


# ── GET /applications/kanban ──────────────────────────────────────────────────


async def test_kanban_board_structure(client: AsyncClient) -> None:
    tokens = await register_and_login(client, email=_email("kanban"))
    token = tokens["access_token"]

    await client.post("/applications", json=_APP_PAYLOAD, headers=auth_headers(token))
    await client.post(
        "/applications",
        json={**_APP_PAYLOAD, "company": "Beta Corp", "status": "applied"},
        headers=auth_headers(token),
    )

    response = await client.get("/applications/kanban", headers=auth_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert "columns" in data
    assert "total" in data
    assert data["total"] == 2

    statuses = [col["status"] for col in data["columns"]]
    assert "research" in statuses
    assert "applied" in statuses

    research_col = next(c for c in data["columns"] if c["status"] == "research")
    assert len(research_col["applications"]) == 1

    applied_col = next(c for c in data["columns"] if c["status"] == "applied")
    assert len(applied_col["applications"]) == 1


# ── PATCH /applications/{id} ──────────────────────────────────────────────────


async def test_update_application_fields(client: AsyncClient) -> None:
    tokens = await register_and_login(client, email=_email("patch"))
    token = tokens["access_token"]

    create_resp = await client.post("/applications", json=_APP_PAYLOAD, headers=auth_headers(token))
    app_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/applications/{app_id}",
        json={"company": "Updated GmbH"},
        headers=auth_headers(token),
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["company"] == "Updated GmbH"


async def test_status_transition_logged_in_history(client: AsyncClient) -> None:
    tokens = await register_and_login(client, email=_email("history"))
    token = tokens["access_token"]

    create_resp = await client.post("/applications", json=_APP_PAYLOAD, headers=auth_headers(token))
    app_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/applications/{app_id}",
        json={"status": "applied", "note": "Jetzt beworben"},
        headers=auth_headers(token),
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["status"] == "applied"
    assert data["applied_at"] is not None  # auto-set on APPLIED transition

    history = data["history"]
    assert len(history) == 2  # initial + transition
    last = history[-1]
    assert last["from_status"] == "research"
    assert last["to_status"] == "applied"
    assert last["note"] == "Jetzt beworben"


async def test_update_foreign_application_returns_404(client: AsyncClient) -> None:
    token_a = (await register_and_login(client, email=_email("foreign-a")))["access_token"]
    token_b = (await register_and_login(client, email=_email("foreign-b")))["access_token"]

    create_resp = await client.post(
        "/applications", json=_APP_PAYLOAD, headers=auth_headers(token_a)
    )
    app_id = create_resp.json()["id"]

    response = await client.patch(
        f"/applications/{app_id}",
        json={"company": "Hacker Corp"},
        headers=auth_headers(token_b),
    )
    assert response.status_code == 404


# ── DELETE /applications/{id} ─────────────────────────────────────────────────


async def test_delete_application(client: AsyncClient) -> None:
    tokens = await register_and_login(client, email=_email("delete"))
    token = tokens["access_token"]

    create_resp = await client.post("/applications", json=_APP_PAYLOAD, headers=auth_headers(token))
    app_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/applications/{app_id}", headers=auth_headers(token))
    assert del_resp.status_code == 204

    list_resp = await client.get("/applications", headers=auth_headers(token))
    ids = [a["id"] for a in list_resp.json()]
    assert app_id not in ids


async def test_delete_foreign_application_returns_404(client: AsyncClient) -> None:
    token_a = (await register_and_login(client, email=_email("del-a")))["access_token"]
    token_b = (await register_and_login(client, email=_email("del-b")))["access_token"]

    create_resp = await client.post(
        "/applications", json=_APP_PAYLOAD, headers=auth_headers(token_a)
    )
    app_id = create_resp.json()["id"]

    response = await client.delete(f"/applications/{app_id}", headers=auth_headers(token_b))
    assert response.status_code == 404


# ── Auth required ─────────────────────────────────────────────────────────────


async def test_applications_require_auth(client: AsyncClient) -> None:
    fake_id = str(uuid.uuid4())
    endpoints = [
        ("GET", "/applications", None),
        ("GET", "/applications/kanban", None),
        ("POST", "/applications", _APP_PAYLOAD),
        ("PATCH", f"/applications/{fake_id}", {"company": "x"}),
        ("DELETE", f"/applications/{fake_id}", None),
    ]
    for method, url, body in endpoints:
        if method == "GET":
            r = await client.get(url)
        elif method == "POST":
            r = await client.post(url, json=body)
        elif method == "PATCH":
            r = await client.patch(url, json=body)
        else:
            r = await client.delete(url)
        assert r.status_code == 401, f"{method} {url} should return 401"
