"""Publication boundaries exercised against PostgreSQL and the real API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.jobs.models import JobPosting
from tests.hr_support import HRWorkspace, body


@pytest.fixture(autouse=True)
def no_embedding_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.jobs.router._embed_new_jobs", AsyncMock())


async def draft(client: AsyncClient, h: HRWorkspace) -> dict:
    return body(
        await client.post(
            "/jobs/recruiter",
            headers=h.headers(),
            json={
                "title": "Publication QA Engineer",
                "company": "Synthetic Publication",
                "location": "Berlin",
                "description": "Qualitätssicherung für unsere Softwareprodukte.",
                "employment_type": "full-time",
                "required_skills": ["Python"],
            },
        ),
        201,
    )


async def publish(client: AsyncClient, h: HRWorkspace, job: dict) -> dict:
    return body(
        await client.post(
            f'/jobs/recruiter/{job["id"]}/publication/publish',
            headers=h.headers(),
            json={
                "expected_version": job["version"],
                "rights_confirmed": True,
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
        )
    )


async def assert_hidden(client: AsyncClient, h: HRWorkspace, job: dict, slug: str) -> None:
    jid = job["id"]
    assert (await client.get(f"/public/jobs/{jid}?slug={slug}")).status_code == 404
    assert all(j["id"] != jid for j in (await client.get(f"/public/jobs?slug={slug}")).json())
    feed = body(
        await client.get("/jobs/recommended?text_search=Publication", headers=h.headers("worker"))
    )
    assert all(item["job"]["id"] != jid for item in feed["jobs"])
    assert (await client.post(f"/jobs/{jid}/apply", headers=h.headers("worker"))).status_code == 404
    assert (await client.post(f"/jobs/{jid}/save", headers=h.headers("worker"))).status_code == 404
    assert (
        await client.post(
            "/applications",
            headers=h.headers("worker"),
            json={
                "job_id": jid,
                "company": "Synthetic",
                "position": "QA",
            },
        )
    ).status_code == 404
    assert (
        await client.post("/jobs/match", headers=h.headers("worker"), json={"job_id": jid})
    ).status_code == 404


async def test_publication_lifecycle_hides_drafts_and_retains_application_history(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
) -> None:
    h = hr_workspace
    tenant = await db_session.get(Customer, h.hr.tenant_id)
    assert tenant
    job = await draft(client, h)
    assert job["publication_status"] == "draft" and job["version"] == 1
    await assert_hidden(client, h, job, tenant.slug)
    job = await publish(client, h, job)
    assert job["publication_status"] == "published" and job["version"] == 2
    assert (await client.get(f'/public/jobs/{job["id"]}?slug={tenant.slug}')).status_code == 200
    body(await client.post(f'/jobs/{job["id"]}/save', headers=h.headers("worker")), 201)
    app = body(await client.post(f'/jobs/{job["id"]}/apply', headers=h.headers("worker")), 201)
    path = f'/jobs/recruiter/{job["id"]}'
    assert (
        await client.patch(
            path, headers=h.headers(), json={"expected_version": 1, "title": "Stale"}
        )
    ).status_code == 409
    job = body(
        await client.patch(
            path,
            headers=h.headers(),
            json={
                "expected_version": 2,
                "description": "Überarbeitete Stelle mit aktualisierten Aufgaben.",
            },
        )
    )
    assert job["publication_status"] == "draft" and job["version"] == 3
    assert (await client.get("/jobs/saved", headers=h.headers("worker"))).json() == []
    assert (await client.get("/jobs/saved/ids", headers=h.headers("worker"))).json() == []
    await assert_hidden(client, h, job, tenant.slug)
    job = await publish(client, h, job)
    assert (await client.get("/jobs/saved/ids", headers=h.headers("worker"))).json() == [job["id"]]
    job = body(
        await client.post(
            path + "/publication/archive",
            headers=h.headers(),
            json={"expected_version": job["version"]},
        )
    )
    assert job["publication_status"] == "archived"
    await assert_hidden(client, h, job, tenant.slug)
    applications = body(await client.get(path + "/applications", headers=h.headers()))
    assert applications["applications"][0]["id"] == app["application_id"]
    assert (
        await client.delete(path + f'?expected_version={job["version"]}', headers=h.headers())
    ).status_code == 409
    assert (
        await client.patch(
            path, headers=h.headers(), json={"expected_version": job["version"], "title": "Reopen"}
        )
    ).status_code == 409
    events = (await client.get(path + "/publication-events", headers=h.headers())).json()
    assert [e["action"] for e in events] == ["archive", "publish", "edit", "publish"]
    assert (
        await client.get(path + "/publication-events", headers=h.headers("other_hr"))
    ).status_code == 403


@pytest.mark.parametrize("cause", ["expired", "suspended", "moved", "inactive", "role_revoked"])
async def test_public_visibility_rechecks_time_and_current_owner(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    cause: str,
) -> None:
    h = hr_workspace
    tenant = await db_session.get(Customer, h.hr.tenant_id)
    assert tenant
    slug = tenant.slug
    job = await publish(client, h, await draft(client, h))
    row = await db_session.get(JobPosting, uuid.UUID(job["id"]))
    assert row
    if cause == "expired":
        row.published_at = datetime.now(UTC) - timedelta(days=2)
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
    elif cause == "suspended":
        tenant.status = "suspended"
    elif cause == "moved":
        h.hr.tenant_id = h.other_hr.tenant_id
    elif cause == "inactive":
        h.hr.is_active = False
    else:
        h.hr.role = "worker"
    await db_session.flush()
    assert (await client.get(f'/public/jobs/{job["id"]}')).status_code == 404
    if cause != "suspended":
        await assert_hidden(client, h, job, slug)
    stats = body(await client.get("/jobs/market/stats", headers=h.headers("worker")))
    assert stats["total_jobs"] == 0
    if cause == "moved":
        assert (
            await client.get(f'/jobs/recruiter/{job["id"]}', headers=h.headers())
        ).status_code == 403
        assert body(await client.get("/jobs/recruiter", headers=h.headers()))["jobs"] == []


@pytest.mark.parametrize(
    "invalid",
    [
        "rights",
        "missing_date",
        "naive_date",
        "past_date",
        "too_long",
        "stale",
        "unknown_action",
        "foreign",
        "worker",
    ],
)
async def test_invalid_publication_does_not_change_draft(
    client: AsyncClient,
    hr_workspace: HRWorkspace,
    invalid: str,
) -> None:
    h = hr_workspace
    job = await draft(client, h)
    payload = {
        "expected_version": 1,
        "rights_confirmed": True,
        "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }
    expected = 422
    who = "hr"
    action = "publish"
    if invalid == "rights":
        payload["rights_confirmed"] = False
    elif invalid == "missing_date":
        payload.pop("expires_at")
    elif invalid == "naive_date":
        payload["expires_at"] = "2027-01-01T12:00:00"
    elif invalid == "past_date":
        payload["expires_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    elif invalid == "too_long":
        payload["expires_at"] = (datetime.now(UTC) + timedelta(days=181)).isoformat()
    elif invalid == "stale":
        payload["expected_version"] = 4
        expected = 409
    elif invalid == "unknown_action":
        action = "autopublish"
    elif invalid == "foreign":
        who = "other_hr"
        expected = 403
    elif invalid == "worker":
        who = "worker"
        expected = 403
    path = f'/jobs/recruiter/{job["id"]}'
    assert (
        await client.post(path + f"/publication/{action}", headers=h.headers(who), json=payload)
    ).status_code == expected
    unchanged = body(await client.get(path, headers=h.headers()))
    assert unchanged["publication_status"] == "draft" and unchanged["version"] == 1


async def test_import_review_is_platform_only_and_source_withdrawal_preserves_rows(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "scraper_import_key", "synthetic-import-key")
    headers = {"X-Import-Key": "synthetic-import-key"}
    h = hr_workspace
    own = await draft(client, h)
    own_row = await db_session.get(JobPosting, uuid.UUID(own["id"]))
    assert own_row
    own_row.external_id = "protected-owned-job"
    await db_session.flush()
    body(
        await client.post(
            "/jobs/import",
            headers=headers,
            json={
                "jobs": [
                    {
                        "title": "Import QA",
                        "company": "Synthetic",
                        "source": "licensed-feed",
                        "external_id": "import-qa",
                        "url": "https://example.com/jobs/qa",
                        "description": "Synthetic QA role",
                        "is_remote": True,
                        "employment_type": "full-time",
                    }
                ]
            },
        )
    )
    imported = await db_session.scalar(
        select(JobPosting).where(JobPosting.external_id == "import-qa")
    )
    assert imported and imported.publication_status == "draft"
    path = f"/jobs/import-review/{imported.id}/publication/publish"
    data = {
        "expected_version": 1,
        "rights_confirmed": True,
        "expires_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
    }
    assert (await client.get("/jobs/import-review", headers=h.headers())).status_code == 403
    h.hr.role = "admin"
    await db_session.flush()
    assert (await client.post(path, headers=h.headers(), json=data)).status_code == 403
    h.hr.tenant_id = None
    await db_session.flush()
    edit_path = f"/jobs/import-review/{imported.id}"
    edit = {"expected_version": 1, "title": "Import QA geprüft", "description": "Ergänzte Angaben"}
    assert (
        await client.patch(edit_path, headers=h.headers("other_hr"), json=edit)
    ).status_code == 403
    edited = body(await client.patch(edit_path, headers=h.headers(), json=edit))
    assert edited["title"] == "Import QA geprüft" and edited["publication_status"] == "draft"
    assert edited["version"] == 2
    assert (await client.patch(edit_path, headers=h.headers(), json=edit)).status_code == 409
    data["expected_version"] = 2
    assert (await client.post(path, headers=h.headers(), json=data)).status_code == 422
    data["note"] = "Synthetischer Lizenznachweis für den Test."
    body(await client.post(path, headers=h.headers(), json=data))
    assert len((await client.get("/jobs/import-review", headers=h.headers())).json()) == 1
    result = body(
        await client.request(
            "DELETE",
            "/jobs/import",
            headers=headers,
            json={"external_ids": ["protected-owned-job", "import-qa"]},
        )
    )
    assert result["removed"] == 1
    await db_session.refresh(imported)
    await db_session.refresh(own_row)
    assert imported.publication_status == "archived" and own_row.publication_status == "draft"
    monkeypatch.setattr(get_settings(), "scraper_import_key", "")
    assert (
        await client.post("/jobs/import", headers={"X-Import-Key": ""}, json={"jobs": []})
    ).status_code == 401


async def test_seed_requires_platform_admin_and_development_environment(
    client: AsyncClient,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    assert (
        await client.post("/jobs/seed", headers=hr_workspace.headers("worker"))
    ).status_code == 403
    monkeypatch.setattr(get_settings(), "app_env", "production")
    assert (await client.post("/jobs/seed", headers=hr_workspace.headers())).status_code == 404
