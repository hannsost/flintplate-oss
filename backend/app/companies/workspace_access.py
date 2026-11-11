"""Reusable workspace authorization, independent of UI and token role claims."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import ColumnElement

from app.jobs.models import JobPosting
from app.security import get_current_user
from app.users.models import User


def workspace_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in {"admin", "recruiter"} or user.tenant_id is None:
        raise HTTPException(403, "Ein Firmenarbeitsbereich ist erforderlich.")
    return user


def workspace_admin(user: Annotated[User, Depends(workspace_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Nur die Firmenadministration darf Zugänge verwalten.")
    return user


def job_scope(user: User) -> ColumnElement[bool]:
    if user.tenant_id is not None:
        return JobPosting.tenant_id == user.tenant_id
    return (JobPosting.owner_id == user.id) & JobPosting.tenant_id.is_(None)
