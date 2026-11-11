"""Interview prep + export tests – Sprint 0.7.

Covers:
  - generate_interview_prep() curated fallback (unit)
  - STAR tip present on behavioral questions (unit)
  - POST /ai/interview-prep → 200 with questions
  - POST /ai/interview-prep → 404 for unknown job_id
  - GET /profiles/me/export/linkedin → 200 with text
  - GET /profiles/me/export/link    → 200 with url
  - GET /profiles/me/export/docx    → 200 binary DOCX
  - Auth required on all new endpoints
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.utils import auth_headers, register_and_login


def _email(label: str = "") -> str:
    return f"ip-{label}-{uuid.uuid4().hex[:8]}@hireos.dev"


_PREP_PAYLOAD = {
    "company": "TechCorp GmbH",
    "position": "Senior Python Developer",
    "job_description": "Wir suchen einen erfahrenen Python-Entwickler mit FastAPI und Docker.",
}


# ── Unit: curated fallback ────────────────────────────────────────────────────


async def test_interview_prep_curated_fallback() -> None:
    from app.ai.generators.interview_prep import generate_interview_prep

    result = await generate_interview_prep(
        profile_data={
            "headline": "Python Developer",
            "skills": [{"name": "Python"}, {"name": "Docker"}],
            "work_experiences": [],
        },
        company="Acme",
        position="Backend Engineer",
        job_description="Python, Docker, AWS",
        required_skills=["Python", "Docker"],
    )
    assert result.ai_generated is True
    assert len(result.questions) >= 5
    assert len(result.general_tips) >= 2

    # Behavioral questions must have STAR tips
    behavioral = [q for q in result.questions if q.category == "behavioral"]
    for q in behavioral:
        assert q.star_tip is not None, f"Missing STAR tip for: {q.question}"


def test_interview_prep_technical_questions_use_skills() -> None:
    from app.ai.generators.interview_prep import _technical_questions_for_skills

    questions = _technical_questions_for_skills(["Python", "FastAPI"], "Backend Engineer")
    texts = [q.question for q in questions]
    assert any("Python" in t or "FastAPI" in t for t in texts)


# ── Integration: POST /ai/interview-prep ─────────────────────────────────────


async def test_interview_prep_endpoint(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("prep"))
    token = tokens["access_token"]

    response = await client.post(
        "/ai/interview-prep",
        json=_PREP_PAYLOAD,
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert "questions" in data
    assert "general_tips" in data
    assert data["ai_generated"] is True
    assert len(data["questions"]) >= 5

    for q in data["questions"]:
        assert "category" in q
        assert "question" in q
        assert q["question"]  # non-empty


async def test_interview_prep_unknown_job_id(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("unk"))
    payload = {**_PREP_PAYLOAD, "job_id": str(uuid.uuid4())}

    response = await client.post(
        "/ai/interview-prep",
        json=payload,
        headers=auth_headers(tokens["access_token"]),
    )
    assert response.status_code == 404


# ── Integration: Export endpoints ─────────────────────────────────────────────


async def test_export_linkedin(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("li"))
    token = tokens["access_token"]

    response = await client.get("/profiles/me/export/linkedin", headers=auth_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert "text" in data
    assert isinstance(data["text"], str)


async def test_export_link(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("link"))
    token = tokens["access_token"]

    response = await client.get("/profiles/me/export/link", headers=auth_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "profile_id" in data
    assert data["url"].startswith("http")


async def test_export_docx(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("docx"))
    token = tokens["access_token"]

    response = await client.get("/profiles/me/export/docx", headers=auth_headers(token))
    assert response.status_code == 200
    # DOCX magic bytes: PK (zip format)
    assert response.content[:2] == b"PK"
    assert "attachment" in response.headers.get("content-disposition", "")


# ── Auth required ─────────────────────────────────────────────────────────────


async def test_sprint07_endpoints_require_auth(client: AsyncClient) -> None:
    endpoints = [
        ("POST", "/ai/interview-prep", _PREP_PAYLOAD),
        ("GET", "/profiles/me/export/linkedin", None),
        ("GET", "/profiles/me/export/link", None),
        ("GET", "/profiles/me/export/docx", None),
    ]
    for method, url, body in endpoints:
        r = await client.get(url) if method == "GET" else await client.post(url, json=body)
        assert r.status_code == 401, f"{method} {url} should return 401"
