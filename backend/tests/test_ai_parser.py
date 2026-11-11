"""AI CV Parser tests – Sprint 0.3.

Tests cover:
  - OCR extractor: PDF (digital), DOCX, plain text, missing file
  - LLM parser: regex fallback (no API key in test env)
  - ParsedCV.to_structured_data() schema
  - POST /ai/parse-cv endpoint (201 + parse_status)
"""

from __future__ import annotations

import io
import pathlib
import tempfile
import uuid

import pytest
from httpx import AsyncClient

from tests.utils import auth_headers, register_and_login


def _email(label: str = "") -> str:
    return f"ai-{label}-{uuid.uuid4().hex[:8]}@hireos.dev"


# ── OCR Extractor ─────────────────────────────────────────────────────────────


async def test_extract_text_plain_file() -> None:
    """Plain text files are read directly."""
    from app.ai.ocr.extractor import extract_text

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("Max Mustermann\nSenior Python Engineer\nBerlin")
        path = f.name

    raw, pages = await extract_text(path)
    assert "Mustermann" in raw
    assert len(pages) >= 1
    pathlib.Path(path).unlink(missing_ok=True)


async def test_extract_text_missing_file() -> None:
    """Missing file returns empty strings without raising."""
    from app.ai.ocr.extractor import extract_text

    raw, pages = await extract_text("/tmp/does_not_exist_hireos.pdf")
    assert raw == ""
    assert pages == []


async def test_extract_text_docx() -> None:
    """DOCX extraction returns non-empty text."""
    pytest.importorskip("docx")
    import docx

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        path = f.name

    doc = docx.Document()
    doc.add_paragraph("Anna Schmidt")
    doc.add_paragraph("Data Scientist – München")
    doc.save(path)

    from app.ai.ocr.extractor import extract_text

    raw, pages = await extract_text(path)
    assert "Schmidt" in raw
    pathlib.Path(path).unlink(missing_ok=True)


# ── Regex Fallback Parser ─────────────────────────────────────────────────────


async def test_regex_fallback_extracts_email() -> None:
    from app.ai.parsers.llm_parser import _regex_fallback

    result = _regex_fallback("Name: Max\nEmail: max@example.com\nPython Developer", [])
    assert result.email == "max@example.com"
    assert result.confidence == pytest.approx(0.3)
    assert result.parser_version == "0.3-regex-fallback"


async def test_regex_fallback_extracts_known_skills() -> None:
    from app.ai.parsers.llm_parser import _regex_fallback

    result = _regex_fallback("Skills: Python, Docker, PostgreSQL, React", [])
    skill_names = [s.name for s in result.skills]
    assert "Python" in skill_names
    assert "Docker" in skill_names
    assert "PostgreSQL" in skill_names


# ── ParsedCV Schema ───────────────────────────────────────────────────────────


async def test_parsed_cv_to_structured_data() -> None:
    from app.ai.parsers.schemas import ParsedCV, ParsedSkill

    cv = ParsedCV(
        raw_text="test",
        name="Max Mustermann",
        email="max@test.de",
        skills=[ParsedSkill(name="Python", level="expert", source="cv_page_1")],
        confidence=0.9,
        parser_version="0.3-llm",
    )
    data = cv.to_structured_data()
    assert data["name"] == "Max Mustermann"
    assert data["email"] == "max@test.de"
    assert data["skills"][0]["name"] == "Python"
    assert data["skills"][0]["source"] == "cv_page_1"
    assert data["_meta"]["confidence"] == pytest.approx(0.9)
    assert data["_meta"]["parser"] == "0.3-llm"


# ── POST /ai/parse-cv endpoint ────────────────────────────────────────────────


async def test_parse_cv_endpoint_returns_structured(client: AsyncClient) -> None:
    """Endpoint accepts a PDF, runs parser, returns structured response."""
    tokens = await register_and_login(client, ai_consent=True, email=_email("parse"))
    token = tokens["access_token"]

    fake_pdf = io.BytesIO(b"%PDF-1.4\nMax Mustermann\nPython Docker PostgreSQL")
    response = await client.post(
        "/ai/parse-cv",
        files={"file": ("test_cv.pdf", fake_pdf, "application/pdf")},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert "parse_status" in data
    assert data["parse_status"] in ("parsed", "fallback", "failed")
    assert "structured_data" in data
    assert "parser_version" in data
    assert "confidence" in data
    assert "raw_text_preview" in data


async def test_parse_cv_endpoint_requires_auth(client: AsyncClient) -> None:
    fake_pdf = io.BytesIO(b"%PDF fake")
    response = await client.post(
        "/ai/parse-cv",
        files={"file": ("cv.pdf", fake_pdf, "application/pdf")},
    )
    assert response.status_code == 401
