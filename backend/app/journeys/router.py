"""Reviewed offers and onboarding with explicit transitions and person-level access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application, ApplicationHistory, ApplicationStatus
from app.companies.workspace_access import job_scope, workspace_user
from app.database import get_db
from app.jobs.models import JobPosting
from app.journeys.models import HiringOffer, OnboardingCase, OnboardingStep
from app.journeys.schemas import (
    Activation,
    ApprovalPolicy,
    CaseCreate,
    CaseRead,
    Completion,
    OfferAction,
    OfferCreate,
    OfferDecision,
    OfferEdit,
    OfferPrivate,
    OfferRead,
    StepEdit,
    StepRead,
    TeamOption,
    TemplateRead,
)
from app.journeys.service import (
    TEMPLATES,
    application_open,
    can_self_approve,
    case_access,
    check_version,
    offer_access,
    offer_open,
    private_offer,
    read_case,
    record,
    team_member,
)
from app.notifications.service import create_and_push
from app.pipeline.access import require_application
from app.security import get_current_user
from app.users.models import User
from app.worker.models import ALL_MODULES, WorkerSettings

router = APIRouter(prefix="/workspace")
HR = Annotated[User, Depends(workspace_user)]
Current = Annotated[User, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/journeys/approval-policy",
    response_model=ApprovalPolicy,
    status_code=200,
    summary="Persönliche Berechtigung zur Angebotsfreigabe",
)
async def approval_policy(user: HR, db: DB) -> ApprovalPolicy:
    return ApprovalPolicy(self_approval_allowed=await can_self_approve(db, user))


@router.get(
    "/journeys/team",
    response_model=list[TeamOption],
    status_code=200,
    summary="Zuständige Personen für Freigaben und Onboarding",
)
async def team(user: HR, db: DB) -> list[TeamOption]:
    users = (
        await db.execute(
            select(User)
            .where(
                User.tenant_id == user.tenant_id,
                User.is_active.is_(True),
                User.role.in_(["admin", "recruiter"]),
            )
            .order_by(User.full_name, User.id)
            .limit(500)
        )
    ).scalars()
    return [
        TeamOption(id=member.id, full_name=member.full_name or member.email, role=member.role)
        for member in users
    ]


@router.get(
    "/offers/mine",
    response_model=list[OfferRead],
    status_code=200,
    summary="Meine bereitgestellten Angebote",
)
async def my_offers(user: Current, db: DB) -> list[HiringOffer]:
    return list(
        (
            await db.execute(
                select(HiringOffer)
                .join(Application, Application.id == HiringOffer.application_id)
                .where(Application.user_id == user.id, HiringOffer.shared_at.is_not(None))
                .order_by(HiringOffer.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )


@router.get(
    "/offers",
    response_model=list[OfferPrivate],
    status_code=200,
    summary="Angebote im Arbeitsbereich",
)
async def offers(
    user: HR, db: DB, application_id: uuid.UUID | None = None, offset: int = Query(0, ge=0)
) -> list[OfferPrivate]:
    query = (
        select(HiringOffer)
        .join(Application, Application.id == HiringOffer.application_id)
        .join(JobPosting, JobPosting.id == Application.job_id)
        .where(HiringOffer.tenant_id == user.tenant_id, job_scope(user))
    )
    if application_id:
        query = query.where(HiringOffer.application_id == application_id)
    records = (
        await db.execute(query.order_by(HiringOffer.created_at.desc()).offset(offset).limit(100))
    ).scalars()
    return [await private_offer(db, offer) for offer in records]


@router.post(
    "/offers",
    response_model=OfferPrivate,
    status_code=201,
    summary="Angebotsentwurf für eine Bewerbung anlegen",
)
async def create_offer(data: OfferCreate, user: HR, db: DB) -> OfferPrivate:
    application = await require_application(db, data.application_id, user)
    await db.refresh(application, with_for_update=True)
    if application.status in {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}:
        raise HTTPException(409, "Dieser Bewerbungsprozess ist abgeschlossen.")
    if await db.scalar(
        select(HiringOffer.id).where(
            HiringOffer.application_id == application.id,
            HiringOffer.status.not_in(["declined", "withdrawn"]),
        )
    ):
        raise HTTPException(409, "Zu dieser Bewerbung gibt es bereits ein Angebot.")
    offer = HiringOffer(tenant_id=user.tenant_id, created_by=user.id, **data.model_dump())
    db.add(offer)
    await db.flush()
    record(db, offer, user)
    await db.flush()
    return await private_offer(db, offer)


@router.patch(
    "/offers/{offer_id}",
    response_model=OfferPrivate,
    status_code=200,
    summary="Angebotsentwurf versioniert bearbeiten",
)
async def edit_offer(offer_id: uuid.UUID, data: OfferEdit, user: HR, db: DB) -> OfferPrivate:
    offer = await offer_access(db, offer_id, user, lock=True)
    check_version(offer, data.version)
    if offer.status != "draft" or offer.created_by != user.id:
        raise HTTPException(409, "Nur die erstellende Person kann einen Entwurf bearbeiten.")
    for key, value in data.model_dump(exclude={"version"}).items():
        setattr(offer, key, value)
    offer.version += 1
    record(db, offer, user, "Entwurf bearbeitet")
    await db.flush()
    return await private_offer(db, offer)


@router.post(
    "/offers/{offer_id}/actions",
    response_model=OfferPrivate,
    status_code=200,
    summary="Angebot prüfen, freigeben oder bereitstellen",
)
async def act(offer_id: uuid.UUID, data: OfferAction, user: HR, db: DB) -> OfferPrivate:
    offer = await offer_access(db, offer_id, user, lock=True)
    check_version(offer, data.version)
    if data.action != "withdraw":
        await application_open(db, offer)
    creator = offer.created_by == user.id
    if data.action == "submit":
        if not creator or offer.status != "draft":
            raise HTTPException(409, "Nur ein eigener Entwurf kann zur Freigabe vorgelegt werden.")
        offer_open(offer)
        approver = await team_member(db, data.approver_id, user.tenant_id, admin=True)
        offer.approver_id = approver.id
        if approver.id == user.id:
            if not await can_self_approve(db, user):
                raise HTTPException(422, "Für die Freigabe ist eine zweite Person erforderlich.")
            offer.status = "approved"
            data.note = (
                "Persönliche Freigabe durch den Firmeninhaber im Einzelrecruiting. "
                + (data.note or "")
            )[:2000]
        else:
            offer.status = "review"
            await create_and_push(
                db=db,
                user_id=approver.id,
                type_="offer.review",
                title="Angebot zur Freigabe",
                body=offer.title,
                meta={"href": "/dashboard/offers"},
            )
    elif data.action in {"approve", "changes"}:
        if (
            offer.status != "review"
            or user.id != offer.approver_id
            or user.role != "admin"
            or creator
        ):
            raise HTTPException(
                403, "Nur die zuständige Firmenadministration kann dieses Angebot prüfen."
            )
        offer_open(offer)
        offer.status = "approved" if data.action == "approve" else "draft"
    elif data.action == "share":
        if offer.status != "approved" or not (creator or user.role == "admin"):
            raise HTTPException(
                409, "Dieses Angebot ist noch nicht zur Bereitstellung freigegeben."
            )
        offer_open(offer)
        # A removed or demoted approver invalidates the outstanding approval.
        await team_member(db, offer.approver_id, user.tenant_id, admin=True)
        if offer.approver_id == offer.created_by:
            creator_user = await team_member(db, offer.created_by, user.tenant_id, admin=True)
            if not await can_self_approve(db, creator_user):
                raise HTTPException(
                    409, "Bitte die Freigabe nach Änderung des Arbeitsbereichs erneut prüfen."
                )
        application = await application_open(db, offer)
        offer.status, offer.shared_at = "shared", datetime.now(UTC)
        db.add(
            ApplicationHistory(
                application_id=application.id,
                from_status=application.status,
                to_status=ApplicationStatus.OFFER,
                note="Freigegebenes Angebot im Bewerberkonto bereitgestellt.",
            )
        )
        application.status = ApplicationStatus.OFFER
        await create_and_push(
            db=db,
            user_id=application.user_id,
            type_="offer.shared",
            title="Dein Angebot ist bereit",
            body=offer.title,
            meta={"href": "/offers"},
        )
    else:
        if not (creator or user.role == "admin") or offer.status in {
            "accepted",
            "declined",
            "withdrawn",
        }:
            raise HTTPException(409, "Dieses Angebot kann nicht zurückgezogen werden.")
        offer.status = "withdrawn"
    offer.version += 1
    record(db, offer, user, data.note)
    await db.flush()
    return await private_offer(db, offer)


@router.post(
    "/offers/{offer_id}/decision",
    response_model=OfferRead,
    status_code=200,
    summary="Eigenes Angebot annehmen oder ablehnen",
)
async def decide(offer_id: uuid.UUID, data: OfferDecision, user: Current, db: DB) -> HiringOffer:
    offer = await offer_access(db, offer_id, user, private=False, lock=True)
    check_version(offer, data.version)
    if offer.status != "shared":
        raise HTTPException(409, "Für dieses Angebot ist keine Antwort mehr möglich.")
    offer_open(offer)
    await application_open(db, offer)
    offer.status, offer.version = data.decision, offer.version + 1
    record(db, offer, user)
    if offer.created_by:
        await create_and_push(
            db=db,
            user_id=offer.created_by,
            type_="offer.decision",
            title="Antwort auf dein Angebot",
            body=f"{offer.title}: {'angenommen' if data.decision == 'accepted' else 'abgelehnt'}",
            meta={"href": "/dashboard/offers"},
        )
    await db.flush()
    return offer


@router.get(
    "/onboarding/templates",
    response_model=list[TemplateRead],
    status_code=200,
    summary="Vorlagen für Eintritt, Vermittlung und Einsatz",
)
async def templates(user: HR) -> list[TemplateRead]:
    return TEMPLATES


@router.get(
    "/onboarding/mine",
    response_model=list[CaseRead],
    status_code=200,
    summary="Mein Onboarding und meine sichtbaren Aufgaben",
)
async def my_cases(user: Current, db: DB) -> list[CaseRead]:
    cases = (
        await db.execute(
            select(OnboardingCase)
            .where(OnboardingCase.person_id == user.id)
            .order_by(OnboardingCase.start_date.desc())
            .limit(100)
        )
    ).scalars()
    return [await read_case(db, case, private=False) for case in cases]


@router.get(
    "/onboarding",
    response_model=list[CaseRead],
    status_code=200,
    summary="Onboarding im Arbeitsbereich",
)
async def cases(user: HR, db: DB, offset: int = Query(0, ge=0)) -> list[CaseRead]:
    cases = (
        await db.execute(
            select(OnboardingCase)
            .where(OnboardingCase.tenant_id == user.tenant_id)
            .order_by(OnboardingCase.start_date.desc())
            .offset(offset)
            .limit(100)
        )
    ).scalars()
    return [await read_case(db, case, private=True) for case in cases]


@router.post(
    "/onboarding",
    response_model=CaseRead,
    status_code=201,
    summary="Onboarding aus einem angenommenen Angebot starten",
)
async def start_case(data: CaseCreate, user: HR, db: DB) -> CaseRead:
    offer = await offer_access(db, data.offer_id, user, lock=True)
    if offer.status != "accepted":
        raise HTTPException(409, "Onboarding setzt ein angenommenes Angebot voraus.")
    application = await application_open(db, offer)
    await team_member(db, data.owner_id, user.tenant_id)
    existing = (
        await db.execute(select(OnboardingCase).where(OnboardingCase.offer_id == offer.id))
    ).scalar_one_or_none()
    if existing:
        return await read_case(db, existing, private=True)
    template = next(item for item in TEMPLATES if item.key == data.template)
    case = OnboardingCase(
        tenant_id=user.tenant_id,
        offer_id=offer.id,
        person_id=application.user_id,
        owner_id=data.owner_id,
        start_date=offer.start_date,
        template=data.template,
    )
    db.add(case)
    await db.flush()
    for position, step in enumerate(template.steps):
        db.add(
            OnboardingStep(
                case_id=case.id,
                title=step.title,
                audience=step.audience,
                assignee_id=data.owner_id if step.audience == "hr" else application.user_id,
                due_on=case.start_date + timedelta(days=step.days_from_start),
                position=position,
            )
        )
    await create_and_push(
        db=db,
        user_id=application.user_id,
        type_="onboarding.started",
        title="Dein Einstieg wird vorbereitet",
        body=offer.title,
        meta={"href": "/offers"},
    )
    await db.flush()
    return await read_case(db, case, private=True)


async def validate_step(db: AsyncSession, case: OnboardingCase, data: StepEdit) -> None:
    if data.audience == "hr" and data.assignee_id:
        await team_member(db, data.assignee_id, case.tenant_id)
    if data.audience == "person":
        data.assignee_id = case.person_id


@router.post(
    "/onboarding/{case_id}/steps",
    response_model=StepRead,
    status_code=201,
    summary="Onboarding-Aufgabe mit Zuständigkeit und Frist ergänzen",
)
async def add_step(case_id: uuid.UUID, data: StepEdit, user: HR, db: DB) -> OnboardingStep:
    case = await case_access(db, case_id, user, private=True, lock=True)
    await validate_step(db, case, data)
    count = (
        await db.scalar(
            select(func.count())
            .select_from(OnboardingStep)
            .where(OnboardingStep.case_id == case.id)
        )
        or 0
    )
    if count >= 100:
        raise HTTPException(422, "Ein Onboarding kann höchstens 100 Aufgaben enthalten.")
    step = OnboardingStep(case_id=case.id, position=count, **data.model_dump())
    db.add(step)
    await db.flush()
    return step


async def load_step(db: AsyncSession, case_id: uuid.UUID, step_id: uuid.UUID) -> OnboardingStep:
    step = (
        await db.execute(
            select(OnboardingStep)
            .where(OnboardingStep.id == step_id, OnboardingStep.case_id == case_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if step is None:
        raise HTTPException(404, "Aufgabe nicht gefunden.")
    return step


@router.patch(
    "/onboarding/{case_id}/steps/{step_id}",
    response_model=StepRead,
    status_code=200,
    summary="Zuständigkeit und Frist einer offenen Onboarding-Aufgabe ändern",
)
async def edit_step(
    case_id: uuid.UUID, step_id: uuid.UUID, data: StepEdit, user: HR, db: DB
) -> OnboardingStep:
    case = await case_access(db, case_id, user, private=True)
    step = await load_step(db, case.id, step_id)
    if step.completed_at:
        raise HTTPException(409, "Bitte die Aufgabe vor dem Bearbeiten wieder öffnen.")
    await validate_step(db, case, data)
    for key, value in data.model_dump().items():
        setattr(step, key, value)
    await db.flush()
    return step


@router.post(
    "/onboarding/{case_id}/steps/{step_id}/completion",
    response_model=StepRead,
    status_code=200,
    summary="Zugewiesene Onboarding-Aufgabe abschließen oder wieder öffnen",
)
async def complete_step(
    case_id: uuid.UUID, step_id: uuid.UUID, data: Completion, user: Current, db: DB
) -> OnboardingStep:
    private = user.role in {"admin", "recruiter"} and user.tenant_id is not None
    case = await case_access(db, case_id, user, private=private)
    step = await load_step(db, case.id, step_id)
    if not private and (step.audience != "person" or step.assignee_id != user.id):
        raise HTTPException(404, "Aufgabe nicht gefunden.")
    if private and user.id not in {step.assignee_id, case.owner_id} and user.role != "admin":
        raise HTTPException(403, "Nur zuständige Personen können diese Aufgabe abschließen.")
    step.completed_at = datetime.now(UTC) if data.completed else None
    step.completed_by = user.id if data.completed else None
    await db.flush()
    return step


@router.post(
    "/onboarding/{case_id}/activate",
    response_model=CaseRead,
    status_code=200,
    summary="Bestehende Person nach Prüfung für das Mitarbeiterportal aktivieren",
)
async def activate(case_id: uuid.UUID, data: Activation, user: HR, db: DB) -> CaseRead:
    case = await case_access(db, case_id, user, private=True, lock=True)
    if case.template == "agency":
        raise HTTPException(
            409, "Eine Vermittlung aktiviert keinen Mitarbeiterzugang beim Vermittler."
        )
    offer = await offer_access(db, case.offer_id, user)
    if offer.status != "accepted":
        raise HTTPException(409, "Bitte das zugrunde liegende Angebot prüfen.")
    await application_open(db, offer)
    if user.id != case.owner_id and user.role != "admin":
        raise HTTPException(
            403, "Nur die verantwortliche Person kann den Mitarbeiterzugang aktivieren."
        )
    person = (
        await db.execute(
            select(User)
            .where(User.id == case.person_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if (
        person.tenant_id not in {None, user.tenant_id}
        or person.role not in {"candidate", "worker"}
        or not person.is_active
    ):
        raise HTTPException(
            409, "Die Person kann diesem Mitarbeiterportal nicht zugeordnet werden."
        )
    settings = (
        await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == person.id))
    ).scalar_one_or_none()
    if settings:
        if settings.tenant_id != user.tenant_id or not settings.is_active:
            raise HTTPException(
                409, "Bitte den vorhandenen Mitarbeiterzugang in der Personalverwaltung prüfen."
            )
    else:
        db.add(
            WorkerSettings(
                user_id=person.id,
                tenant_id=user.tenant_id,
                is_active=True,
                employment_type=data.employment_type,
                active_modules=dict(ALL_MODULES),
                assigned_manager_id=case.owner_id,
                activated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
    if person.role != "worker" or person.tenant_id != user.tenant_id:
        person.role, person.tenant_id = "worker", user.tenant_id
        person.auth_version += 1
    case.activated_at = case.activated_at or datetime.now(UTC)
    await db.flush()
    return await read_case(db, case, private=True)
