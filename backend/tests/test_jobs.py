"""Job matching tests – Sprint 0.4.

Covers:
  - Score computation (weighted formula)
  - Skill overlap calculation
  - POST /jobs/seed + GET /jobs/recommended
  - POST /jobs/match
  - Embedding service (mock – no model download in CI)
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import create_access_token
from app.users.models import User
from tests.utils import auth_headers, register_and_login


def _email(label: str = "") -> str:
    return f"jobs-{label}-{uuid.uuid4().hex[:8]}@hireos.dev"


# ── Unit: score computation ───────────────────────────────────────────────────


def test_compute_match_score_perfect() -> None:
    from app.jobs.service import compute_match_score

    score, expl = compute_match_score(
        vector_sim=1.0,
        skill_ov=1.0,
        profile_skills=["Python"],
        job_skills=["Python"],
    )
    assert score == pytest.approx(100.0)
    assert expl["matched_skills"] == ["python"]
    assert expl["missing_skills"] == []


def test_compute_match_score_no_overlap() -> None:
    from app.jobs.service import compute_match_score

    score, expl = compute_match_score(
        vector_sim=0.0,  # neutral (maps to 0.5 after normalization)
        skill_ov=0.0,
        profile_skills=["Java"],
        job_skills=["Python"],
    )
    # vector contribution: 0.5 * 0.6 * 100 = 30, skill: 0 → total 30
    assert score == pytest.approx(30.0)
    assert "python" in expl["missing_skills"]


def test_skill_overlap_partial() -> None:
    from app.jobs.service import _skill_overlap

    overlap = _skill_overlap(
        job_skills=["Python", "Docker", "Kubernetes"],
        profile_skills=["Python", "Docker", "React"],
    )
    assert overlap == pytest.approx(2 / 3)


def test_skill_overlap_empty_job_skills() -> None:
    from app.jobs.service import _skill_overlap

    # No required skills → perfect match by default
    assert _skill_overlap([], ["Python"]) == pytest.approx(1.0)


def test_skill_overlap_case_insensitive() -> None:
    from app.jobs.service import _skill_overlap

    assert _skill_overlap(["python", "Docker"], ["PYTHON", "docker"]) == pytest.approx(1.0)


# ── Unit: cosine similarity ───────────────────────────────────────────────────


def test_cosine_similarity_identical() -> None:
    from app.jobs.embeddings import cosine_similarity

    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal() -> None:
    from app.jobs.embeddings import cosine_similarity

    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


# ── Integration: endpoints ────────────────────────────────────────────────────


async def seed_as_admin(client: AsyncClient, db: AsyncSession):
    admin = User(email=_email("admin"), hashed_password="unused", role="admin")
    db.add(admin)
    await db.flush()
    return await client.post(
        "/jobs/seed", headers=auth_headers(create_access_token({"sub": admin.email}))
    )


async def test_seed_jobs(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await seed_as_admin(client, db_session)
    assert response.status_code == 201
    data = response.json()
    assert data["seeded"] > 0


async def test_recommended_jobs_returns_feed(client: AsyncClient, db_session: AsyncSession) -> None:
    tokens = await register_and_login(client, email=_email("rec"))
    token = tokens["access_token"]

    # Seed some jobs first
    await seed_as_admin(client, db_session)

    response = await client.get("/jobs/recommended", headers=auth_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert "total" in data
    assert isinstance(data["jobs"], list)
    # Each job has a score
    for item in data["jobs"]:
        assert "score" in item
        assert 0.0 <= item["score"] <= 100.0


async def test_recommendations_remain_available_when_profile_embedding_is_slow(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import router

    cancelled = asyncio.Event()

    async def slow_embedding(**kwargs: object) -> list[float]:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return []

    monkeypatch.setattr("app.jobs.embeddings.embed_profile", slow_embedding)
    monkeypatch.setattr(router, "PROFILE_EMBED_BUDGET_SECONDS", 0.01)
    tokens = await register_and_login(client, email=_email("cold-model"))
    await seed_as_admin(client, db_session)
    response = await client.get("/jobs/recommended", headers=auth_headers(tokens["access_token"]))
    assert response.status_code == 200 and cancelled.is_set()
    results = response.json()["jobs"]
    assert results
    assert all(result["explanation"]["matching_mode"] == "skills_only" for result in results)
    assert all(result["vector_similarity"] == 0 for result in results)


async def test_recommended_remote_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    tokens = await register_and_login(client, email=_email("remote"))
    token = tokens["access_token"]
    await seed_as_admin(client, db_session)

    response = await client.get(
        "/jobs/recommended?remote_only=true",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    for item in response.json()["jobs"]:
        assert item["job"]["is_remote"] is True


async def test_match_single_job(client: AsyncClient, db_session: AsyncSession) -> None:
    tokens = await register_and_login(client, email=_email("match"))
    token = tokens["access_token"]

    seed = await seed_as_admin(client, db_session)
    assert seed.status_code == 201

    # Get a job id from the feed
    feed = await client.get("/jobs/recommended?page_size=1", headers=auth_headers(token))
    jobs = feed.json()["jobs"]
    assert jobs, "Seeded published jobs must appear in the feed"

    job_id = jobs[0]["job"]["id"]
    response = await client.post(
        "/jobs/match",
        json={"job_id": job_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert "explanation" in data
    assert 0.0 <= data["score"] <= 100.0


async def test_jobs_require_auth(client: AsyncClient) -> None:
    r1 = await client.get("/jobs/recommended")
    r2 = await client.post("/jobs/match", json={"job_id": str(uuid.uuid4())})
    assert r1.status_code == 401
    assert r2.status_code == 401
