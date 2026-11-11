"""Feedback endpoint – Sprint 0.8."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.feedback.models import Feedback, FeedbackCategory
from app.security import get_current_user_optional
from app.users.models import User

router = APIRouter()


class FeedbackCreate(BaseModel):
    category: FeedbackCategory = FeedbackCategory.GENERAL
    message: str = Field(min_length=5, max_length=2000)
    email: str | None = Field(default=None, max_length=255)
    page_url: str | None = Field(default=None, max_length=500)


class FeedbackRead(BaseModel):
    id: str
    category: FeedbackCategory
    message: str
    created_at: str


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Feedback einreichen (anonym oder eingeloggt)",
)
async def submit_feedback(
    data: FeedbackCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> dict[str, Any]:
    fb = Feedback(
        user_id=current_user.id if current_user else None,
        email=data.email or (current_user.email if current_user else None),
        category=data.category,
        message=data.message,
        page_url=data.page_url,
    )
    db.add(fb)
    await db.flush()
    return {"id": str(fb.id), "status": "received"}
