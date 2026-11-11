from __future__ import annotations

import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.gastro.models import FireFlintLink
from tests.hr_support import body
from tests.test_flintplate import Site

pytest_plugins = ["tests.test_flintplate"]


def configuration() -> dict:
    return {
        "org_id": str(uuid.uuid4()),
        "content_id": str(uuid.uuid4()),
        "expected_revision": 1,
        "version": 0,
        "access_token": "synthetic-access-credential",
        "refresh_token": "synthetic-refresh-credential",
    }


def setup(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "fireflint_base_url", "https://fireflint.invalid")
    monkeypatch.setattr(settings, "flintplate_connector_key", Fernet.generate_key().decode())
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "app.gastro.fireflint.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
async def test_fireflint_jwt_refresh_sync_and_explicit_publish(
    client: AsyncClient, site: Site, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    config = configuration()
    calls = []
    saved = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        data = json.loads(request.content)
        if request.url.path == "/auth/refresh":
            assert data == {"refresh_token": "synthetic-refresh-credential"}
            return httpx.Response(200, json={"access_token": "synthetic-new-access"})
        if request.headers["Authorization"] == "Bearer synthetic-access-credential":
            return httpx.Response(401)
        if request.method == "PUT":
            assert data["expected_revision"] == 1
            saved.update(data["data"])
            return httpx.Response(
                200,
                json={
                    "id": config["content_id"],
                    "org_id": config["org_id"],
                    "revision": 2,
                    "status": "draft",
                    "data": saved,
                },
            )
        assert request.url.path.endswith("/publish") and data == {"expected_revision": 2}
        return httpx.Response(
            200,
            json={
                "id": config["content_id"],
                "org_id": config["org_id"],
                "revision": 3,
                "status": "published",
                "data": saved,
            },
        )

    setup(monkeypatch, handler)
    link = body(await client.put(site.path("/fireflint"), headers=site.headers, json=config))
    assert "access_token" not in link and "refresh_ciphertext" not in link
    stored = (
        await db_session.execute(
            select(FireFlintLink).where(FireFlintLink.id == uuid.UUID(link["id"]))
        )
    ).scalar_one()
    assert stored.access_ciphertext != "synthetic-access-credential"
    synced = body(
        await client.post(
            site.path("/fireflint/sync"), headers=site.headers, json={"version": link["version"]}
        )
    )
    assert synced["status"] == "draft_synced" and synced["expected_revision"] == 2
    assert calls == [
        ("PUT", f"/api/orgs/{config['org_id']}/content/gastro_menu/{config['content_id']}"),
        ("POST", "/auth/refresh"),
        ("PUT", f"/api/orgs/{config['org_id']}/content/gastro_menu/{config['content_id']}"),
    ]
    assert saved["source_system"] == "flintplate" and len(saved["menu_revision"]) == 64
    assert "cost_cents" not in saved["items"][0]
    published = body(
        await client.post(
            site.path("/fireflint/publish"),
            headers=site.headers,
            json={"version": synced["version"]},
        )
    )
    assert published["status"] == "published" and published["expected_revision"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["conflict", "timeout", "wrong_object"])
async def test_fireflint_never_rebases_or_retries_unknown_write(
    client: AsyncClient, site: Site, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import json

    config = configuration()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failure == "conflict":
            return httpx.Response(409, json={"code": "revision_conflict", "current_revision": 22})
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(
            200,
            json={
                "id": str(uuid.uuid4()),
                "org_id": config["org_id"],
                "revision": 2,
                "status": "draft",
                "data": json.loads(request.content)["data"],
            },
        )

    setup(monkeypatch, handler)
    link = body(await client.put(site.path("/fireflint"), headers=site.headers, json=config))
    result = body(
        await client.post(
            site.path("/fireflint/sync"), headers=site.headers, json={"version": link["version"]}
        )
    )
    assert result["status"] == ("conflict" if failure == "conflict" else "uncertain")
    assert result["expected_revision"] == 1 and len(calls) == 1
    assert (
        await client.post(
            site.path("/fireflint/sync"), headers=site.headers, json={"version": result["version"]}
        )
    ).status_code == 409
    assert len(calls) == 1
