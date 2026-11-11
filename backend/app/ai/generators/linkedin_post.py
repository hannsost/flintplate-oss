"""LinkedIn post generator for recruiters – Content-Kit.

Generates ready-to-publish LinkedIn posts for job openings and successful
placements. Falls back to a template when OPENAI_API_KEY is not set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_MAX_DESC_CHARS = 1_500


@dataclass
class LinkedInPostResult:
    text: str
    post_type: str  # "job_opening" | "placement"
    ai_generated: bool = True
    disclaimer: str = "[KI-generiert – bitte prüfen und anpassen]"


_SYSTEM_PROMPT = """\
Du bist ein erfahrener Recruiting-Marketing-Experte. Du schreibst ansprechende
LinkedIn-Posts für Personalvermittler. Deine Posts sind:
- Direkt und auf den Punkt (max 300 Wörter)
- Mit relevanten Hashtags am Ende (5–8 Stück)
- Professionell aber persönlich – kein Marketing-Bla-Bla
- Auf Deutsch, außer wenn explizit anders gewünscht
- Ohne Emojis zu übertreiben (max 2-3 pro Post)
Gib NUR den Post-Text aus, keine Erklärungen.
"""

_JOB_POST_TEMPLATE = """\
Schreibe einen LinkedIn-Post für folgende Stellenausschreibung:

Unternehmen: {company}
Stelle: {title}
Standort: {location}
Anstellungsart: {employment_type}
Gehalt: {salary}
Remote: {remote}
Geforderte Skills: {skills}
Kurzbeschreibung: {description}

Ziel: Qualifizierte Kandidaten ansprechen. Der Post soll die wichtigsten
Benefits hervorheben und zur Bewerbung animieren.
"""

_PLACEMENT_POST_TEMPLATE = """\
Schreibe einen LinkedIn-Post für eine erfolgreiche Vermittlung:

Kandidat vermittelt als: {position}
Unternehmen: {company}
Branche: {category}

Schreibe einen kurzen, professionellen Post der:
1. Die erfolgreiche Vermittlung feiert (anonym, kein Kandidatenname)
2. Die Expertise des Recruiters unterstreicht
3. Andere potenzielle Kandidaten/Unternehmen anspricht
Verwende „wir haben erfolgreich vermittelt" o.ä.
"""


def _fmt_salary(min_: int | None, max_: int | None) -> str:
    if not min_ and not max_:
        return "nicht angegeben"

    def fmt(n: int) -> str:
        return f"{round(n / 1000)}k"

    if min_ and max_:
        return f"€{fmt(min_)} – €{fmt(max_)} p.a."
    if min_:
        return f"ab €{fmt(min_)} p.a."
    return f"bis €{fmt(max_)} p.a."  # type: ignore[arg-type]


def _mock_job_post(data: dict[str, Any]) -> str:
    title = data.get("title", "Stelle")
    company = data.get("company", "Unternehmen")
    location = data.get("location", "Deutschland")
    skills = ", ".join(data.get("required_skills", [])[:5]) or "diverse Skills"
    return (
        f"🚀 Neue Stelle: {title} bei {company}!\n\n"
        f"Wir suchen einen motivierten {title} für den Standort {location}.\n\n"
        f"Das bringst du mit:\n✅ {skills}\n\n"
        f"Klingt interessant? Dann bewirb dich jetzt über den Link in den Kommentaren "
        f"oder sende mir eine Direktnachricht!\n\n"
        f"#recruiting #{title.replace(' ', '')} #{company.replace(' ', '')} "
        f"#jobs #karriere #stellenangebot #bewerbung"
    )


def _mock_placement_post(data: dict[str, Any]) -> str:
    position = data.get("position", "eine neue Position")
    company = data.get("company", "einem Unternehmen")
    return (
        f"✅ Erfolgreiche Vermittlung!\n\n"
        f"Wir freuen uns, die erfolgreiche Besetzung der Position '{position}' "
        f"bei {company} bekannt zu geben.\n\n"
        f"Unser Matching-Prozess hat wieder einen perfekten Fit gefunden. "
        f"Herzlichen Glückwunsch an alle Beteiligten!\n\n"
        f"Suchen auch Sie qualifizierte Fachkräfte? Sprechen Sie uns an!\n\n"
        f"#recruiting #personalvermittlung #erfolgsvermittlung #hr #jobs #karriere #hiring"
    )


async def generate_job_post(
    *,
    title: str,
    company: str,
    location: str | None,
    description: str,
    required_skills: list[str],
    salary_min: int | None,
    salary_max: int | None,
    is_remote: bool,
    employment_type: str | None,
) -> LinkedInPostResult:
    """Generate LinkedIn post for a job opening."""
    user_prompt = _JOB_POST_TEMPLATE.format(
        company=company,
        title=title,
        location=location or "Flexibel",
        employment_type=employment_type or "Vollzeit",
        salary=_fmt_salary(salary_min, salary_max),
        remote="Ja" if is_remote else "Nein",
        skills=", ".join(required_skills[:8]) or "keine Angaben",
        description=description[:_MAX_DESC_CHARS] or "keine Beschreibung",
    )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.ai.client import get_llm

        llm = await get_llm(temperature=0.7)
        if llm is None:
            raise ValueError("LLM nicht verfügbar")

        response = await llm.ainvoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )
        text = str(response.content).strip()
        return LinkedInPostResult(text=text, post_type="job_opening")
    except Exception as exc:
        log.warning("LinkedIn post LLM failed: %s – using template", exc)
        return LinkedInPostResult(
            text=_mock_job_post(
                {
                    "title": title,
                    "company": company,
                    "location": location,
                    "required_skills": required_skills,
                }
            ),
            post_type="job_opening",
            ai_generated=False,
            disclaimer="[Template – KI nicht verfügbar]",
        )


async def generate_placement_post(
    *,
    position: str,
    company: str,
    category: str | None,
) -> LinkedInPostResult:
    """Generate LinkedIn post for a successful placement."""
    user_prompt = _PLACEMENT_POST_TEMPLATE.format(
        position=position,
        company=company,
        category=category or "allgemein",
    )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.ai.client import get_llm

        llm = await get_llm(temperature=0.7)
        if llm is None:
            raise ValueError("LLM nicht verfügbar")

        response = await llm.ainvoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )
        text = str(response.content).strip()
        return LinkedInPostResult(text=text, post_type="placement")
    except Exception as exc:
        log.warning("LinkedIn placement post LLM failed: %s – using template", exc)
        return LinkedInPostResult(
            text=_mock_placement_post({"position": position, "company": company}),
            post_type="placement",
            ai_generated=False,
            disclaimer="[Template – KI nicht verfügbar]",
        )
