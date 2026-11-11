"""Enforce explicit user consent before processing personal data with AI."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security import get_current_user
from app.users.models import PrivacyConsent, User


async def require_ai_consent(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    consent = await db.scalar(
        select(PrivacyConsent).where(PrivacyConsent.user_id == current_user.id)
    )
    if consent is None or not consent.ai_opt_in or consent.ai_opt_in_at is None:
        raise HTTPException(
            status_code=403,
            detail="Bitte stimmen Sie der KI-Verarbeitung zuerst in den Kontoeinstellungen zu.",
        )
