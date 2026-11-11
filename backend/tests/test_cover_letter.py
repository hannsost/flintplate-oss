"""Cover letter + CV adjuster tests – Sprint 0.6.

Covers:
  - generate_cover_letter() mock fallback (no OPENAI_API_KEY)
  - adjust_cv_for_job() heuristic fallback
  - skill relevance sort (unit)
  - POST /ai/cover-letter → 201, ai_generated=True
  - GET  /ai/cover-letters → list
  - DELETE /ai/cover-letters/{id} → 204
  - DELETE /ai/cover-letters/{id} → 404 for other user
  - POST /ai/cv-adjust → 200 with tips
  - Auth required on all new endpoints
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.utils import auth_headers, register_and_login


def _email(label: str = "") -> str:
    return f"cl-{label}-{uuid.uuid4().hex[:8]}@hireos.dev"


_COVER_LETTER_PAYLOAD = {
    "company": "Acme GmbH",
    "position": "Backend Engineer",
    "job_description": "Wir suchen einen erfahrenen Python-Entwickler mit FastAPI-Kenntnissen.",
    "tone": "professionell",
}

_CV_ADJUST_PAYLOAD = {
    "company": "TechCorp",
    "position": "Senior Developer",
    "job_description": "Python, Docker, Kubernetes, React, AWS erforderlich.",
}


# ── Unit: mock cover letter generator ────────────────────────────────────────


async def test_generate_cover_letter_mock_fallback() -> None:
    """Without API key the mock template should be returned."""
    from app.ai.generators.cover_letter import generate_cover_letter

    result = await generate_cover_letter(
        profile_data={
            "name": "Max Muster",
            "headline": "Python Developer",
            "summary": "Ich entwickle seit 5 Jahren mit Python.",
            "skills": [{"name": "Python"}, {"name": "FastAPI"}],
            "work_experiences": [],
            "educations": [],
        },
        company="Acme GmbH",
        position="Backend Engineer",
        job_description="Python und FastAPI benötigt.",
        required_skills=["Python", "FastAPI"],
    )
    assert result.ai_generated is True
    assert "Acme GmbH" in result.text
    assert result.disclaimer in result.text or "[KI-generiert" in result.text


# ── Unit: heuristic CV adjuster ───────────────────────────────────────────────


async def test_adjust_cv_heuristic_fallback() -> None:
    from app.ai.generators.cv_adjuster import adjust_cv_for_job

    result = await adjust_cv_for_job(
        profile_data={
            "headline": "Software Engineer",
            "summary": "Erfahren in Python und Docker.",
            "skills": [{"name": "Python"}, {"name": "Docker"}, {"name": "Java"}],
            "work_experiences": [
                {
                    "id": "aaa",
                    "title": "Dev",
                    "company": "A",
                    "description": "Python Docker",
                    "is_current": False,
                },
                {
                    "id": "bbb",
                    "title": "Manager",
                    "company": "B",
                    "description": "Excel",
                    "is_current": True,
                },
            ],
        },
        company="TechCorp",
        position="DevOps Engineer",
        job_description="Docker Kubernetes AWS",
        required_skills=["Docker", "Kubernetes"],
    )
    assert result.ai_generated is True
    # Docker should be highlighted first (it's a required skill present in profile)
    assert "Docker" in result.highlighted_skills[:3]
    assert len(result.tips) >= 1


def test_skill_relevance_sort() -> None:
    from app.ai.generators.cv_adjuster import _skill_relevance_sort

    skills = [{"name": "Java"}, {"name": "Python"}, {"name": "Docker"}]
    sorted_skills = _skill_relevance_sort(skills, required_skills=["Python", "Docker"])
    # Required skills come first
    assert sorted_skills[0] in ["Python", "Docker"]
    assert sorted_skills[1] in ["Python", "Docker"]
    assert sorted_skills[2] == "Java"


# ── Integration: POST /ai/cover-letter ───────────────────────────────────────


async def test_generate_cover_letter_endpoint(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("gen"))
    token = tokens["access_token"]

    response = await client.post(
        "/ai/cover-letter",
        json=_COVER_LETTER_PAYLOAD,
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["company"] == "Acme GmbH"
    assert data["position"] == "Backend Engineer"
    assert data["ai_generated"] is True
    assert len(data["generated_text"]) > 20
    assert data["tone"] == "professionell"


async def test_cover_letter_with_job_id_not_found(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("notfound"))
    payload = {**_COVER_LETTER_PAYLOAD, "job_id": str(uuid.uuid4())}

    response = await client.post(
        "/ai/cover-letter",
        json=payload,
        headers=auth_headers(tokens["access_token"]),
    )
    assert response.status_code == 404


# ── Integration: GET /ai/cover-letters ───────────────────────────────────────


async def test_list_cover_letters(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("list"))
    token = tokens["access_token"]

    # Create two
    for i in range(2):
        await client.post(
            "/ai/cover-letter",
            json={**_COVER_LETTER_PAYLOAD, "company": f"Company {i}"},
            headers=auth_headers(token),
        )

    response = await client.get("/ai/cover-letters", headers=auth_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Ordered newest first
    assert data[0]["company"] == "Company 1"


async def test_list_cover_letters_own_only(client: AsyncClient) -> None:
    token_a = (await register_and_login(client, ai_consent=True, email=_email("own-a")))[
        "access_token"
    ]
    token_b = (await register_and_login(client, ai_consent=True, email=_email("own-b")))[
        "access_token"
    ]

    await client.post("/ai/cover-letter", json=_COVER_LETTER_PAYLOAD, headers=auth_headers(token_a))
    await client.post("/ai/cover-letter", json=_COVER_LETTER_PAYLOAD, headers=auth_headers(token_b))

    resp_a = await client.get("/ai/cover-letters", headers=auth_headers(token_a))
    resp_b = await client.get("/ai/cover-letters", headers=auth_headers(token_b))
    assert len(resp_a.json()) == 1
    assert len(resp_b.json()) == 1


# ── Integration: DELETE /ai/cover-letters/{id} ───────────────────────────────


async def test_delete_cover_letter(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("del"))
    token = tokens["access_token"]

    create_resp = await client.post(
        "/ai/cover-letter", json=_COVER_LETTER_PAYLOAD, headers=auth_headers(token)
    )
    letter_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/ai/cover-letters/{letter_id}", headers=auth_headers(token))
    assert del_resp.status_code == 204

    list_resp = await client.get("/ai/cover-letters", headers=auth_headers(token))
    assert len(list_resp.json()) == 0


async def test_delete_foreign_cover_letter_returns_404(client: AsyncClient) -> None:
    token_a = (await register_and_login(client, ai_consent=True, email=_email("fdel-a")))[
        "access_token"
    ]
    token_b = (await register_and_login(client, ai_consent=True, email=_email("fdel-b")))[
        "access_token"
    ]

    create_resp = await client.post(
        "/ai/cover-letter", json=_COVER_LETTER_PAYLOAD, headers=auth_headers(token_a)
    )
    letter_id = create_resp.json()["id"]

    response = await client.delete(f"/ai/cover-letters/{letter_id}", headers=auth_headers(token_b))
    assert response.status_code == 404


# ── Integration: POST /ai/cv-adjust ──────────────────────────────────────────


async def test_cv_adjust_endpoint(client: AsyncClient) -> None:
    tokens = await register_and_login(client, ai_consent=True, email=_email("adj"))
    token = tokens["access_token"]

    response = await client.post(
        "/ai/cv-adjust",
        json=_CV_ADJUST_PAYLOAD,
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert "highlighted_skills" in data
    assert "suggested_summary" in data
    assert "tips" in data
    assert data["ai_generated"] is True
    assert isinstance(data["highlighted_skills"], list)
    assert isinstance(data["tips"], list)


# ── Auth required ─────────────────────────────────────────────────────────────


async def test_cover_letter_endpoints_require_auth(client: AsyncClient) -> None:
    fake_id = str(uuid.uuid4())
    endpoints = [
        ("POST", "/ai/cover-letter", _COVER_LETTER_PAYLOAD),
        ("GET", "/ai/cover-letters", None),
        ("DELETE", f"/ai/cover-letters/{fake_id}", None),
        ("POST", "/ai/cv-adjust", _CV_ADJUST_PAYLOAD),
    ]
    for method, url, body in endpoints:
        if method == "GET":
            r = await client.get(url)
        elif method == "DELETE":
            r = await client.delete(url)
        else:
            r = await client.post(url, json=body)
        assert r.status_code == 401, f"{method} {url} should return 401"
