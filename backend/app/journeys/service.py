"""Permission checks and reusable onboarding process definitions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.applications.models import Application, ApplicationStatus
from app.companies.models import Company
from app.journeys.models import HiringOffer, OfferEvent, OnboardingCase, OnboardingStep
from app.journeys.schemas import (
    CaseRead,
    EventRead,
    OfferPrivate,
    OfferRead,
    StepRead,
    TemplateRead,
    TemplateStep,
)
from app.pipeline.access import require_application
from app.users.models import User

TEMPLATES = [
    TemplateRead(
        key="internal_hr",
        title="Eintritt ins Unternehmen",
        steps=[
            TemplateStep(
                title="Vertragsunterlagen final prüfen", audience="hr", days_from_start=-7
            ),
            TemplateStep(
                title="Arbeitsplatz und Zugänge vorbereiten", audience="hr", days_from_start=-3
            ),
            TemplateStep(
                title="Kontakt- und Stammdaten abstimmen", audience="person", days_from_start=-3
            ),
            TemplateStep(title="Willkommensgespräch durchführen", audience="hr", days_from_start=0),
            TemplateStep(
                title="Einarbeitungsplan besprechen", audience="person", days_from_start=7
            ),
        ],
    ),
    TemplateRead(
        key="agency",
        title="Vermittlung begleiten",
        steps=[
            TemplateStep(
                title="Angebot mit dem Kunden abstimmen", audience="hr", days_from_start=-7
            ),
            TemplateStep(
                title="Eintritt und Ansprechperson bestätigen",
                audience="person",
                days_from_start=-3,
            ),
            TemplateStep(
                title="Vermittlungsunterlagen abschließen", audience="hr", days_from_start=0
            ),
            TemplateStep(
                title="Feedback nach dem Einstieg einholen", audience="hr", days_from_start=7
            ),
        ],
    ),
    TemplateRead(
        key="staffing",
        title="Einsatz vorbereiten",
        steps=[
            TemplateStep(
                title="Vertrag und Einsatzvoraussetzungen prüfen", audience="hr", days_from_start=-7
            ),
            TemplateStep(
                title="Qualifikationen und Nachweise prüfen", audience="hr", days_from_start=-3
            ),
            TemplateStep(
                title="Einsatzort und Anreise abstimmen", audience="person", days_from_start=-2
            ),
            TemplateStep(
                title="Ausrüstung und Sicherheitsunterweisung organisieren",
                audience="hr",
                days_from_start=-1,
            ),
            TemplateStep(
                title="Kontakt für den ersten Einsatztag bestätigen",
                audience="person",
                days_from_start=0,
            ),
        ],
    ),
]


async def can_self_approve(db: AsyncSession, user: User) -> bool:
    if user.role != "admin" or user.company_id is None or user.tenant_id is None:
        return False
    return bool(
        await db.scalar(
            select(Company.id)
            .join(Customer, Customer.id == user.tenant_id)
            .where(
                Company.id == user.company_id,
                Company.created_by == user.id,
                Customer.type == "solo_recruiter",
            )
        )
    )


async def team_member(
    db: AsyncSession, user_id: uuid.UUID | None, tenant_id: uuid.UUID | None, *, admin: bool = False
) -> User:
    member = await db.get(User, user_id) if user_id else None
    if (
        member is None
        or not member.is_active
        or member.tenant_id != tenant_id
        or member.role not in ({"admin"} if admin else {"admin", "recruiter"})
    ):
        raise HTTPException(
            422, "Bitte eine aktive, berechtigte Person aus diesem Arbeitsbereich wählen."
        )
    return member


async def offer_access(
    db: AsyncSession, offer_id: uuid.UUID, user: User, *, private: bool = True, lock: bool = False
) -> HiringOffer:
    stmt = select(HiringOffer).where(HiringOffer.id == offer_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    offer = (await db.execute(stmt)).scalar_one_or_none()
    if offer is None:
        raise HTTPException(404, "Angebot nicht gefunden.")
    if private:
        if offer.tenant_id != user.tenant_id:
            raise HTTPException(404, "Angebot nicht gefunden.")
        await require_application(db, offer.application_id, user)
    else:
        application = await db.get(Application, offer.application_id)
        if application is None or application.user_id != user.id or offer.shared_at is None:
            raise HTTPException(404, "Angebot nicht gefunden.")
    return offer


def check_version(offer: HiringOffer, version: int) -> None:
    if offer.version != version:
        raise HTTPException(
            409, "Das Angebot wurde zwischenzeitlich geändert. Bitte neu laden und prüfen."
        )


def offer_open(offer: HiringOffer) -> None:
    if offer.expires_on < datetime.now(UTC).date():
        raise HTTPException(409, "Dieses Angebot ist abgelaufen.")


async def application_open(db: AsyncSession, offer: HiringOffer) -> Application:
    application = await db.get(Application, offer.application_id)
    if application is not None:
        await db.refresh(application, with_for_update=True)
    if application is None or application.status in {
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }:
        raise HTTPException(409, "Dieser Bewerbungsprozess ist abgeschlossen.")
    return application


def record(db: AsyncSession, offer: HiringOffer, actor: User, note: str | None = None) -> None:
    db.add(
        OfferEvent(
            offer_id=offer.id,
            actor_id=actor.id,
            status=offer.status,
            version=offer.version,
            note=note,
            title=offer.title,
            terms=offer.terms,
            start_date=offer.start_date,
            expires_on=offer.expires_on,
        )
    )


async def private_offer(db: AsyncSession, offer: HiringOffer) -> OfferPrivate:
    application = await db.get(Application, offer.application_id)
    person = await db.get(User, application.user_id) if application else None
    events = (
        await db.execute(
            select(OfferEvent)
            .where(OfferEvent.offer_id == offer.id)
            .order_by(OfferEvent.created_at, OfferEvent.version)
        )
    ).scalars()
    if person is None:
        raise HTTPException(404, "Person nicht gefunden.")
    return OfferPrivate(
        **OfferRead.model_validate(offer).model_dump(),
        person_id=person.id,
        person_name=person.full_name or person.email,
        created_by=offer.created_by,
        approver_id=offer.approver_id,
        events=[EventRead.model_validate(event) for event in events],
    )


async def case_access(
    db: AsyncSession, case_id: uuid.UUID, user: User, *, private: bool, lock: bool = False
) -> OnboardingCase:
    stmt = select(OnboardingCase).where(OnboardingCase.id == case_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    case = (await db.execute(stmt)).scalar_one_or_none()
    if case is None or (case.tenant_id != user.tenant_id if private else case.person_id != user.id):
        raise HTTPException(404, "Onboarding nicht gefunden.")
    return case


async def read_case(db: AsyncSession, case: OnboardingCase, *, private: bool) -> CaseRead:
    query = select(OnboardingStep).where(OnboardingStep.case_id == case.id)
    if not private:
        query = query.where(OnboardingStep.audience == "person")
    steps = list(
        (
            await db.execute(query.order_by(OnboardingStep.position, OnboardingStep.created_at))
        ).scalars()
    )
    person = await db.get(User, case.person_id)
    offer = await db.get(HiringOffer, case.offer_id)
    return CaseRead(
        id=case.id,
        offer_id=case.offer_id,
        person_id=case.person_id,
        person_name=person.full_name or person.email if person else "Person",
        title=offer.title if offer else "Onboarding",
        owner_id=case.owner_id,
        start_date=case.start_date,
        template=case.template,
        activated_at=case.activated_at,
        completed=sum(step.completed_at is not None for step in steps),
        total=len(steps),
        steps=[StepRead.model_validate(step) for step in steps],
    )
