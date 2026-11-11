"""Multi-format CV export – Sprint 0.7.

Formats: PDF (WeasyPrint), DOCX (python-docx), LinkedIn text, Profile link.
"""

from __future__ import annotations

import io
from html import escape

from app.profiles.models import CandidateProfile, Skill
from app.users.models import User

# ── LinkedIn text ─────────────────────────────────────────────────────────────


def build_linkedin_text(profile: CandidateProfile) -> str:
    """Return a LinkedIn-optimized plain text profile summary."""
    lines: list[str] = []

    if profile.headline:
        lines.append(f"🎯 {profile.headline}")
        lines.append("")

    if profile.summary:
        lines.append(profile.summary)
        lines.append("")

    if profile.skills:
        skill_names = [s.name for s in profile.skills[:20]]
        lines.append("💡 Skills: " + " · ".join(skill_names))
        lines.append("")

    if profile.work_experiences:
        lines.append("💼 Erfahrung:")
        for exp in profile.work_experiences[:5]:
            start = str(exp.start_date.year) if exp.start_date else ""
            end = "heute" if exp.is_current else (str(exp.end_date.year) if exp.end_date else "")
            period = f" ({start}–{end})" if start or end else ""
            lines.append(f"  • {exp.title} bei {exp.company}{period}")
        lines.append("")

    if profile.educations:
        lines.append("🎓 Ausbildung:")
        for edu in profile.educations[:3]:
            degree = f"{edu.degree} " if edu.degree else ""
            field_ = f"in {edu.field_of_study} " if edu.field_of_study else ""
            lines.append(f"  • {degree}{field_}@ {edu.institution}")
        lines.append("")

    if profile.location:
        lines.append(f"📍 {profile.location}")

    return "\n".join(lines)


# ── DOCX export ───────────────────────────────────────────────────────────────


def build_docx(profile: CandidateProfile, user: User) -> bytes:
    """Return a DOCX CV as bytes."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    doc = Document()

    # Title
    name = user.full_name or user.email
    title = doc.add_heading(name, 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if profile.headline:
        sub = doc.add_paragraph(profile.headline)
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.runs[0].font.color.rgb = RGBColor(0x45, 0x6A, 0xFF)

    # Contact info
    contact_parts = []
    if user.email:
        contact_parts.append(user.email)
    if profile.phone:
        contact_parts.append(profile.phone)
    if profile.location:
        contact_parts.append(profile.location)
    if profile.linkedin_url:
        contact_parts.append(profile.linkedin_url)
    if contact_parts:
        c = doc.add_paragraph(" | ".join(contact_parts))
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()

    # Summary
    if profile.summary:
        doc.add_heading("Profil", 1)
        doc.add_paragraph(profile.summary)

    # Work experiences
    if profile.work_experiences:
        doc.add_heading("Berufserfahrung", 1)
        for exp in profile.work_experiences:
            start = str(exp.start_date) if exp.start_date else ""
            end = "heute" if exp.is_current else (str(exp.end_date) if exp.end_date else "")
            period = f"{start} – {end}" if start or end else ""
            p = doc.add_paragraph()
            run = p.add_run(f"{exp.title} | {exp.company}")
            run.bold = True
            if period:
                p.add_run(f"  {period}")
            if exp.location:
                p.add_run(f"  📍 {exp.location}")
            if exp.description:
                doc.add_paragraph(exp.description, style="List Bullet")

    # Education
    if profile.educations:
        doc.add_heading("Ausbildung", 1)
        for edu in profile.educations:
            p = doc.add_paragraph()
            degree = f"{edu.degree} " if edu.degree else ""
            field_ = f"in {edu.field_of_study} " if edu.field_of_study else ""
            run = p.add_run(f"{degree}{field_}@ {edu.institution}")
            run.bold = True
            if edu.start_date or edu.end_date:
                start = str(edu.start_date.year) if edu.start_date else ""
                end = str(edu.end_date.year) if edu.end_date else ""
                p.add_run(f"  ({start}–{end})")

    # Skills – grouped by category with level
    if profile.skills:
        doc.add_heading("Skills", 1)
        from collections import defaultdict

        by_cat: dict[str, list[Skill]] = defaultdict(list)
        for s in profile.skills:
            by_cat[s.category or "Weitere"].append(s)
        for cat, skills in by_cat.items():
            p = doc.add_paragraph()
            run = p.add_run(f"{cat}: ")
            run.bold = True
            parts = []
            for s in skills:
                entry = s.name
                if s.level:
                    entry += f" ({s.level})"
                parts.append(entry)
            p.add_run(" · ".join(parts))

    # Footer note
    doc.add_paragraph()
    footer = doc.add_paragraph("Erstellt mit FlintPlate · neurofunken")
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.runs[0].font.size = Pt(8)
    footer.runs[0].font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── PDF export ────────────────────────────────────────────────────────────────


def _build_cv_html(profile: CandidateProfile, user: User) -> str:
    """Build an HTML string for the CV (used by WeasyPrint)."""
    name = escape(user.full_name or user.email)
    headline = escape(profile.headline or "")
    summary = escape(profile.summary or "")
    location = escape(profile.location or "")
    phone = escape(profile.phone or "")
    email_addr = escape(user.email or "")
    linkedin = escape(profile.linkedin_url or "")

    contact = " &nbsp;|&nbsp; ".join(filter(None, [email_addr, phone, location, linkedin]))

    skills_html = ""
    if profile.skills:
        # Group by category
        from collections import defaultdict

        by_cat: dict[str, list[Skill]] = defaultdict(list)
        for s in profile.skills:
            by_cat[s.category or "Weitere"].append(s)

        _level_dots = {
            "beginner": "●○○○",
            "intermediate": "●●○○",
            "advanced": "●●●○",
            "expert": "●●●●",
        }

        groups_html = ""
        for cat, skills in by_cat.items():
            badges = "".join(
                f'<span class="badge">{escape(s.name)}'
                f'{"<span class=lvl>" + _level_dots.get(s.level or "", "") + "</span>" if s.level else ""}'
                f"</span>"
                for s in skills
            )
            groups_html += f'<div class="skill-group"><span class="skill-cat">{escape(cat)}</span><div class="badges">{badges}</div></div>'

        skills_html = f"<section><h2>Skills</h2>{groups_html}</section>"

    exp_html = ""
    if profile.work_experiences:
        items = []
        for exp in profile.work_experiences:
            start = str(exp.start_date) if exp.start_date else ""
            end = "heute" if exp.is_current else (str(exp.end_date) if exp.end_date else "")
            period = f"{start} – {end}" if start or end else ""
            desc = f"<p>{escape(exp.description)}</p>" if exp.description else ""
            items.append(
                f'<div class="entry">'
                f'<div class="entry-header"><strong>{escape(exp.title)}</strong> '
                f'<span class="company">bei {escape(exp.company)}</span>'
                f'{"<span class=period>" + period + "</span>" if period else ""}'
                f"</div>{desc}</div>"
            )
        exp_html = f'<section><h2>Berufserfahrung</h2>{"".join(items)}</section>'

    edu_html = ""
    if profile.educations:
        items = []
        for edu in profile.educations:
            degree = f"{escape(edu.degree)} " if edu.degree else ""
            field_ = f"in {escape(edu.field_of_study)}" if edu.field_of_study else ""
            start = str(edu.start_date.year) if edu.start_date else ""
            end = str(edu.end_date.year) if edu.end_date else ""
            period = f"({start}–{end})" if start or end else ""
            items.append(
                f'<div class="entry"><div class="entry-header">'
                f"<strong>{degree}{field_}</strong> @ {escape(edu.institution)} "
                f'<span class="period">{period}</span></div></div>'
            )
        edu_html = f'<section><h2>Ausbildung</h2>{"".join(items)}</section>'

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 10pt;
         color: #1a1a2e; padding: 2cm; max-width: 21cm; }}
  h1 {{ font-size: 22pt; color: #456AFF; margin-bottom: 4px; }}
  h2 {{ font-size: 12pt; color: #456AFF; border-bottom: 1px solid #e0e7ff;
        padding-bottom: 3px; margin: 18px 0 10px; }}
  .headline {{ font-size: 11pt; color: #555; margin-bottom: 6px; }}
  .contact {{ font-size: 9pt; color: #777; margin-bottom: 4px; }}
  .summary {{ font-size: 10pt; line-height: 1.5; margin: 12px 0; }}
  section {{ margin-bottom: 14px; }}
  .entry {{ margin-bottom: 10px; }}
  .entry-header {{ font-size: 10pt; }}
  .company {{ color: #456AFF; }}
  .period {{ font-size: 9pt; color: #999; margin-left: 6px; }}
  .skill-group {{ margin-bottom: 8px; }}
  .skill-cat {{ font-size: 8pt; font-weight: bold; color: #888;
                text-transform: uppercase; letter-spacing: 0.5px;
                display: block; margin-bottom: 4px; }}
  .badges {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .badge {{ background: #eef1ff; color: #456AFF; border-radius: 4px;
            padding: 2px 7px; font-size: 9pt; display: inline-flex;
            align-items: center; gap: 4px; }}
  .lvl {{ font-size: 7pt; color: #9aabff; letter-spacing: -1px; }}
  .footer {{ font-size: 8pt; color: #bbb; text-align: center; margin-top: 2cm; }}
</style>
</head>
<body>
  <h1>{name}</h1>
  {f'<div class="headline">{headline}</div>' if headline else ''}
  {f'<div class="contact">{contact}</div>' if contact else ''}
  {f'<div class="summary">{summary}</div>' if summary else ''}
  {skills_html}
  {exp_html}
  {edu_html}
  <div class="footer">Erstellt mit FlintPlate · neurofunken</div>
</body>
</html>"""


def build_pdf(profile: CandidateProfile, user: User) -> bytes:
    """Return a PDF CV as bytes using WeasyPrint."""
    from weasyprint import HTML

    html_content = _build_cv_html(profile, user)
    return bytes(HTML(string=html_content, url_fetcher=_block_external_resource).write_pdf())


def _block_external_resource(url: str) -> dict[str, object]:
    """CV templates are self-contained; no network or local file reads are needed."""
    raise ValueError("External resources are disabled in CV exports")
