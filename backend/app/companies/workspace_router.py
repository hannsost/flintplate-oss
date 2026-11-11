"""Actionable workspace overview and permission-scoped person records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.absences.models import Absence
from app.applications.models import Application, ApplicationStatus
from app.companies.workspace_access import job_scope, workspace_user
from app.companies.workspace_schemas import (
    ActionRead,
    PeopleRead,
    PersonApplication,
    PersonDetail,
    PersonExperience,
    PersonRead,
    PersonSkill,
    TodayRead,
)
from app.database import get_db
from app.interviews.models import InterviewSchedule, InterviewScorecard
from app.jobs.access import candidate_visibility
from app.jobs.models import JobPosting
from app.journeys.models import HiringOffer, OnboardingCase, OnboardingStep
from app.profiles.models import CandidateProfile, Skill
from app.users.models import User
from app.worker.time_models import TimeEntry

router = APIRouter(prefix="/workspace")
HR = Annotated[User, Depends(workspace_user)]
DB = Annotated[AsyncSession, Depends(get_db)]


def person_read(person: User, profile: CandidateProfile | None) -> PersonRead:
    return PersonRead(
        id=person.id,
        full_name=person.full_name,
        email=person.email,
        role=person.role,
        headline=profile.headline if profile else None,
        location=profile.location if profile else None,
    )


async def visible_person(db: AsyncSession, user: User, person_id: uuid.UUID) -> User:
    person = (
        await db.execute(
            select(User).where(User.id == person_id, candidate_visibility(user.id, user.tenant_id))
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(404, "Person nicht gefunden.")
    return person


@router.get(
    "/people",
    response_model=PeopleRead,
    status_code=200,
    summary="Menschen im eigenen Arbeitsbereich finden",
)
async def people(
    user: HR,
    db: DB,
    q: str = Query("", max_length=150),
    role: Literal["all", "candidate", "worker"] = "all",
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=100),
) -> PeopleRead:
    scope = candidate_visibility(user.id, user.tenant_id)
    if role != "all":
        scope = scope & (User.role == role)
    if q.strip():
        term = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        skill_match = (
            select(Skill.id)
            .where(Skill.profile_id == CandidateProfile.id, Skill.name.ilike(term))
            .exists()
        )
        scope = scope & or_(
            User.full_name.ilike(term),
            User.email.ilike(term),
            CandidateProfile.headline.ilike(term),
            CandidateProfile.location.ilike(term),
            skill_match,
        )
    base = (
        select(User, CandidateProfile)
        .outerjoin(CandidateProfile, CandidateProfile.user_id == User.id)
        .where(scope)
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(func.lower(func.coalesce(User.full_name, User.email)), User.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return PeopleRead(
        total=total, people=[person_read(person, profile) for person, profile in rows]
    )


@router.get(
    "/people/{person_id}",
    response_model=PersonDetail,
    status_code=200,
    summary="Zusammenhängende Personenakte mit freigegebenen Vorgängen",
)
async def person_detail(person_id: uuid.UUID, user: HR, db: DB) -> PersonDetail:
    person = await visible_person(db, user, person_id)
    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == person.id))
    ).scalar_one_or_none()
    applications = (
        (
            await db.execute(
                select(Application)
                .join(JobPosting, JobPosting.id == Application.job_id)
                .where(Application.user_id == person.id, job_scope(user))
                .order_by(Application.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    # Candidate-owned notes and applications to other companies never enter this response.
    return PersonDetail(
        **person_read(person, profile).model_dump(),
        summary=profile.summary if profile else None,
        skills=(
            [PersonSkill(name=skill.name, source=skill.source) for skill in profile.skills]
            if profile
            else []
        ),
        experience=(
            [
                PersonExperience(
                    title=item.title,
                    company=item.company,
                    description=item.description,
                    source=item.source,
                )
                for item in profile.work_experiences
            ]
            if profile
            else []
        ),
        applications=[
            PersonApplication(
                id=application.id,
                position=application.position,
                status=application.status.value,
                updated_at=application.updated_at,
            )
            for application in applications
        ],
        actions=[
            ActionRead(
                id=f"application:{application.id}",
                kind="application",
                title=application.position,
                detail="Bewerbung im Arbeitsbereich",
                href=f"/dashboard/applications?application={application.id}",
                action_label="Bewerbung öffnen",
            )
            for application in applications
            if application.status not in {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
        ],
    )


@router.get(
    "/today",
    response_model=TodayRead,
    status_code=200,
    summary="Nächste Schritte im Arbeitsbereich",
)
async def today(user: HR, db: DB) -> TodayRead:
    now = datetime.now(UTC)
    actions: list[ActionRead] = []
    applications = (
        await db.execute(
            select(Application, User)
            .join(User, User.id == Application.user_id)
            .join(JobPosting, JobPosting.id == Application.job_id)
            .where(
                job_scope(user),
                User.is_active.is_(True),
                Application.status.in_([ApplicationStatus.APPLIED, ApplicationStatus.SCREENING]),
            )
            .order_by(Application.updated_at)
            .limit(30)
        )
    ).all()
    for application, candidate in applications:
        actions.append(
            ActionRead(
                id=f"application:{application.id}",
                kind="application",
                title=f"Bewerbung prüfen: {candidate.full_name or candidate.email}",
                detail=application.position,
                href=f"/dashboard/people?person={candidate.id}",
                action_label="Person ansehen",
                due_at=application.updated_at,
                urgent=application.updated_at < now - timedelta(days=7),
            )
        )
    interviews = (
        await db.execute(
            select(InterviewSchedule, Application, User)
            .join(Application, Application.id == InterviewSchedule.application_id)
            .join(User, User.id == Application.user_id)
            .join(JobPosting, JobPosting.id == Application.job_id)
            .where(
                job_scope(user),
                InterviewSchedule.status.in_(["confirmed", "proposed"]),
                InterviewSchedule.scheduled_at >= now - timedelta(days=30),
                InterviewSchedule.scheduled_at <= now + timedelta(days=7),
                or_(
                    InterviewSchedule.scheduled_at >= now,
                    ~select(InterviewScorecard.id)
                    .where(InterviewScorecard.application_id == Application.id)
                    .exists(),
                ),
            )
            .order_by(InterviewSchedule.scheduled_at)
            .limit(30)
        )
    ).all()
    for interview, application, candidate in interviews:
        past = interview.scheduled_at < now
        actions.append(
            ActionRead(
                id=f"interview:{interview.id}",
                kind="feedback" if past else "interview",
                title=f"{'Feedback ergänzen' if past else 'Gespräch vorbereiten'}: {candidate.full_name or candidate.email}",
                detail=application.position,
                href=(
                    f"/dashboard/applications?application={application.id}"
                    if past
                    else "/dashboard/interviews"
                ),
                action_label="Feedback öffnen" if past else "Termin öffnen",
                due_at=interview.scheduled_at,
                urgent=past,
            )
        )
    for count, kind, title, href in [
        (
            (
                await db.execute(
                    select(func.count(TimeEntry.id)).where(
                        TimeEntry.tenant_id == user.tenant_id,
                        TimeEntry.status.in_(["submitted", "correction_requested"]),
                    )
                )
            ).scalar_one(),
            "time",
            "Zeiterfassungen warten auf Freigabe",
            "/dashboard/zeitarbeit/time-approval",
        ),
        (
            (
                await db.execute(
                    select(func.count(Absence.id)).where(
                        Absence.tenant_id == user.tenant_id, Absence.status == "pending"
                    )
                )
            ).scalar_one(),
            "absence",
            "Abwesenheitsanträge warten auf Entscheidung",
            "/dashboard/zeitarbeit/absences",
        ),
    ]:
        if count:
            actions.append(
                ActionRead(
                    id=kind,
                    kind=kind,
                    title=title,
                    detail=f"{count} offene Vorgänge",
                    href=href,
                    action_label="Anträge prüfen",
                )
            )
    pending_offers = (
        await db.execute(
            select(HiringOffer)
            .where(
                HiringOffer.tenant_id == user.tenant_id,
                or_(
                    (HiringOffer.status == "review") & (HiringOffer.approver_id == user.id),
                    (HiringOffer.status == "accepted")
                    & (HiringOffer.created_by == user.id)
                    & ~select(OnboardingCase.id)
                    .where(OnboardingCase.offer_id == HiringOffer.id)
                    .exists(),
                ),
            )
            .order_by(HiringOffer.expires_on)
            .limit(30)
        )
    ).scalars()
    for offer in pending_offers:
        review = offer.status == "review"
        actions.append(
            ActionRead(
                id=f"offer:{offer.id}",
                kind="offer",
                title="Angebot freigeben" if review else "Onboarding vorbereiten",
                detail=offer.title,
                href=(
                    f"/dashboard/offers?application={offer.application_id}"
                    if review
                    else f"/dashboard/onboarding?offer={offer.id}"
                ),
                action_label="Angebot prüfen" if review else "Onboarding öffnen",
                due_at=datetime.combine(
                    offer.expires_on if review else offer.start_date, datetime.min.time(), UTC
                ),
                urgent=offer.expires_on < now.date() if review else offer.start_date <= now.date(),
            )
        )
    steps = (
        await db.execute(
            select(OnboardingStep, OnboardingCase, User)
            .join(OnboardingCase, OnboardingCase.id == OnboardingStep.case_id)
            .join(User, User.id == OnboardingCase.person_id)
            .where(
                OnboardingCase.tenant_id == user.tenant_id,
                OnboardingStep.completed_at.is_(None),
                OnboardingStep.due_on <= now.date() + timedelta(days=7),
                or_(OnboardingStep.assignee_id == user.id, OnboardingCase.owner_id == user.id),
            )
            .order_by(OnboardingStep.due_on)
            .limit(30)
        )
    ).all()
    for step, case, person in steps:
        actions.append(
            ActionRead(
                id=f"onboarding:{step.id}",
                kind="onboarding",
                title=step.title,
                detail=person.full_name or person.email,
                href=f"/dashboard/onboarding?offer={case.offer_id}",
                action_label="Aufgabe öffnen",
                due_at=datetime.combine(step.due_on, datetime.min.time(), UTC),
                urgent=step.due_on < now.date(),
            )
        )
    actions.sort(
        key=lambda action: (
            not action.urgent,
            action.due_at or now + timedelta(days=365),
            action.id,
        )
    )
    return TodayRead(generated_at=now, actions=actions)
