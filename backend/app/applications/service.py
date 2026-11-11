"""Bewerbungs-Tracker service – Sprint 0.5 + WS events Sprint 1.1 + Auto-Tracking Sprint 1.8."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.applications.models import Application, ApplicationHistory, ApplicationStatus
from app.applications.schemas import ApplicationCreate, ApplicationUpdate

# ── Platform detection ────────────────────────────────────────────────────────

_PLATFORM_RULES: list[tuple[str, str]] = [
    (r"linkedin\.com", "LinkedIn"),
    (r"indeed\.com", "Indeed"),
    (r"stepstone\.", "StepStone"),
    (r"xing\.com", "XING"),
    (r"monster\.", "Monster"),
    (r"glassdoor\.", "Glassdoor"),
    (r"arbeitsagentur\.", "Bundesagentur"),
    (r"palmscout\.", "palmscout"),
    (r"hireos\.", "palmscout"),
    (r"join\.com", "Join"),
    (r"campusjäger\.|campusjaeger\.", "Campusjäger"),
    (r"absolventa\.", "Absolventa"),
    (r"kununu\.", "Kununu"),
]


def detect_platform(url: str | None) -> str | None:
    if not url:
        return None
    for pattern, name in _PLATFORM_RULES:
        if re.search(pattern, url, re.IGNORECASE):
            return name
    return "Sonstige"


async def _get_with_history(db: AsyncSession, app_id: uuid.UUID) -> Application | None:
    result = await db.execute(
        select(Application)
        .where(Application.id == app_id)
        .options(selectinload(Application.history))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


def _app_event(type_: str, app: Application) -> dict[str, Any]:
    return {
        "type": type_,
        "payload": {
            "id": str(app.id),
            "status": app.status.value,
            "company": app.company,
            "position": app.position,
            "updated_at": app.updated_at.isoformat() if app.updated_at else None,
        },
    }


async def create_application(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: ApplicationCreate,
) -> Application:
    from app.ws.manager import manager

    if data.job_id is not None:
        from app.jobs.publication import require_public_job

        await require_public_job(db, data.job_id, lock=True)
    payload = data.model_dump(exclude_none=True)
    # Auto-detect source platform from job URL if not explicitly provided
    if not payload.get("source_platform") and payload.get("job_url"):
        detected = detect_platform(payload["job_url"])
        if detected:
            payload["source_platform"] = detected
    app = Application(user_id=user_id, **payload)
    db.add(app)
    await db.flush()
    await db.refresh(app, ["history"])

    db.add(
        ApplicationHistory(
            application_id=app.id,
            from_status=None,
            to_status=app.status,
            note="Bewerbung angelegt",
        )
    )
    await db.flush()

    result = await _get_with_history(db, app.id)
    await manager.send_to_user(str(user_id), _app_event("application.created", result))  # type: ignore[arg-type]
    return result  # type: ignore[return-value]


async def get_applications(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[Application]:
    result = await db.execute(
        select(Application)
        .where(Application.user_id == user_id)
        .options(selectinload(Application.history))
        .order_by(Application.updated_at.desc())
    )
    return list(result.scalars().all())


async def update_application(
    db: AsyncSession,
    app: Application,
    data: ApplicationUpdate,
) -> Application:
    from app.ws.manager import manager

    old_status = app.status
    update_data = data.model_dump(exclude_none=True, exclude={"note"})

    for key, val in update_data.items():
        setattr(app, key, val)

    new_status = data.status
    if new_status and new_status != old_status:
        db.add(
            ApplicationHistory(
                application_id=app.id,
                from_status=old_status,
                to_status=new_status,
                note=data.note,
            )
        )
        if new_status == ApplicationStatus.APPLIED and not app.applied_at:
            app.applied_at = datetime.now(UTC)

    await db.flush()
    result = await _get_with_history(db, app.id)
    await manager.send_to_user(str(app.user_id), _app_event("application.updated", result))  # type: ignore[arg-type]
    return result  # type: ignore[return-value]


async def delete_application(db: AsyncSession, app: Application) -> None:
    from app.ws.manager import manager

    event = {
        "type": "application.deleted",
        "payload": {"id": str(app.id)},
    }
    user_id = str(app.user_id)
    await db.delete(app)
    await db.flush()
    await manager.send_to_user(user_id, event)
