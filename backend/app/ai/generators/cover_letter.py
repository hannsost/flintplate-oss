"""Cover letter RAG pipeline – Sprint 0.6.

Builds a context from profile + job, calls LLM via LangChain.
Falls back to a template-based mock when OPENAI_API_KEY is not set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Max description chars sent to LLM
_MAX_DESC_CHARS = 3_000


@dataclass
class CoverLetterResult:
    text: str
    tone: str
    model_used: str
    ai_generated: bool = True
    # DSGVO-Kennzeichnung: der LLM-Output trägt immer dieses Flag
    disclaimer: str = "[KI-generiert – bitte überprüfen und anpassen]"


def _fmt_experiences(exps: list[dict[str, Any]]) -> str:
    lines = []
    for e in exps[:5]:
        line = f"- {e.get('title', '?')} bei {e.get('company', '?')}"
        start = e.get("start_date", "")
        end = e.get("end_date", "heute") if e.get("is_current") else e.get("end_date", "")
        if start:
            line += f" ({start}–{end})"
        if e.get("description"):
            line += f": {str(e['description'])[:120]}"
        lines.append(line)
    return "\n".join(lines) or "keine Angaben"


def _fmt_educations(edus: list[dict[str, Any]]) -> str:
    lines = []
    for e in edus[:3]:
        degree = e.get("degree") or ""
        field_ = e.get("field_of_study") or ""
        inst = e.get("institution", "?")
        lines.append(f"- {degree} {field_} @ {inst}".strip())
    return "\n".join(lines) or "keine Angaben"


def _build_profile_context(profile_data: dict[str, Any]) -> dict[str, str]:
    skills_raw = profile_data.get("skills") or []
    skill_names = [s["name"] if isinstance(s, dict) else str(s) for s in skills_raw[:20]]
    exps = profile_data.get("work_experiences") or []
    edus = profile_data.get("educations") or []

    return {
        "name": profile_data.get("name") or profile_data.get("full_name") or "Kandidat/in",
        "headline": profile_data.get("headline") or "",
        "summary": (profile_data.get("summary") or "")[:500],
        "location": profile_data.get("location") or "",
        "skills": ", ".join(skill_names) or "keine Angaben",
        "work_experiences": _fmt_experiences(exps),
        "educations": _fmt_educations(edus),
    }


async def generate_cover_letter(
    *,
    profile_data: dict[str, Any],
    company: str,
    position: str,
    job_description: str = "",
    required_skills: list[str] | None = None,
    company_context: str = "",
    tone: str = "professionell",
) -> CoverLetterResult:
    """Generate a cover letter using LangChain + LLM or mock fallback."""
    from app.ai.prompts.cover_letter import (
        COVER_LETTER_SYSTEM_PROMPT,
        COVER_LETTER_USER_TEMPLATE,
    )

    ctx = _build_profile_context(profile_data)
    req_skills = ", ".join(required_skills or []) or "keine Angaben"
    company_ctx_section = f"Unternehmensinfos: {company_context}" if company_context else ""
    desc_truncated = job_description[:_MAX_DESC_CHARS]

    user_prompt = COVER_LETTER_USER_TEMPLATE.format(
        **ctx,
        company=company,
        position=position,
        job_description=desc_truncated or "keine Beschreibung",
        required_skills=req_skills,
        company_context_section=company_ctx_section,
        tone=tone,
    )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.ai.client import get_llm
        from app.config import get_settings

        llm = await get_llm(temperature=0.7)
        if llm is None:
            raise ValueError("LLM nicht verfügbar (mock mode oder rate limit)")

        messages = [
            SystemMessage(content=COVER_LETTER_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        response = await llm.ainvoke(messages)
        text = str(response.content).strip()
        model_name = get_settings().openai_model

    except Exception as exc:
        log.warning("Cover letter LLM call failed (%s), using mock template", exc)
        text = _mock_cover_letter(ctx, company, position, tone)
        model_name = "mock-template"

    return CoverLetterResult(
        text=text,
        tone=tone,
        model_used=model_name,
    )


def _mock_cover_letter(
    ctx: dict[str, str],
    company: str,
    position: str,
    tone: str,
) -> str:
    """Fallback template – no LLM required."""
    skills_preview = ctx["skills"].split(", ")[:3]
    skills_str = ", ".join(skills_preview)
    name = ctx["name"]
    headline = ctx["headline"] or position
    summary_snippet = ctx["summary"][:200] if ctx["summary"] else ""

    return (
        f"Sehr geehrte Damen und Herren,\n\n"
        f"mit großem Interesse habe ich Ihre Stellenausschreibung als {position} "
        f"bei {company} gelesen. Als {headline} bringe ich die gesuchte Expertise mit.\n\n"
        f"{summary_snippet}\n\n"
        f"Meine Kernkompetenzen umfassen: {skills_str}. "
        f"Diese Fähigkeiten würde ich gerne bei {company} einbringen.\n\n"
        f"Über die Möglichkeit eines persönlichen Gesprächs freue ich mich sehr.\n\n"
        f"Mit freundlichen Grüßen\n{name}\n\n"
        f"[KI-generiert – bitte überprüfen und anpassen]"
    )
