"""Publication policy shared by all candidate-facing reads and writes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.jobs.models import JobPosting, JobPublicationEvent
from app.jobs.schemas import JobPublicationChange
from app.users.models import User


def public_job_condition() -> ColumnElement[bool]:
    """A suspended tenant or a removed/moved owner immediately withdraws its jobs."""
    active_workspace = (
        select(Customer.id)
        .join(User, User.tenant_id == Customer.id)
        .where(
            Customer.id == JobPosting.tenant_id,
            Customer.status.in_(["active", "trial"]),
            or_(
                Customer.status != "trial",
                Customer.trial_ends_at.is_(None),
                Customer.trial_ends_at > datetime.now(UTC),
            ),
            User.id == JobPosting.owner_id,
            User.is_active.is_(True),
            User.role.in_(["recruiter", "admin"]),
        )
        .correlate(JobPosting)
        .exists()
    )
    reviewed_import = and_(
        JobPosting.owner_id.is_(None),
        JobPosting.tenant_id.is_(None),
        JobPosting.source != "recruiter",
    )
    return and_(
        JobPosting.publication_status == "published",
        JobPosting.published_at <= datetime.now(UTC),
        JobPosting.expires_at > datetime.now(UTC),
        or_(active_workspace, reviewed_import),
    )


async def require_public_job(
    db: AsyncSession, job_id: uuid.UUID, *, lock: bool = False
) -> JobPosting:
    query = select(JobPosting).where(JobPosting.id == job_id)
    # Lock first, then check policy in a fresh statement: an archive that committed
    # while waiting for this lock must also invalidate the application.
    if lock:
        await db.execute(query.with_for_update())
    job = await db.scalar(
        query.where(public_job_condition()).execution_options(populate_existing=True)
    )
    if job is None:
        raise HTTPException(404, "Diese Stelle ist nicht veröffentlicht oder nicht mehr verfügbar.")
    return job


def check_version(job: JobPosting, expected: int) -> None:
    if job.version != expected:
        raise HTTPException(409, "Das Inserat wurde geändert. Bitte neu laden und erneut prüfen.")


def record_change(
    db: AsyncSession,
    job: JobPosting,
    actor_id: uuid.UUID | None,
    action: str,
    note: str | None = None,
) -> None:
    job.version += 1
    db.add(
        JobPublicationEvent(
            job_id=job.id, actor_id=actor_id, version=job.version, action=action, note=note
        )
    )


async def change_publication(
    db: AsyncSession,
    job: JobPosting,
    actor_id: uuid.UUID | None,
    action: Literal["publish", "withdraw", "archive"],
    data: JobPublicationChange,
) -> JobPosting:
    check_version(job, data.expected_version)
    now = datetime.now(UTC)
    if action == "publish":
        if job.publication_status == "archived":
            raise HTTPException(
                409, "Archivierte Inserate können nicht erneut veröffentlicht werden."
            )
        if not data.rights_confirmed:
            raise HTTPException(
                422, "Bitte Inhalt und Berechtigung zur Veröffentlichung bestätigen."
            )
        if not (
            job.title.strip()
            and job.company.strip()
            and (job.description or "").strip()
            and (job.location or job.is_remote)
            and job.employment_type
        ):
            raise HTTPException(
                422,
                "Titel, Unternehmen, Beschreibung, Arbeitsort oder Remote und Beschäftigungsart sind erforderlich.",
            )
        if (
            (job.salary_min is not None and job.salary_min < 0)
            or (job.salary_max is not None and job.salary_max < 0)
            or (
                job.salary_min is not None
                and job.salary_max is not None
                and job.salary_min > job.salary_max
            )
        ):
            raise HTTPException(422, "Bitte die Gehaltsspanne prüfen.")
        if data.expires_at is None or not now < data.expires_at <= now + timedelta(days=180):
            raise HTTPException(
                422, "Das Ablaufdatum muss in der Zukunft und innerhalb von 180 Tagen liegen."
            )
        if job.owner_id is not None:
            active = await db.scalar(
                select(Customer.id)
                .join(User, User.tenant_id == Customer.id)
                .where(
                    Customer.id == job.tenant_id,
                    User.id == job.owner_id,
                    User.is_active.is_(True),
                    User.role.in_(["recruiter", "admin"]),
                    Customer.status.in_(["active", "trial"]),
                    or_(
                        Customer.status != "trial",
                        Customer.trial_ends_at.is_(None),
                        Customer.trial_ends_at > now,
                    ),
                )
            )
            if active is None:
                raise HTTPException(
                    403,
                    "Für die Veröffentlichung ist ein aktiver Unternehmensbereich erforderlich.",
                )
        elif not job.url or not (data.note or "").strip():
            raise HTTPException(
                422,
                "Importe benötigen einen Quellenlink und einen Vermerk zu den Veröffentlichungsrechten.",
            )
        job.publication_status = "published"
        job.published_at = now
        job.expires_at = data.expires_at
        job.archived_at = None
    elif action == "withdraw":
        if job.publication_status != "published":
            raise HTTPException(409, "Nur veröffentlichte Inserate können zurückgezogen werden.")
        job.publication_status = "draft"
    else:
        if job.publication_status == "archived":
            raise HTTPException(409, "Das Inserat ist bereits archiviert.")
        job.publication_status = "archived"
        job.archived_at = now
    record_change(db, job, actor_id, action, data.note)
    await db.flush()
    return job
