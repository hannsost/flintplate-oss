"""Profile endpoints – Sprint 0.2 + 0.7 (export)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.consent import require_ai_consent
from app.ai.parsers.cv_parser import parse_cv_file
from app.database import get_db
from app.profiles.models import CandidateProfile
from app.profiles.schemas import CVUploadResponse, ProfileCreate, ProfileRead, ProfileUpdate
from app.profiles.service import (
    create_profile,
    get_or_create_profile,
    get_profile_by_id,
    update_profile,
)
from app.security import get_current_user
from app.uploads.service import delete_cv, save_cv
from app.users.models import User

router = APIRouter()


@router.post(
    "",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Kandidaten-Profil anlegen",
)
async def create_my_profile(
    data: ProfileCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CandidateProfile:
    return await create_profile(db, current_user.id, data)


@router.get(
    "/me",
    response_model=ProfileRead,
    summary="Eigenes Profil abrufen (oder leeres anlegen)",
)
async def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CandidateProfile:
    return await get_or_create_profile(db, current_user.id)


@router.patch(
    "/{profile_id}",
    response_model=ProfileRead,
    summary="Profil aktualisieren",
)
async def patch_profile(
    profile_id: uuid.UUID,
    data: ProfileUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CandidateProfile:
    profile = await get_profile_by_id(db, profile_id)
    if profile.user_id != current_user.id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Profil")
    return await update_profile(db, profile, data)


@router.post(
    "/me/cv",
    dependencies=[Depends(require_ai_consent)],
    response_model=CVUploadResponse,
    summary="CV hochladen und automatisch parsen",
)
async def upload_cv(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(..., description="PDF, DOC oder DOCX – max. 10 MB"),
) -> CVUploadResponse:
    profile = await get_or_create_profile(db, current_user.id)

    # Remove old CV if exists
    if profile.cv_file_path:
        await delete_cv(profile.cv_file_path)

    file_path, original_filename = await save_cv(file, current_user.id)
    profile.cv_file_path = file_path
    profile.cv_original_filename = original_filename

    # Phase 0 mock parse
    parsed = await parse_cv_file(file_path, original_filename)
    structured = parsed.to_structured_data()
    profile.structured_data = structured
    profile.raw_cv_text = {"text": parsed.raw_text[:5000]}  # truncate for storage

    await db.flush()
    # Flush expires server-generated updated_at; load it before Pydantic reads
    # attributes outside SQLAlchemy's async greenlet.
    await db.refresh(profile)
    await db.refresh(profile, ["work_experiences", "educations", "skills"])

    return CVUploadResponse(
        profile=ProfileRead.model_validate(profile),
        parse_status="parsed",
        extracted_fields=structured,
    )


# ── Export endpoints (Sprint 0.7) ─────────────────────────────────────────────

from sqlalchemy import select  # noqa: E402


async def _load_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden.")
    return user


@router.get(
    "/me/export/pdf",
    summary="CV als PDF exportieren (WeasyPrint)",
    response_class=Response,
    tags=["export"],
)
async def export_pdf(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    from app.profiles.export import build_pdf

    profile = await get_or_create_profile(db, current_user.id)
    try:
        pdf_bytes = build_pdf(profile, current_user)
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="PDF-Export nicht verfügbar (WeasyPrint nicht installiert).",
        ) from None
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=FlintPlate_cv.pdf"},
    )


@router.get(
    "/me/export/docx",
    summary="CV als DOCX exportieren",
    response_class=Response,
    tags=["export"],
)
async def export_docx(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    from app.profiles.export import build_docx

    profile = await get_or_create_profile(db, current_user.id)
    docx_bytes = build_docx(profile, current_user)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=FlintPlate_cv.docx"},
    )


@router.get(
    "/me/export/linkedin",
    summary="LinkedIn-optimierten Profiltext exportieren",
    tags=["export"],
)
async def export_linkedin(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    from app.profiles.export import build_linkedin_text

    profile = await get_or_create_profile(db, current_user.id)
    return {"text": build_linkedin_text(profile)}


@router.get(
    "/me/export/link",
    summary="FlintPlate Profil-Link",
    tags=["export"],
)
async def export_link(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    import os

    profile = await get_or_create_profile(db, current_user.id)
    base_url = os.environ.get("FRONTEND_URL", "http://localhost:3001")
    return {
        "url": f"{base_url}/profile/{profile.id}",
        "profile_id": str(profile.id),
    }


# ── Public profile view (no auth required) ───────────────────────────────────


@router.post(
    "/me/export/link",
    response_model=dict[str, str],
    status_code=200,
    summary="Eigenes Profil ausdrücklich über einen öffentlichen Link freigeben",
)
async def publish_profile_link(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    profile = await get_or_create_profile(db, current_user.id)
    profile.is_public = True
    await db.commit()
    return await export_link(current_user, db)


@router.delete(
    "/me/export/link",
    response_model=None,
    status_code=204,
    summary="Öffentlichen Profil-Link widerrufen",
)
async def revoke_profile_link(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    profile = await get_or_create_profile(db, current_user.id)
    profile.is_public = False
    await db.commit()


@router.get(
    "/{profile_id}",
    response_model=ProfileRead,
    summary="Öffentliches Profil anzeigen (kein Auth erforderlich)",
)
async def get_public_profile(
    profile_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CandidateProfile:
    profile = await get_profile_by_id(db, profile_id)
    if not profile or not profile.is_public:
        raise HTTPException(status_code=404, detail="Profil nicht gefunden.")
    return profile


# ── Skills Gap Analysis (Sprint 1.4) ─────────────────────────────────────────


@router.get(
    "/me/gaps",
    summary="Skills-Gap Analyse – fehlende Markt-Skills + Kurs-Empfehlungen",
)
async def get_my_gaps(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    from app.jobs.service import get_profile_gap_analysis

    profile = await get_or_create_profile(db, current_user.id)
    gap = await get_profile_gap_analysis(db, profile.id)
    return gap.model_dump()
