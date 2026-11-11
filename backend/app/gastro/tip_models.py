"""Explicit links between payroll time entries and FlintPlate service shifts."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class TipTimeAttribution(GastroBase):
    """A manager's attribution, independent of the two legacy assignment tables."""

    __tablename__ = "fp_tip_time_attributions"
    __table_args__ = (UniqueConstraint("entry_id", "shift_id", name="uq_fp_tip_time_attribution"),)
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("time_entries.id"), index=True)
    shift_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_shifts.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    entry_hash: Mapped[str] = mapped_column(String(64))
    shift_hash: Mapped[str] = mapped_column(String(64))
