"""Vermerke – operative Wissensschicht (palmscout MVP 2)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Vermerk(Base):
    """Strukturierter Vermerk, anhaftend an Kandidat, Bewerbung oder Zeitarbeit-Auftrag."""

    __tablename__ = "vermerke"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Polymorphic targets – at most one is set
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=True
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_assignments.id", ondelete="CASCADE"), nullable=True
    )

    # Content
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # präferenz | warnhinweis | beziehungswissen | dokumentenhinweis | override_grund

    text: Mapped[str] = mapped_column(Text(), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date(), nullable=True)
    strength: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)  # 1–5
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    # internal | partner | public
    source: Mapped[str | None] = mapped_column(String(100), nullable=True, default="manual")
    # manual | ai_suggestion | import

    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
