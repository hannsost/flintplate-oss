"""AI endpoints – Sprint 0.3 + 0.6 + 0.7 + 1.8 (module enforcement)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import check_module_enabled, track_ai_usage
from app.ai.consent import require_ai_consent
from app.ai.parsers.schemas import ParsedCV
from app.database import get_db
from app.profiles.service import get_or_create_profile
from app.security import get_current_user
from app.uploads.service import save_cv
from app.users.models import User

router = APIRouter()


async def _require_module(tenant_id: str | None, module_key: str) -> None:
    """Raise 403 if tenant does not have this module enabled."""
    if not await check_module_enabled(tenant_id, module_key):
        raise HTTPException(
            status_code=403,
            detail=f"Modul '{module_key}' ist für Ihren Plan nicht freigeschaltet. Kontaktieren Sie Ihren Administrator.",
        )


class ParseCVResponse(BaseModel):
    parse_status: str  # "parsed" | "fallback" | "failed"
    parser_version: str
    confidence: float
    token_count: int
    structured_data: dict[str, Any]
    raw_text_preview: str  # first 500 chars for UI debugging


# ── CV Parse (Sprint 0.3) ─────────────────────────────────────────────────────


@router.post(
    "/parse-cv",
    dependencies=[Depends(require_ai_consent)],
    response_model=ParseCVResponse,
    status_code=status.HTTP_200_OK,
    summary="CV hochladen und mit KI parsen (Sprint 0.3)",
)
async def parse_cv(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(..., description="PDF, DOC oder DOCX – max. 10 MB"),
) -> ParseCVResponse:
    """Upload a CV file, run OCR + LLM extraction, persist to profile."""
    from app.ai.parsers.cv_parser import parse_cv_file
    from app.uploads.service import delete_cv

    tid = str(current_user.tenant_id) if current_user.tenant_id else None
    await _require_module(tid, "ai_cv_parser")

    profile = await get_or_create_profile(db, current_user.id)
    if profile.cv_file_path:
        await delete_cv(profile.cv_file_path)

    file_path, original_filename = await save_cv(file, current_user.id)
    profile.cv_file_path = file_path
    profile.cv_original_filename = original_filename

    try:
        parsed: ParsedCV = await parse_cv_file(file_path, original_filename)
        parse_status = "parsed" if parsed.confidence >= 0.5 else "fallback"
    except Exception:
        from app.ai.parsers.llm_parser import _regex_fallback

        parsed = _regex_fallback("", [])
        parse_status = "failed"

    await track_ai_usage(tid, "ai_cv_parser")
    structured = parsed.to_structured_data()
    profile.structured_data = structured
    profile.raw_cv_text = {"text": parsed.raw_text[:5000]}

    await db.flush()

    return ParseCVResponse(
        parse_status=parse_status,
        parser_version=parsed.parser_version,
        confidence=parsed.confidence,
        token_count=parsed.token_count,
        structured_data=structured,
        raw_text_preview=parsed.raw_text[:500],
    )


# ── Cover Letter (Sprint 0.6) ─────────────────────────────────────────────────

# ── Interview Prep schemas (Sprint 0.7) ───────────────────────────────────────
from pydantic import Field as _Field  # noqa: E402

from app.ai.cover_letters.models import CoverLetter  # noqa: E402
from app.ai.cover_letters.schemas import (  # noqa: E402
    CoverLetterRead,
    CoverLetterRequest,
    CVAdjustRequest,
    CVAdjustResponse,
)


class InterviewPrepRequest(BaseModel):
    job_id: uuid.UUID | None = None
    company: str = _Field(max_length=255)
    position: str = _Field(max_length=500)
    job_description: str | None = _Field(default=None, max_length=5000)


class InterviewQuestionOut(BaseModel):
    category: str
    question: str
    star_tip: str | None
    example_answer_hint: str


class InterviewPrepResponse(BaseModel):
    questions: list[InterviewQuestionOut]
    general_tips: list[str]
    model_used: str
    ai_generated: bool
    disclaimer: str


@router.post(
    "/cover-letter",
    dependencies=[Depends(require_ai_consent)],
    response_model=CoverLetterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Anschreiben generieren (KI-Assistent Sprint 0.6)",
)
async def generate_cover_letter(
    data: CoverLetterRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CoverLetter:
    """Generate a cover letter using RAG (profile + job context) and persist it."""
    from app.ai.generators.cover_letter import generate_cover_letter as _gen
    from app.jobs.models import JobPosting
    from app.jobs.publication import public_job_condition

    tid = str(current_user.tenant_id) if current_user.tenant_id else None
    await _require_module(tid, "ai_cover_letter")

    # Load profile with structured data
    profile = await get_or_create_profile(db, current_user.id)
    profile_data: dict[str, Any] = profile.structured_data or {}

    # Supplement with profile relational data
    profile_data.setdefault("headline", profile.headline)
    profile_data.setdefault("summary", profile.summary)
    profile_data.setdefault("location", profile.location)
    profile_data.setdefault("skills", [{"name": s.name, "level": s.level} for s in profile.skills])
    profile_data.setdefault(
        "work_experiences",
        [
            {
                "id": str(e.id),
                "title": e.title,
                "company": e.company,
                "description": e.description,
                "start_date": str(e.start_date) if e.start_date else None,
                "end_date": str(e.end_date) if e.end_date else None,
                "is_current": e.is_current,
            }
            for e in profile.work_experiences
        ],
    )

    # Optionally load job from DB
    company = data.company
    position = data.position
    job_description = data.job_description or ""
    required_skills: list[str] = []

    if data.job_id:
        result = await db.execute(
            select(JobPosting).where(JobPosting.id == data.job_id, public_job_condition())
        )
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job nicht gefunden.")
        company = company or job.company
        position = position or job.title
        job_description = job_description or job.description or ""
        required_skills = list(job.required_skills or [])

    result_obj = await _gen(
        profile_data=profile_data,
        company=company,
        position=position,
        job_description=job_description,
        required_skills=required_skills,
        company_context=data.company_context or "",
        tone=data.tone,
    )

    await track_ai_usage(tid, "ai_cover_letter")
    letter = CoverLetter(
        user_id=current_user.id,
        job_id=data.job_id,
        application_id=data.application_id,
        company=company,
        position=position,
        tone=data.tone,
        generated_text=result_obj.text,
        model_used=result_obj.model_used,
        ai_generated=result_obj.ai_generated,
    )
    db.add(letter)
    await db.flush()
    await db.refresh(letter)
    return letter


@router.get(
    "/cover-letters",
    response_model=list[CoverLetterRead],
    summary="Alle generierten Anschreiben",
)
async def list_cover_letters(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CoverLetter]:
    result = await db.execute(
        select(CoverLetter)
        .where(CoverLetter.user_id == current_user.id)
        .order_by(CoverLetter.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete(
    "/cover-letters/{letter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Anschreiben löschen",
)
async def delete_cover_letter(
    letter_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(CoverLetter).where(
            CoverLetter.id == letter_id,
            CoverLetter.user_id == current_user.id,
        )
    )
    letter = result.scalar_one_or_none()
    if not letter:
        raise HTTPException(status_code=404, detail="Anschreiben nicht gefunden.")
    await db.delete(letter)
    await db.flush()


# ── CV Adjuster (Sprint 0.6) ──────────────────────────────────────────────────


@router.post(
    "/cv-adjust",
    dependencies=[Depends(require_ai_consent)],
    response_model=CVAdjustResponse,
    summary="CV für eine Stelle optimieren (KI-Empfehlungen)",
)
async def adjust_cv(
    data: CVAdjustRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CVAdjustResponse:
    """Return AI suggestions for CV reordering + summary rewrite for a specific job."""
    from app.ai.generators.cv_adjuster import adjust_cv_for_job
    from app.jobs.models import JobPosting
    from app.jobs.publication import public_job_condition

    tid = str(current_user.tenant_id) if current_user.tenant_id else None
    await _require_module(tid, "ai_cv_parser")

    profile = await get_or_create_profile(db, current_user.id)
    profile_data: dict[str, Any] = profile.structured_data or {}
    profile_data.setdefault("headline", profile.headline)
    profile_data.setdefault("summary", profile.summary)
    profile_data.setdefault("skills", [{"name": s.name, "level": s.level} for s in profile.skills])
    profile_data.setdefault(
        "work_experiences",
        [
            {
                "id": str(e.id),
                "title": e.title,
                "company": e.company,
                "description": e.description,
                "is_current": e.is_current,
            }
            for e in profile.work_experiences
        ],
    )

    company = data.company
    position = data.position
    job_description = data.job_description or ""
    required_skills: list[str] = []

    if data.job_id:
        result = await db.execute(
            select(JobPosting).where(JobPosting.id == data.job_id, public_job_condition())
        )
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job nicht gefunden.")
        job_description = job_description or job.description or ""
        required_skills = list(job.required_skills or [])

    adj = await adjust_cv_for_job(
        profile_data=profile_data,
        company=company,
        position=position,
        job_description=job_description,
        required_skills=required_skills,
    )
    await track_ai_usage(tid, "ai_cv_parser")

    return CVAdjustResponse(
        highlighted_skills=adj.highlighted_skills,
        highlighted_experience_ids=adj.highlighted_experience_ids,
        suggested_summary=adj.suggested_summary,
        tips=adj.tips,
        model_used=adj.model_used,
        ai_generated=adj.ai_generated,
        disclaimer=adj.disclaimer,
    )


# ── Interview Prep (Sprint 0.7) ───────────────────────────────────────────────


@router.post(
    "/interview-prep",
    dependencies=[Depends(require_ai_consent)],
    response_model=InterviewPrepResponse,
    summary="Interview-Vorbereitung generieren (Sprint 0.7)",
)
async def generate_interview_prep(
    data: InterviewPrepRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InterviewPrepResponse:
    """Generate tailored interview questions + STAR tips for a specific job."""
    from app.ai.generators.interview_prep import generate_interview_prep as _gen
    from app.jobs.models import JobPosting
    from app.jobs.publication import public_job_condition

    tid = str(current_user.tenant_id) if current_user.tenant_id else None
    await _require_module(tid, "ai_interview_prep")

    profile = await get_or_create_profile(db, current_user.id)
    profile_data: dict[str, Any] = profile.structured_data or {}
    profile_data.setdefault("headline", profile.headline)
    profile_data.setdefault("skills", [{"name": s.name} for s in profile.skills])
    profile_data.setdefault(
        "work_experiences",
        [
            {"title": e.title, "company": e.company, "description": e.description}
            for e in profile.work_experiences
        ],
    )

    company = data.company
    position = data.position
    job_description = data.job_description or ""
    required_skills: list[str] = []

    if data.job_id:
        result = await db.execute(
            select(JobPosting).where(JobPosting.id == data.job_id, public_job_condition())
        )
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job nicht gefunden.")
        job_description = job_description or job.description or ""
        required_skills = list(job.required_skills or [])

    prep = await _gen(
        profile_data=profile_data,
        company=company,
        position=position,
        job_description=job_description,
        required_skills=required_skills,
    )
    await track_ai_usage(tid, "ai_interview_prep")

    return InterviewPrepResponse(
        questions=[
            InterviewQuestionOut(
                category=q.category,
                question=q.question,
                star_tip=q.star_tip,
                example_answer_hint=q.example_answer_hint,
            )
            for q in prep.questions
        ],
        general_tips=prep.general_tips,
        model_used=prep.model_used,
        ai_generated=prep.ai_generated,
        disclaimer=prep.disclaimer,
    )
