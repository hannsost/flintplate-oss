"""Pydantic schemas for parsed CV data with Trust-Layer – Sprint 0.3.

Each extracted field carries a `source` that references the CV page or
extraction method, enabling the UI to show confidence and provenance.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Trust-annotated leaf types ─────────────────────────────────────────────────


class TrustedField(BaseModel):
    """A single extracted value with a source reference."""

    value: str | None = None
    source: str = "llm"  # e.g. "cv_page_1", "llm", "mock_regex"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# ── Sub-structures ─────────────────────────────────────────────────────────────


class ParsedSkill(BaseModel):
    name: str = Field(
        description="Specific skill name, e.g. 'HubSpot CRM', 'Python', 'Consultative Selling'"
    )
    level: str | None = Field(
        default=None,
        description="One of: beginner, intermediate, advanced, expert. Infer from context words like 'Grundkenntnisse'=beginner, 'gute Kenntnisse'=intermediate, 'sehr gut'/'mehrjährig'=advanced, '10+ Jahre'/'Experte'=expert. null if unknown.",
    )
    years_of_experience: int | None = Field(
        default=None,
        description="Integer years derived from dates in work history, or null.",
    )
    category: str | None = Field(
        default=None,
        description="One of: Programming Language, Framework, Database, Cloud, DevOps, Tool, CRM & Sales, Healthcare IT, Office & Productivity, Language, Soft Skill, Other. Choose the best fit.",
    )
    source: str = "llm"


class ParsedWorkExperience(BaseModel):
    company: str = Field(description="Company name as written in the CV")
    title: str = Field(description="Exact job title as written in the CV")
    location: str | None = Field(default=None, description="City or location of the role, or null")
    start_date: str | None = Field(
        default=None, description="Start date in YYYY-MM or YYYY format, or null"
    )
    end_date: str | None = Field(
        default=None, description="End date in YYYY-MM or YYYY format. null if role is current."
    )
    is_current: bool = Field(
        default=False,
        description="true if role is ongoing (no end date, or 'aktuell'/'heute'/'present')",
    )
    description: str | None = Field(
        default=None,
        description="Full role description: ALL responsibilities, tools, technologies, achievements, and quantitative results (quotas, revenue, team size) as detailed prose. Minimum 3 sentences. Never use a single tag or one-word summary.",
    )
    source: str = "llm"


class ParsedEducation(BaseModel):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    grade: str | None = None
    source: str = "llm"


# ── LLM structured output schema ───────────────────────────────────────────────


class LLMExtractedCV(BaseModel):
    """Structured output returned by the LLM – mapped 1:1 from the prompt."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    skills: list[ParsedSkill] = Field(default_factory=list)
    work_experiences: list[ParsedWorkExperience] = Field(default_factory=list)
    educations: list[ParsedEducation] = Field(default_factory=list)


# ── Final ParsedCV result ──────────────────────────────────────────────────────


class ParsedCV(BaseModel):
    """Complete parsed CV with metadata."""

    raw_text: str
    pages: list[str] = Field(default_factory=list)  # per-page text

    # Extracted fields
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    skills: list[ParsedSkill] = Field(default_factory=list)
    work_experiences: list[ParsedWorkExperience] = Field(default_factory=list)
    educations: list[ParsedEducation] = Field(default_factory=list)

    # Metadata
    confidence: float = 0.0
    parser_version: str = "0.3-llm"
    token_count: int = 0

    def to_structured_data(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "headline": self.headline,
            "summary": self.summary,
            "skills": [s.model_dump() for s in self.skills],
            "work_experiences": [w.model_dump() for w in self.work_experiences],
            "educations": [e.model_dump() for e in self.educations],
            "_meta": {
                "confidence": self.confidence,
                "parser": self.parser_version,
                "token_count": self.token_count,
            },
        }
