"""Versioned hygiene plans, due controls and bounded evidence exports."""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro import recipes
from app.gastro import service as svc
from app.gastro.inventory_models import InventoryBase
from app.gastro.models import Membership
from app.gastro.recipes import HaccpInput, HaccpRead, HaccpRecord
from app.gastro.router import DB, Actor, private_response
from app.users.models import User
from app.utils.csv import literal_cell

router = APIRouter(dependencies=[Depends(private_response)])


class HygienePlanVersion(InventoryBase):
    __tablename__ = "fp_hygiene_plan_versions"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_hygiene_plan_scope"),
        UniqueConstraint("venue_id", "plan_id", "version", name="uq_fp_hygiene_plan_version"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_hygiene_plan_request"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class HygienePlanCheck(InventoryBase):
    __tablename__ = "fp_hygiene_plan_checks"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_hygiene_check_request"),
        UniqueConstraint("record_id", name="uq_fp_hygiene_check_record"),
        ForeignKeyConstraint(
            ["venue_id", "plan_version_id"],
            ["fp_hygiene_plan_versions.venue_id", "fp_hygiene_plan_versions.id"],
            name="fk_fp_hygiene_check_plan",
        ),
        ForeignKeyConstraint(
            ["venue_id", "record_id"],
            ["fp_haccp_records.venue_id", "fp_haccp_records.id"],
            name="fk_fp_hygiene_check_record",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    plan_version_id: Mapped[uuid.UUID] = mapped_column()
    record_id: Mapped[uuid.UUID] = mapped_column()
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))


class PlanSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    location: str = Field(min_length=2, max_length=120)
    instructions: str = Field(min_length=5, max_length=1000)
    minimum: Decimal = Field(ge=-100000, le=100000, decimal_places=3)
    maximum: Decimal = Field(ge=-100000, le=100000, decimal_places=3)
    unit: str = Field(min_length=1, max_length=20)
    interval_minutes: int = Field(ge=15, le=44640)
    responsible_user_id: uuid.UUID
    active: bool = True

    @model_validator(mode="after")
    def limits(self) -> PlanSettings:
        if self.minimum > self.maximum:
            raise ValueError("Untergrenze muss unter der Obergrenze liegen.")
        return self


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    plan_id: uuid.UUID | None = None
    expected_version: int = Field(default=0, ge=0)
    data: PlanSettings


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    plan_id: uuid.UUID
    version: int
    data: PlanSettings
    created_at: datetime
    actor_id: uuid.UUID


class PlanDue(PlanRead):
    last_record: HaccpRead | None
    due_at: datetime
    overdue: bool
    unresolved_deviation_ids: list[uuid.UUID]
    unresolved_deviations: list[HaccpRead]


class CheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    version: int = Field(ge=1)
    value: Decimal = Field(ge=-100000, le=100000, decimal_places=3)
    correction: str = Field(default="", max_length=500)
    corrects_id: uuid.UUID | None = None


async def latest_plan(db: DB, venue_id: uuid.UUID, plan_id: uuid.UUID) -> HygienePlanVersion:
    row = (
        await db.execute(
            select(HygienePlanVersion)
            .where(HygienePlanVersion.venue_id == venue_id, HygienePlanVersion.plan_id == plan_id)
            .order_by(HygienePlanVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Kontrollplan nicht gefunden.")
    return row


@router.post(
    "/venues/{venue_id}/hygiene/plans",
    response_model=PlanRead,
    status_code=201,
    summary="Betrieblichen Kontrollplan mit Verantwortung versionieren",
)
async def save_plan(
    venue_id: uuid.UUID, data: PlanInput, user: Actor, db: DB
) -> HygienePlanVersion:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    prior = (
        await db.execute(
            select(HygienePlanVersion).where(
                HygienePlanVersion.venue_id == venue_id,
                HygienePlanVersion.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != svc.digest(data):
            raise HTTPException(409, "Diese Plan-ID wurde anders verwendet.")
        return prior
    version = 0
    if data.plan_id:
        version = (await latest_plan(db, venue_id, data.plan_id)).version
    svc.check_version(version, data.expected_version)
    if not (
        await db.execute(
            select(Membership.id).where(
                Membership.venue_id == venue_id,
                Membership.user_id == data.data.responsible_user_id,
                Membership.active.is_(True),
                Membership.role.in_(svc.KITCHEN),
            )
        )
    ).first():
        raise HTTPException(
            422, "Verantwortung benötigt ein aktives Küchen- oder Leitungsmitglied."
        )
    row = HygienePlanVersion(
        venue_id=venue_id,
        plan_id=data.plan_id or uuid.uuid4(),
        version=version + 1,
        request_key=data.request_key,
        request_hash=svc.digest(data),
        data=data.data.model_dump(mode="json"),
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "hygiene.plan_versioned",
        row.plan_id,
        {"version": row.version, "plan_version_id": str(row.id)},
        user.id,
    )
    return row


async def linked_records(db: DB, venue_id: uuid.UUID, plan_id: uuid.UUID) -> list[HaccpRecord]:
    return list(
        (
            await db.execute(
                select(HaccpRecord)
                .join(HygienePlanCheck, HygienePlanCheck.record_id == HaccpRecord.id)
                .join(HygienePlanVersion, HygienePlanVersion.id == HygienePlanCheck.plan_version_id)
                .where(
                    HaccpRecord.venue_id == venue_id,
                    HygienePlanVersion.venue_id == venue_id,
                    HygienePlanVersion.plan_id == plan_id,
                )
                .order_by(HaccpRecord.measured_at.desc(), HaccpRecord.id)
            )
        ).scalars()
    )


@router.get(
    "/venues/{venue_id}/hygiene/plans",
    response_model=list[PlanDue],
    status_code=200,
    summary="Fällige Kontrollen und ungeklärte Abweichungen anzeigen",
)
async def plans(venue_id: uuid.UUID, user: Actor, db: DB) -> list[PlanDue]:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    versions = (
        await db.execute(
            select(HygienePlanVersion)
            .where(HygienePlanVersion.venue_id == venue_id)
            .order_by(HygienePlanVersion.version.desc())
        )
    ).scalars()
    latest: dict[uuid.UUID, HygienePlanVersion] = {}
    for row in versions:
        latest.setdefault(row.plan_id, row)
    now = datetime.now(UTC)
    result: list[PlanDue] = []
    for row in latest.values():
        plan = PlanRead.model_validate(row)
        records = await linked_records(db, venue_id, row.plan_id)
        # A new version needs a fresh check against its new concept/limits.
        current_ids = set(
            (
                await db.execute(
                    select(HygienePlanCheck.record_id).where(
                        HygienePlanCheck.venue_id == venue_id,
                        HygienePlanCheck.plan_version_id == row.id,
                    )
                )
            ).scalars()
        )
        current = [record for record in records if record.id in current_ids]
        last = current[0] if current else None
        due = (
            last.measured_at + timedelta(minutes=plan.data.interval_minutes)
            if last
            else row.created_at
        )
        corrected = {record.corrects_id for record in records if record.result == "ok"}
        result.append(
            PlanDue(
                **plan.model_dump(),
                last_record=HaccpRead.model_validate(last) if last else None,
                due_at=due,
                overdue=plan.data.active and due <= now,
                unresolved_deviation_ids=[
                    record.id
                    for record in records
                    if record.result == "deviation" and record.id not in corrected
                ],
                unresolved_deviations=[
                    HaccpRead.model_validate(record)
                    for record in records
                    if record.result == "deviation" and record.id not in corrected
                ],
            )
        )
    return sorted(result, key=lambda row: (not row.overdue, row.due_at, row.data.name))


@router.post(
    "/venues/{venue_id}/hygiene/plans/{plan_id}/checks",
    response_model=HaccpRead,
    status_code=201,
    summary="Planbezogene Kontrolle ohne veränderbare Grenzwerte protokollieren",
)
async def check_plan(
    venue_id: uuid.UUID, plan_id: uuid.UUID, data: CheckInput, user: Actor, db: DB
) -> HaccpRecord:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    fingerprint = svc.digest(data) + str(plan_id)
    prior = (
        await db.execute(
            select(HygienePlanCheck).where(
                HygienePlanCheck.venue_id == venue_id,
                HygienePlanCheck.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != hashlib.sha256(fingerprint.encode()).hexdigest():
            raise HTTPException(409, "Diese Kontroll-ID wurde anders verwendet.")
        return (
            await db.execute(
                select(HaccpRecord).where(
                    HaccpRecord.id == prior.record_id, HaccpRecord.venue_id == venue_id
                )
            )
        ).scalar_one()
    row = await latest_plan(db, venue_id, plan_id)
    svc.check_version(row.version, data.version)
    settings = PlanSettings.model_validate(row.data)
    if not settings.active:
        raise HTTPException(409, "Dieser Kontrollplan ist pausiert.")
    if data.corrects_id and data.corrects_id not in {
        record.id for record in await linked_records(db, venue_id, plan_id)
    }:
        raise HTTPException(422, "Nachkontrolle muss zur gleichen Kontrollaufgabe gehören.")
    if (
        await db.execute(
            select(HaccpRecord.id).where(
                HaccpRecord.venue_id == venue_id, HaccpRecord.request_key == data.request_key
            )
        )
    ).first():
        raise HTTPException(409, "Diese Kontroll-ID gehört bereits zu einer anderen Kontrolle.")
    if not settings.minimum <= data.value <= settings.maximum and len(data.correction.strip()) < 5:
        raise HTTPException(
            422, "Bei Grenzwertverletzung ist eine konkrete Sofortmaßnahme erforderlich."
        )
    record_data = HaccpInput(
        request_key=data.request_key,
        name=settings.name,
        location=settings.location,
        value=data.value,
        minimum=settings.minimum,
        maximum=settings.maximum,
        unit=settings.unit,
        correction=data.correction,
        corrects_id=data.corrects_id,
    )
    record = await recipes.record_haccp(venue_id, record_data, user, db)
    db.add(
        HygienePlanCheck(
            venue_id=venue_id,
            plan_version_id=row.id,
            record_id=record.id,
            request_key=data.request_key,
            request_hash=hashlib.sha256(fingerprint.encode()).hexdigest(),
        )
    )
    await db.flush()
    return record


class EvidenceExport(BaseModel):
    venue_id: uuid.UUID
    generated_at: datetime
    start: datetime
    end: datetime
    records: list[HaccpRead]
    plan_versions: list[PlanRead]
    record_plan_versions: dict[str, str]


@router.get(
    "/venues/{venue_id}/hygiene/export",
    response_model=EvidenceExport,
    status_code=200,
    summary="Kontrollnachweise mit Verantwortlichen und exakten Planversionen exportieren",
)
async def export(
    venue_id: uuid.UUID, start: AwareDatetime, end: AwareDatetime, user: Actor, db: DB
) -> EvidenceExport:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    if not timedelta(0) < end - start <= timedelta(days=93):
        raise HTTPException(
            422, "Exportzeitraum muss positiv sein und darf höchstens 93 Tage umfassen."
        )
    records = list(
        (
            await db.execute(
                select(HaccpRecord)
                .where(
                    HaccpRecord.venue_id == venue_id,
                    HaccpRecord.measured_at >= start,
                    HaccpRecord.measured_at < end,
                )
                .order_by(HaccpRecord.measured_at, HaccpRecord.id)
                .limit(10001)
            )
        ).scalars()
    )
    if len(records) > 10000:
        raise HTTPException(
            422, "Mehr als 10.000 Kontrollen: Zeitraum verkleinern; Export wurde nicht gekürzt."
        )
    links = list(
        (
            await db.execute(
                select(HygienePlanCheck).where(
                    HygienePlanCheck.venue_id == venue_id,
                    HygienePlanCheck.record_id.in_([record.id for record in records]),
                )
            )
        ).scalars()
    )
    versions = list(
        (
            await db.execute(
                select(HygienePlanVersion).where(
                    HygienePlanVersion.venue_id == venue_id,
                    HygienePlanVersion.id.in_([link.plan_version_id for link in links]),
                )
            )
        ).scalars()
    )
    return EvidenceExport(
        venue_id=venue_id,
        generated_at=datetime.now(UTC),
        start=start,
        end=end,
        records=[HaccpRead.model_validate(record) for record in records],
        plan_versions=[PlanRead.model_validate(version) for version in versions],
        record_plan_versions={str(link.record_id): str(link.plan_version_id) for link in links},
    )


@router.get(
    "/venues/{venue_id}/hygiene/export.csv",
    response_model=None,
    status_code=200,
    summary="Lesbare Kontrollnachweise für Tabellenkalkulation und Prüfung exportieren",
)
async def export_csv(
    venue_id: uuid.UUID, start: AwareDatetime, end: AwareDatetime, user: Actor, db: DB
) -> Response:
    evidence = await export(venue_id, start, end, user, db)
    user_ids = {record.actor_id for record in evidence.records} | {
        plan.data.responsible_user_id for plan in evidence.plan_versions
    }
    names = {
        user_id: name
        for user_id, name in (
            await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
        ).all()
    }
    versions = {str(plan.id): plan for plan in evidence.plan_versions}
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Nachweis-ID",
            "Zeitpunkt (UTC)",
            "Kontrollaufgabe",
            "Ort",
            "Messwert",
            "Einheit",
            "Untergrenze",
            "Obergrenze",
            "Ergebnis",
            "Sofortmaßnahme",
            "Durchgeführt von",
            "Verantwortlich",
            "Planversion",
            "Nachkontrolle zu",
        ]
    )
    for record in evidence.records:
        plan = versions.get(evidence.record_plan_versions.get(str(record.id), ""))
        writer.writerow(
            [
                str(record.id),
                record.measured_at.astimezone(UTC).isoformat(),
                literal_cell(record.name),
                literal_cell(record.location),
                str(record.value).replace(".", ","),
                literal_cell(record.unit),
                str(record.minimum).replace(".", ","),
                str(record.maximum).replace(".", ","),
                "Im Soll" if record.result == "ok" else "Abweichung",
                literal_cell(record.correction),
                literal_cell(names.get(record.actor_id) or str(record.actor_id)),
                literal_cell(
                    (names.get(plan.data.responsible_user_id) or str(plan.data.responsible_user_id))
                    if plan
                    else "Manuelle Kontrolle"
                ),
                plan.version if plan else "",
                str(record.corrects_id) if record.corrects_id else "",
            ]
        )
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="flintplate-kontrollen-{start.date()}.csv"',
            "Cache-Control": "no-store",
        },
    )
