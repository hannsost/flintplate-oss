"""Interview prep generator – Sprint 0.7.

Generates interview questions + STAR tips per job.
Falls back to curated template questions without OPENAI_API_KEY.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_MAX_DESC_CHARS = 2_000


@dataclass
class InterviewQuestion:
    category: str  # technical | behavioral | company | motivation
    question: str
    star_tip: str | None = None
    example_answer_hint: str = ""


@dataclass
class InterviewPrepResult:
    questions: list[InterviewQuestion]
    general_tips: list[str]
    model_used: str
    ai_generated: bool = True
    disclaimer: str = "[KI-generiert – bitte überprüfen]"


# ── Fallback template questions ────────────────────────────────────────────

_BEHAVIORAL_QUESTIONS = [
    InterviewQuestion(
        category="behavioral",
        question="Erzählen Sie von einer Situation, in der Sie ein schwieriges Problem gelöst haben.",
        star_tip="Beschreibe: Situation → Aufgabe → konkrete Handlung → messbares Ergebnis (STAR)",
        example_answer_hint="Konkretes Beispiel aus der Praxis, quantifiziertes Ergebnis",
    ),
    InterviewQuestion(
        category="behavioral",
        question="Wie haben Sie in einem Team Konflikte gelöst?",
        star_tip="Fokus auf Action: Was haben SIE konkret getan? Ergebnis zeigen.",
        example_answer_hint="Zeige Empathie + Lösungsorientierung",
    ),
    InterviewQuestion(
        category="behavioral",
        question="Beschreiben Sie ein Projekt, bei dem Sie scheiterten. Was haben Sie gelernt?",
        star_tip="Ehrlichkeit zeigen + Lerneffekt betonen. Negatives → Positives wenden.",
        example_answer_hint="Reflexionsfähigkeit und Wachstumsmindset demonstrieren",
    ),
]

_MOTIVATION_QUESTIONS = [
    InterviewQuestion(
        category="motivation",
        question="Warum bewerben Sie sich bei uns, und nicht bei einem Wettbewerber?",
        example_answer_hint="Recherche zeigen: Produkt, Kultur, Mission des Unternehmens",
    ),
    InterviewQuestion(
        category="motivation",
        question="Wo sehen Sie sich in 3–5 Jahren?",
        example_answer_hint="Ambition + Bezug zur Stelle + realistischer Karriereplan",
    ),
]

_COMPANY_QUESTIONS = [
    InterviewQuestion(
        category="company",
        question="Was wissen Sie über unser Unternehmen und unsere Produkte?",
        example_answer_hint="Zeige echtes Interesse – recherchiere vorher Website, LinkedIn, News",
    ),
    InterviewQuestion(
        category="company",
        question="Was erwarten Sie von Ihrer Führungskraft?",
        example_answer_hint="Sei konkret, aber flexibel – kein Wunschkonzert",
    ),
]


def _technical_questions_for_skills(skills: list[str], position: str) -> list[InterviewQuestion]:
    questions = []
    for skill in skills[:3]:
        questions.append(
            InterviewQuestion(
                category="technical",
                question=f"Wie würden Sie {skill} in einem Produktivsystem einsetzen? Nenn ein konkretes Beispiel.",
                example_answer_hint=f"Zeige praktische {skill}-Erfahrung + Architekturbewusstsein",
            )
        )
    if not skills:
        questions.append(
            InterviewQuestion(
                category="technical",
                question=f"Welche technischen Herausforderungen erwarten Sie in der Rolle als {position}?",
                example_answer_hint="Zeige Marktkenntnis und Vorbereitungstiefe",
            )
        )
    return questions


def _general_tips(company: str, position: str) -> list[str]:
    return [
        f"Bereite 2–3 eigene Fragen an {company} vor (Teamstruktur, Tech-Stack, Onboarding).",
        "Recherchiere {company} auf LinkedIn, Kununu und der Website.",
        "Übe deine Kurzvorstellung (2 Minuten: Werdegang → aktuelle Rolle → warum jetzt).",
        "Halte konkrete Zahlen/Ergebnisse aus deiner Erfahrung bereit (Teamgröße, Umsatz, Performance).",
    ]


async def generate_interview_prep(
    *,
    profile_data: dict[str, Any],
    company: str,
    position: str,
    job_description: str = "",
    required_skills: list[str] | None = None,
) -> InterviewPrepResult:
    """Generate interview preparation using LLM or curated fallback."""
    from app.ai.prompts.interview_prep import INTERVIEW_PREP_SYSTEM, INTERVIEW_PREP_USER_TEMPLATE

    skills_raw = profile_data.get("skills") or []
    skill_names = [s["name"] if isinstance(s, dict) else str(s) for s in skills_raw[:15]]
    req_skills = required_skills or []
    desc_truncated = job_description[:_MAX_DESC_CHARS]

    exps = profile_data.get("work_experiences") or []
    exp_summary = (
        "; ".join(f"{e.get('title', '')} @ {e.get('company', '')}" for e in exps[:4]) or "keine"
    )

    try:
        import json

        from langchain_core.messages import HumanMessage, SystemMessage

        from app.ai.client import get_llm

        user_prompt = INTERVIEW_PREP_USER_TEMPLATE.format(
            headline=profile_data.get("headline") or position,
            skills=", ".join(skill_names) or "keine",
            experiences=exp_summary,
            position=position,
            company=company,
            job_description=desc_truncated or "keine",
            required_skills=", ".join(req_skills) or "keine",
        )

        llm = await get_llm(temperature=0.5)
        if llm is None:
            raise ValueError("LLM nicht verfügbar")

        messages = [
            SystemMessage(content=INTERVIEW_PREP_SYSTEM),
            HumanMessage(content=user_prompt),
        ]
        response = await llm.ainvoke(messages)
        raw = str(response.content).strip()

        # Extract JSON – find first { ... } block
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]

        parsed = json.loads(raw)
        questions = [
            InterviewQuestion(
                category=q.get("category", "general"),
                question=q.get("question", ""),
                star_tip=q.get("star_tip"),
                example_answer_hint=q.get("example_answer_hint", ""),
            )
            for q in parsed.get("questions", [])
        ]
        general_tips = parsed.get("general_tips", _general_tips(company, position))

        from app.config import get_settings

        return InterviewPrepResult(
            questions=questions,
            general_tips=general_tips,
            model_used=get_settings().openai_model,
        )

    except Exception as exc:
        log.warning("Interview prep LLM failed (%s), using curated fallback", exc)

    # Curated fallback
    questions = (
        _technical_questions_for_skills(skill_names or req_skills, position)
        + _BEHAVIORAL_QUESTIONS
        + _MOTIVATION_QUESTIONS
        + _COMPANY_QUESTIONS
    )
    return InterviewPrepResult(
        questions=questions[:10],
        general_tips=_general_tips(company, position),
        model_used="curated-fallback",
    )
