"""CV adjuster – Sprint 0.6.

Reorders skills + experiences, suggests summary rewrite for a specific job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_MAX_DESC_CHARS = 2_000


@dataclass
class CVAdjustResult:
    highlighted_skills: list[str]  # sorted by relevance for this job
    highlighted_experience_ids: list[str]  # UUIDs of most relevant work_experiences
    suggested_summary: str  # rewritten for this job
    tips: list[str]  # 2–3 concrete improvement suggestions
    model_used: str
    ai_generated: bool = True
    disclaimer: str = "[KI-generiert – bitte überprüfen und anpassen]"


def _skill_relevance_sort(
    profile_skills: list[dict[str, Any]],
    required_skills: list[str],
) -> list[str]:
    """Sort profile skills by relevance: required first, then rest alphabetically."""
    req_lower = {s.lower() for s in required_skills}
    matched, rest = [], []
    for s in profile_skills:
        name = s["name"] if isinstance(s, dict) else str(s)
        if name.lower() in req_lower:
            matched.append(name)
        else:
            rest.append(name)
    return matched + sorted(rest)


def _experience_relevance_sort(
    experiences: list[dict[str, Any]],
    required_skills: list[str],
    job_description: str,
) -> list[str]:
    """Score each experience by keyword overlap with job description + required skills."""
    keywords = {s.lower() for s in required_skills}
    keywords.update(word.lower() for word in job_description.split() if len(word) > 4)

    scored: list[tuple[int, str]] = []
    for exp in experiences:
        exp_id = exp.get("id", "")
        if not exp_id:
            continue
        text = " ".join(
            [
                exp.get("title", ""),
                exp.get("company", ""),
                exp.get("description", "") or "",
            ]
        ).lower()
        score = sum(1 for kw in keywords if kw in text)
        scored.append((score, exp_id))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [eid for _, eid in scored]


async def adjust_cv_for_job(
    *,
    profile_data: dict[str, Any],
    company: str,
    position: str,
    job_description: str = "",
    required_skills: list[str] | None = None,
) -> CVAdjustResult:
    """Suggest CV adjustments for a specific job using LLM or heuristic fallback."""
    from app.ai.prompts.cover_letter import CV_ADJUST_SYSTEM_PROMPT, CV_ADJUST_USER_TEMPLATE

    skills_raw = profile_data.get("skills") or []
    experiences = profile_data.get("work_experiences") or []
    req_skills = required_skills or []
    desc_truncated = job_description[:_MAX_DESC_CHARS]

    # Always compute heuristic result (used as fallback + fallback data for LLM)
    heuristic_skills = _skill_relevance_sort(skills_raw, req_skills)
    heuristic_exp_ids = _experience_relevance_sort(experiences, req_skills, desc_truncated)
    headline = profile_data.get("headline") or position
    summary = profile_data.get("summary") or ""

    try:
        import json

        from langchain_core.messages import HumanMessage, SystemMessage

        from app.ai.client import get_llm

        skill_names = [s["name"] if isinstance(s, dict) else str(s) for s in skills_raw[:20]]
        exp_lines = "\n".join(
            f"- [{e.get('id', '')}] {e.get('title', '')} @ {e.get('company', '')} ({e.get('description', '')[:120]})"
            for e in experiences[:5]
        )

        user_prompt = CV_ADJUST_USER_TEMPLATE.format(
            headline=headline,
            summary=summary[:300],
            skills=", ".join(skill_names),
            work_experiences=exp_lines or "keine",
            position=position,
            company=company,
            job_description=desc_truncated or "keine Beschreibung",
            required_skills=", ".join(req_skills) or "keine Angaben",
        )

        llm = await get_llm(temperature=0.3)
        if llm is None:
            raise ValueError("LLM nicht verfügbar")

        messages = [
            SystemMessage(content=CV_ADJUST_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        response = await llm.ainvoke(messages)
        raw = str(response.content).strip()

        # Try to parse JSON from LLM response
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        parsed = json.loads(raw)
        from app.config import get_settings

        return CVAdjustResult(
            highlighted_skills=parsed.get("highlighted_skills", heuristic_skills)[:15],
            highlighted_experience_ids=parsed.get("highlighted_experience_ids", heuristic_exp_ids)[
                :5
            ],
            suggested_summary=parsed.get("suggested_summary", summary),
            tips=parsed.get("tips", [])[:3],
            model_used=get_settings().openai_model,
        )

    except Exception as exc:
        log.warning("CV adjuster LLM call failed (%s), using heuristic", exc)

    # Heuristic fallback
    tips = []
    if req_skills:
        missing = [
            s
            for s in req_skills
            if not any(
                s.lower() in (sk["name"] if isinstance(sk, dict) else sk).lower()
                for sk in skills_raw
            )
        ]
        if missing:
            tips.append(f"Fehlende Skills ergänzen: {', '.join(missing[:3])}")
    if summary and len(summary) < 100:
        tips.append("Zusammenfassung ausführlicher gestalten (mind. 2–3 Sätze)")
    tips.append(f"Hebe relevante Erfahrungen für '{position}' stärker hervor")

    fallback_summary = (
        f"{summary[:250]}… [Optimiert für {position} bei {company} – bitte anpassen]"
        if summary
        else f"Erfahrener {headline} mit Interesse an {position} bei {company}. [KI-Vorschlag]"
    )

    return CVAdjustResult(
        highlighted_skills=heuristic_skills[:15],
        highlighted_experience_ids=heuristic_exp_ids[:5],
        suggested_summary=fallback_summary,
        tips=tips[:3],
        model_used="heuristic",
    )
