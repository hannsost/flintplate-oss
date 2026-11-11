"""Real database workflows for recruiting and cross-company access boundaries."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.interviews.models import InterviewSchedule
from app.jobs.models import JobPosting
from app.profiles.models import CandidateProfile, Skill
from app.security import create_access_token
from app.users.models import User
from tests.hr_support import HRWorkspace, body
from tests.utils import auth_headers


@pytest.fixture(autouse=True)
def no_embedding_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.jobs.router._embed_new_jobs", AsyncMock())


async def vacancy(client: AsyncClient, h: HRWorkspace) -> str:
    job = body(
        await client.post(
            "/jobs/recruiter",
            headers=h.headers(),
            json={
                "title": "Python Engineer",
                "company": "Synthetic HR",
                "required_skills": ["Python"],
                "description": "Entwicklung und Wartung unserer Software.",
                "location": "Berlin",
                "employment_type": "full-time",
            },
        ),
        201,
    )
    await publish_vacancy(client, h, str(job["id"]))
    return str(job["id"])


async def publish_vacancy(client: AsyncClient, h: HRWorkspace, job_id: str) -> None:
    job = body(await client.get(f"/jobs/recruiter/{job_id}", headers=h.headers()))
    body(
        await client.post(
            f"/jobs/recruiter/{job_id}/publication/publish",
            headers=h.headers(),
            json={
                "expected_version": job["version"],
                "rights_confirmed": True,
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
        )
    )


async def application(client: AsyncClient, h: HRWorkspace, job: str) -> str:
    data = body(await client.post(f"/jobs/{job}/apply", headers=h.headers("worker")), 201)
    return str(data["application_id"])


async def test_recruiter_job_application_and_reporting_lifecycle(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
) -> None:
    h = hr_workspace
    h.worker.full_name = "=1+1"
    await db_session.flush()
    job = await vacancy(client, h)
    saved = await db_session.get(JobPosting, uuid.UUID(job))
    assert saved is not None and saved.tenant_id == h.hr.tenant_id
    assert (
        body(await client.get(f"/jobs/recruiter/{job}", headers=h.headers()))["title"]
        == "Python Engineer"
    )
    assert (
        await client.get(f"/jobs/recruiter/{job}", headers=h.headers("other_hr"))
    ).status_code == 403
    assert (
        body(
            await client.patch(
                f"/jobs/recruiter/{job}",
                headers=h.headers(),
                json={"title": "Senior Python Engineer", "expected_version": 2},
            )
        )["title"]
        == "Senior Python Engineer"
    )
    await publish_vacancy(client, h, job)
    app_id = await application(client, h, job)
    assert (await client.post(f"/jobs/{job}/apply", headers=h.headers("worker"))).status_code == 409
    applications = body(
        await client.get(f"/jobs/recruiter/{job}/applications", headers=h.headers())
    )
    assert applications["total"] == 1
    assert applications["applications"][0]["id"] == app_id
    assert (
        body(await client.get("/jobs/recruiter/applications", headers=h.headers("other_hr")))[
            "total"
        ]
        == 0
    )
    updated = body(
        await client.patch(
            f"/jobs/recruiter/{job}/applications/{app_id}",
            headers=h.headers(),
            json={"status": "interview", "note": "Interview vereinbaren"},
        )
    )
    assert updated["status"] == "interview"
    report = await client.get("/jobs/recruiter/applications/export", headers=h.headers())
    assert report.status_code == 200
    rows = list(csv.reader(io.StringIO(report.content.decode("utf-8-sig"))))
    assert rows[1][0] == "'=1+1"
    analytics = body(await client.get("/jobs/recruiter/analytics", headers=h.headers()))
    assert analytics["funnel"]["interview"] == 1
    assert (
        await client.delete(
            f"/jobs/recruiter/{job}?expected_version=4", headers=h.headers("other_hr")
        )
    ).status_code == 403
    assert (
        await client.delete(f"/jobs/recruiter/{job}?expected_version=4", headers=h.headers())
    ).status_code == 409
    body(
        await client.post(
            f"/jobs/recruiter/{job}/publication/archive",
            headers=h.headers(),
            json={"expected_version": 4},
        )
    )


async def test_candidate_visibility_requires_employment_or_application(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
) -> None:
    h = hr_workspace
    external = User(
        email=f"external-{uuid.uuid4().hex}@example.com", hashed_password="unused", role="candidate"
    )
    db_session.add(external)
    await db_session.flush()
    for user in (h.worker, h.other_worker, external):
        profile = CandidateProfile(user_id=user.id, headline="Python Engineer", location="Berlin")
        db_session.add(profile)
        await db_session.flush()
        db_session.add(Skill(profile_id=profile.id, name="Python"))
    await db_session.flush()
    own_id, other_id, external_id = map(str, (h.worker.id, h.other_worker.id, external.id))
    external_headers = auth_headers(create_access_token({"sub": external.email}))
    job = await vacancy(client, h)
    search = "/jobs/recruiter/candidates?skills=Python&location=Berlin&query=Engineer"
    before = body(await client.get(search, headers=h.headers()))
    assert [c["user_id"] for c in before["candidates"]] == [own_id]
    for hidden in (other_id, external_id):
        assert (
            await client.get(f"/jobs/recruiter/candidates/{hidden}/profile", headers=h.headers())
        ).status_code == 404
    assert (
        body(await client.get(f"/jobs/recruiter/{job}/candidates", headers=h.headers()))["total"]
        == 1
    )
    body(await client.post(f"/jobs/{job}/apply", headers=external_headers), 201)
    after = body(await client.get(search, headers=h.headers()))
    assert {c["user_id"] for c in after["candidates"]} == {own_id, external_id}
    assert (
        body(
            await client.get(
                f"/jobs/recruiter/candidates/{external_id}/profile", headers=h.headers()
            )
        )["email"]
        == external.email
    )
    assert (
        await client.get(
            f"/jobs/recruiter/candidates/{external_id}/profile", headers=h.headers("other_hr")
        )
    ).status_code == 404
    ranked = body(await client.get(f"/jobs/recruiter/{job}/candidates", headers=h.headers()))
    assert ranked["total"] == 2
    assert all(c["score"] == 100 for c in ranked["candidates"])


async def test_unassigned_recruiter_does_not_see_all_unassigned_candidates(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
) -> None:
    h = hr_workspace
    h.hr.tenant_id = None
    h.worker.tenant_id = None
    db_session.add(CandidateProfile(user_id=h.worker.id, headline="Hidden"))
    await db_session.flush()
    assert body(await client.get("/jobs/recruiter/candidates", headers=h.headers()))["total"] == 0
    assert (
        await client.get(f"/jobs/recruiter/candidates/{h.worker.id}/profile", headers=h.headers())
    ).status_code == 404


@pytest.mark.parametrize("role", ["recruiter", "admin"])
async def test_interview_lifecycle_and_cancellation_notifies_candidate(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    role: str,
) -> None:
    h = hr_workspace
    h.hr.role = role
    await db_session.flush()
    job = await vacancy(client, h)
    app_id = await application(client, h, job)
    path = f"/applications/{app_id}/interview"
    assert (await client.get(path, headers=h.headers())).json() is None
    proposed = body(
        await client.post(
            path,
            headers=h.headers(),
            json={"scheduled_at": "2027-01-15T10:00:00+01:00", "notes": "Kennenlernen"},
        ),
        201,
    )
    schedule = await db_session.get(InterviewSchedule, uuid.UUID(proposed["id"]))
    assert schedule is not None and schedule.tenant_id == h.hr.tenant_id
    assert body(await client.get(path, headers=h.headers("worker")))["status"] == "proposed"
    assert (
        body(await client.patch(path, headers=h.headers("worker"), json={"status": "confirmed"}))[
            "status"
        ]
        == "confirmed"
    )
    assert (
        len((await client.get("/applications/my-interviews", headers=h.headers("worker"))).json())
        == 1
    )
    score_path = f"/applications/{app_id}/scorecard"
    assert (await client.get(score_path, headers=h.headers())).json() is None
    for rating in (3, 4):
        assert (
            body(
                await client.put(
                    score_path,
                    headers=h.headers(),
                    json={"overall_rating": rating, "recommendation": "maybe"},
                )
            )["overall_rating"]
            == rating
        )
    assert body(await client.get(score_path, headers=h.headers()))["overall_rating"] == 4
    assert (
        body(await client.patch(path, headers=h.headers(), json={"status": "cancelled"}))["status"]
        == "cancelled"
    )
    assert (await client.get(path, headers=h.headers())).json() is None
    notifications = body(await client.get("/notifications/", headers=h.headers("worker")))
    assert any(n["type"] == "interview.cancelled" for n in notifications["notifications"])


@pytest.mark.parametrize("operation", ["propose", "view", "cancel", "score_read", "score_write"])
async def test_foreign_recruiter_cannot_access_interview_or_scorecard(
    client: AsyncClient,
    hr_workspace: HRWorkspace,
    operation: str,
) -> None:
    h = hr_workspace
    job = await vacancy(client, h)
    app_id = await application(client, h, job)
    path = f"/applications/{app_id}"
    body(
        await client.post(
            path + "/interview", headers=h.headers(), json={"scheduled_at": "2027-01-15T10:00:00Z"}
        ),
        201,
    )
    method, suffix, data = {
        "propose": ("POST", "/interview", {"scheduled_at": "2027-01-16T10:00:00Z"}),
        "view": ("GET", "/interview", None),
        "cancel": ("PATCH", "/interview", {"status": "cancelled"}),
        "score_read": ("GET", "/scorecard", None),
        "score_write": ("PUT", "/scorecard", {"overall_rating": 1}),
    }[operation]
    assert (
        await client.request(method, path + suffix, headers=h.headers("other_hr"), json=data)
    ).status_code == 404
    assert body(await client.get(path + "/interview", headers=h.headers()))["status"] == "proposed"


async def test_bookmarks_are_idempotent_and_alerts_are_private(
    client: AsyncClient,
    hr_workspace: HRWorkspace,
) -> None:
    h = hr_workspace
    job = await vacancy(client, h)
    for _ in range(2):
        body(await client.post(f"/jobs/{job}/save", headers=h.headers("worker")), 201)
    assert (await client.get("/jobs/saved/ids", headers=h.headers("worker"))).json() == [job]
    assert len((await client.get("/jobs/saved", headers=h.headers("worker"))).json()) == 1
    assert (await client.get("/jobs/saved/ids", headers=h.headers("other_worker"))).json() == []
    for _ in range(2):
        assert (
            await client.delete(f"/jobs/{job}/save", headers=h.headers("worker"))
        ).status_code == 204
    alert = body(
        await client.post(
            "/jobs/alerts",
            headers=h.headers("worker"),
            json={"keywords": "Python", "remote_only": True},
        ),
        201,
    )
    path = f'/jobs/alerts/{alert["id"]}'
    assert (await client.get("/jobs/alerts", headers=h.headers("worker"))).json()[0]["id"] == alert[
        "id"
    ]
    assert (await client.patch(path, headers=h.headers("other_worker"))).status_code == 404
    assert (await client.delete(path, headers=h.headers("other_worker"))).status_code == 404
    assert body(await client.patch(path, headers=h.headers("worker")))["is_active"] is False
    assert (await client.delete(path, headers=h.headers("worker"))).status_code == 204


async def test_interview_rejects_ambiguous_local_timestamp(
    client: AsyncClient,
    hr_workspace: HRWorkspace,
) -> None:
    h = hr_workspace
    job = await vacancy(client, h)
    app_id = await application(client, h, job)
    response = await client.post(
        f"/applications/{app_id}/interview",
        headers=h.headers(),
        json={"scheduled_at": "2027-01-15T10:00:00"},
    )
    assert response.status_code == 422


async def test_matching_fallback_includes_new_jobs_without_model_download(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    load_model = Mock(side_effect=AssertionError("Mock mode must not load or download models"))
    monkeypatch.setattr("app.jobs.embeddings._load_model", load_model)
    h = hr_workspace
    profile = CandidateProfile(user_id=h.worker.id, headline="Python Engineer")
    db_session.add(profile)
    await db_session.flush()
    db_session.add(Skill(profile_id=profile.id, name="Python"))
    await db_session.flush()
    job = await vacancy(client, h)
    feed = body(
        await client.get("/jobs/recommended?text_search=Python", headers=h.headers("worker"))
    )
    match = next(m for m in feed["jobs"] if m["job"]["id"] == job)
    assert match["score"] == 100
    assert match["explanation"]["matching_mode"] == "skills_only"
    assert match["explanation"]["vector_contribution"] == 0
    load_model.assert_not_called()
