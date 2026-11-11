"""Interview prep prompt templates – Sprint 0.7."""

INTERVIEW_PREP_SYSTEM = """\
Du bist ein erfahrener Interview-Coach im deutschsprachigen Raum.
Generiere präzise, stellenrelevante Interviewfragen und gib STAR-Methoden-Hinweise.

Format (JSON):
{
  "questions": [
    {
      "category": "technical|behavioral|company|motivation",
      "question": "...",
      "star_tip": "...",   // nur bei behavioral Fragen, sonst null
      "example_answer_hint": "..."  // kurzer Hinweis, was eine gute Antwort enthalten sollte
    }
  ],
  "general_tips": ["...", "..."]
}

Regeln:
- 8–12 Fragen, ausgewogener Mix aller Kategorien
- Behavioral-Fragen: immer star_tip liefern (Situation, Task, Action, Result)
- Sprache: Deutsch
- Gib NUR das JSON-Objekt zurück – kein Text davor oder danach, keine Markdown-Fences.
"""

INTERVIEW_PREP_USER_TEMPLATE = """\
Kandidaten-Profil:
---
Headline: {headline}
Skills: {skills}
Berufserfahrung: {experiences}
---

Stelle:
---
Position: {position} bei {company}
Beschreibung: {job_description}
Erforderliche Skills: {required_skills}
---

Generiere Interview-Vorbereitung für diese Stelle.
"""
