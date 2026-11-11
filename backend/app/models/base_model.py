"""Base model with UUID primary key – use for all palmscout entities."""

from __future__ import annotations

import uuid

from sqlalchemy import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class UUIDBase(TimestampMixin, Base):
    """Abstract base: UUID PK + created_at + updated_at.

    Usage:
        class User(UUIDBase):
            __tablename__ = "users"
            ...
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
