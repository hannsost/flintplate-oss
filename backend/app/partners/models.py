from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.timed_model import TimedUUIDBase


class Partnership(TimedUUIDBase):
    __tablename__ = "partnerships"
    __table_args__ = (
        Index(
            "uq_partnership_live_pair",
            "pair_key",
            unique=True,
            postgresql_where=text("status IN ('pending', 'active')"),
        ),
    )
    initiator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    pair_key: Mapped[str] = mapped_column(String(73))
    purpose: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1)


class SharedDemand(TimedUUIDBase):
    __tablename__ = "shared_demands"
    partnership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partnerships.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(120))
    required_skills: Mapped[list[str]] = mapped_column(ARRAY(String(100)))
    starts_on: Mapped[date] = mapped_column(Date)
    headcount: Mapped[int] = mapped_column(Integer)
    offered_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open")
    version: Mapped[int] = mapped_column(Integer, default=1)


class PartnerEvent(TimedUUIDBase):
    __tablename__ = "partner_events"
    partnership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partnerships.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(String(300))
