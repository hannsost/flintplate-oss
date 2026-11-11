"""Document management and organization charts with isolated organizations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dms.models import DocCategory
from tests.hr_support import HRWorkspace, body


@pytest.fixture(autouse=True)
def mock_document_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.dms.router._safe_process", AsyncMock())


def document_payload(name: str = "Contract") -> dict:
    return {
        "name": name,
        "original_filename": "contract.pdf",
        "file_url": "https://files.example.com/contract.pdf",
        "mime_type": "application/pdf",
        "file_size": 1024,
    }


async def test_document_lifecycle_search_comments_sharing_and_expiry(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    category = body(
        await client.post(
            "/documents/categories",
            headers=h.headers(),
            json={"name": "Contracts", "slug": "contracts"},
        ),
        201,
    )
    payload = {
        **document_payload("Manager's guide"),
        "category_id": category["id"],
        "linked_entity_type": "worker",
        "linked_entity_id": str(h.worker.id),
    }
    doc = body(await client.post("/documents", headers=h.headers(), json=payload), 201)
    path = f'/documents/{doc["id"]}'
    assert body(await client.get(path, headers=h.headers()))["category"]["id"] == category["id"]
    assert (await client.get(path, headers=h.headers("other_hr"))).status_code == 404
    for who in ("worker", "other_worker"):
        assert (await client.get(path, headers=h.headers(who))).status_code == 403
    assert len((await client.get("/worker/documents", headers=h.headers("worker"))).json()) == 1
    assert (await client.get("/worker/documents", headers=h.headers("other_worker"))).json() == []
    found = await client.get("/documents", headers=h.headers(), params={"q": "Manager's guide"})
    assert found.status_code == 200, found.text
    assert len(found.json()) == 1
    assert (
        await client.get("/documents", headers=h.headers(), params={"q": "' OR true --"})
    ).json() == []
    comment = body(
        await client.post(
            path + "/comments", headers=h.headers(), json={"content": "Bitte prüfen"}
        ),
        201,
    )
    assert len((await client.get(path + "/comments", headers=h.headers())).json()) == 1
    assert (
        await client.delete(path + f'/comments/{comment["id"]}', headers=h.headers())
    ).status_code == 204
    expires = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    body(
        await client.patch(
            path, headers=h.headers(), json={"expires_at": expires, "category_id": category["id"]}
        )
    )
    assert (
        len(body(await client.get("/documents/expiry", headers=h.headers()))["expiring_soon"]) == 1
    )
    share = body(
        await client.post(path + "/shares", headers=h.headers(), json={"access_type": "view"}), 201
    )
    shared_path = f'/public/documents/{share["share_token"]}'
    assert body(await client.get(shared_path))["name"] == "Manager's guide"
    assert (
        await client.delete(path + f'/shares/{share["id"]}', headers=h.headers())
    ).status_code == 204
    assert (await client.get(shared_path)).status_code == 404
    assert body(await client.post(path + "/archive", headers=h.headers()))["status"] == "archived"
    assert (await client.get("/documents", headers=h.headers())).json() == []
    assert body(await client.post(path + "/restore", headers=h.headers()))["status"] == "active"
    assert len((await client.get(path + "/activity", headers=h.headers())).json()) >= 5
    assert (await client.delete(path, headers=h.headers())).status_code == 204
    assert (await client.get("/worker/documents", headers=h.headers("worker"))).json() == []
    assert (
        body(
            await client.patch(
                f'/documents/categories/{category["id"]}',
                headers=h.headers(),
                json={"name": "Unterlagen"},
            )
        )["name"]
        == "Unterlagen"
    )
    assert (
        await client.delete(f'/documents/categories/{category["id"]}', headers=h.headers())
    ).status_code == 204


async def test_document_version_history_includes_every_version(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    payload = {
        **document_payload(),
        "linked_entity_type": "worker",
        "linked_entity_id": str(h.worker.id),
    }
    first = body(await client.post("/documents", headers=h.headers(), json=payload), 201)
    second = body(
        await client.post(
            f'/documents/{first["id"]}/new-version', headers=h.headers(), json=payload
        ),
        201,
    )
    third = body(
        await client.post(
            f'/documents/{second["id"]}/new-version', headers=h.headers(), json=payload
        ),
        201,
    )
    for doc in (first, second, third):
        versions = (
            await client.get(f'/documents/{doc["id"]}/versions', headers=h.headers())
        ).json()
        assert [v["version_number"] for v in versions] == [1, 2, 3]
        assert [v["id"] for v in versions if v["is_latest_version"]] == [third["id"]]
    assert [
        d["id"] for d in (await client.get("/worker/documents", headers=h.headers("worker"))).json()
    ] == [third["id"]]


async def test_document_cannot_reference_foreign_category_or_worker(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    category = DocCategory(tenant_id=h.other_hr.tenant_id, name="Private category", slug="private")
    db_session.add(category)
    await db_session.flush()
    assert (
        await client.post(
            "/documents",
            headers=h.headers(),
            json={**document_payload(), "category_id": str(category.id)},
        )
    ).status_code == 404
    assert (
        await client.post(
            "/documents",
            headers=h.headers(),
            json={
                **document_payload(),
                "linked_entity_type": "worker",
                "linked_entity_id": str(h.other_worker.id),
            },
        )
    ).status_code == 404


async def test_orgchart_save_load_update_and_delete(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    chart = body(
        await client.post("/org-charts", headers=h.headers(), json={"name": "HR structure"}), 201
    )
    path = f'/org-charts/{chart["id"]}'
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    payload = {
        "nodes": [
            {"id": a, "title": "Team lead", "person_id": str(h.hr.id)},
            {"id": b, "title": "Team member", "person_id": str(h.worker.id)},
        ],
        "edges": [{"source_id": a, "target_id": b}],
    }
    saved = body(await client.put(path + "/save", headers=h.headers(), json=payload))
    assert saved["node_count"] == 2
    assert len(saved["edges"]) == 1
    assert body(await client.get(path, headers=h.headers()))["node_count"] == 2
    assert (await client.get("/org-charts", headers=h.headers())).json()[0]["node_count"] == 2
    assert (await client.get(path, headers=h.headers("other_hr"))).status_code == 404
    assert (
        body(await client.patch(path, headers=h.headers(), json={"name": "People team"}))["name"]
        == "People team"
    )
    assert (await client.delete(path, headers=h.headers())).status_code == 204
    assert (await client.get("/org-charts", headers=h.headers())).json() == []


@pytest.mark.parametrize("operation", ["read", "save", "delete"])
async def test_worker_cannot_manage_company_orgcharts(
    client: AsyncClient, hr_workspace: HRWorkspace, operation: str
) -> None:
    h = hr_workspace
    chart = body(
        await client.post("/org-charts", headers=h.headers(), json={"name": "HR structure"}), 201
    )
    path = f'/org-charts/{chart["id"]}'
    method, path, payload = {
        "read": ("GET", path, None),
        "save": ("PUT", path + "/save", {"nodes": [], "edges": []}),
        "delete": ("DELETE", path, None),
    }[operation]
    assert (
        await client.request(method, path, headers=h.headers("worker"), json=payload)
    ).status_code == 403


async def test_invalid_chart_save_preserves_existing_structure(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    chart = body(
        await client.post("/org-charts", headers=h.headers(), json={"name": "Valid chart"}), 201
    )
    path = f'/org-charts/{chart["id"]}'
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    body(
        await client.put(
            path + "/save",
            headers=h.headers(),
            json={"nodes": [{"id": a, "title": "Existing role"}], "edges": []},
        )
    )
    invalid = {
        "nodes": [{"id": a, "title": "Changed role"}],
        "edges": [{"source_id": a, "target_id": b}],
    }
    assert (await client.put(path + "/save", headers=h.headers(), json=invalid)).status_code == 422
    assert body(await client.get(path, headers=h.headers()))["nodes"][0]["title"] == "Existing role"
    invalid = {
        "nodes": [{"id": a, "title": "Foreign person", "person_id": str(h.other_worker.id)}],
        "edges": [],
    }
    assert (await client.put(path + "/save", headers=h.headers(), json=invalid)).status_code == 404
