"""Map View schemas – Sprint MVP-2."""

from __future__ import annotations

from pydantic import BaseModel


class MapAssignmentOut(BaseModel):
    id: str
    title: str
    location: str | None
    lat: float | None
    lng: float | None
    status: str
    required_skills: list[str]
    worker_count: int  # number of active dispositions

    model_config = {"from_attributes": True}


class MapWorkerOut(BaseModel):
    user_id: str
    full_name: str | None
    preferred_location: str | None
    lat: float | None
    lng: float | None
    is_in_pool: bool
    aueg_status: str
    aueg_remaining_months: float
    current_assignment_id: str | None
    current_assignment_title: str | None

    model_config = {"from_attributes": True}


class MapDataResponse(BaseModel):
    assignments: list[MapAssignmentOut]
    workers: list[MapWorkerOut]
