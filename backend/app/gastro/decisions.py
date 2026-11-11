"""Seating proposals: hard rules filter, transparent weights rank, a model may only tune weights.

The engine never books anything. It offers named options with visible reasons and
trade-offs; the caller accepts exactly one, and accepting re-checks every rule
against the current state. A prompt or a language model can move weights and
express preferences, but it cannot admit a resource the rules exclude, invent a
resource, or override an occupied window.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.models import (
    Decision,
    DecisionCriterion,
    DiningTable,
    Venue,
)
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import VersionInput

log = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(private_response)])

KIND = "reservation_table"
SHIFTS = (-60, -30, 30, 60)
MAX_PARTNERS = 8


class Weights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fit: float = Field(default=1.0, ge=0, le=3)
    keep_open: float = Field(default=1.0, ge=0, le=3)
    preference: float = Field(default=1.0, ge=0, le=3)


class ProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: datetime
    ends_at: datetime | None = None
    guests: int = Field(ge=1, le=100)
    kind: str = Field(default="table", max_length=20)
    prefer_area: str = Field(default="", max_length=80)
    prefer_tags: list[str] = Field(default_factory=list, max_length=6)
    prompt: str = Field(default="", max_length=1000)
    use_saved_criteria: bool = True
    weights: Weights = Field(default_factory=Weights)

    @model_validator(mode="after")
    def aware_interval(self) -> ProposalInput:
        if self.starts_at.tzinfo is None or (self.ends_at and self.ends_at.tzinfo is None):
            raise ValueError("Zeitangaben benötigen eine Zeitzone.")
        if self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("Das Ende muss nach dem Beginn liegen.")
        if self.ends_at and self.ends_at - self.starts_at > timedelta(hours=12):
            raise ValueError("Ein Zeitfenster von höchstens zwölf Stunden ist zulässig.")
        self.prefer_tags = [tag.strip().lower() for tag in self.prefer_tags if tag.strip()]
        return self


class Option(BaseModel):
    key: str
    title: str
    summary: str
    table_ids: list[uuid.UUID]
    table_names: list[str]
    seats: int
    starts_at: datetime
    ends_at: datetime
    score: float
    reasons: list[str]
    tradeoffs: list[str]


class ProposalRead(BaseModel):
    decision_id: uuid.UUID
    engine: str
    prompt_applied: bool
    prompt_note: str
    considered: int
    options: list[Option]
    notes: list[str]


class AcceptInput(VersionInput):
    model_config = ConfigDict(extra="forbid")
    option_key: str = Field(min_length=1, max_length=40)
    guest_name: str = Field(min_length=1, max_length=120)


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    prompt: str
    prompt_applied: bool
    engine: str
    chosen_key: str | None
    chosen_at: datetime | None
    created_at: datetime
    version: int


class CriterionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=1000)
    active: bool = True


class CriterionRead(CriterionInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    version: int


class Adjustment(BaseModel):
    """The only thing a language model is allowed to return."""

    model_config = ConfigDict(extra="forbid")
    fit: float = Field(ge=0, le=3)
    keep_open: float = Field(ge=0, le=3)
    preference: float = Field(ge=0, le=3)
    prefer_tags: list[str] = Field(default_factory=list, max_length=6)
    note: str = Field(default="", max_length=300)


async def free_tables(
    db: AsyncSession, venue_id: uuid.UUID, kind: str, start: datetime, end: datetime
) -> list[DiningTable]:
    """Resources of this kind without an overlapping reservation or open usage."""
    from app.gastro.booking_service import conflicting_resources

    rows = (
        (
            await db.execute(
                select(DiningTable)
                .where(DiningTable.venue_id == venue_id, DiningTable.kind == kind)
                .order_by(DiningTable.name)
            )
        )
        .scalars()
        .all()
    )
    booked = await conflicting_resources(
        db, [row.id for row in rows], start, end, live=start <= datetime.now(UTC) < end
    )
    return [row for row in rows if row.id not in booked]


async def all_tables(db: AsyncSession, venue_id: uuid.UUID) -> list[DiningTable]:
    return list(
        (await db.execute(select(DiningTable).where(DiningTable.venue_id == venue_id))).scalars()
    )


@dataclass(frozen=True)
class Candidate:
    tables: list[DiningTable]
    seats: int
    waste: int
    combo_loss: int
    match: int
    combined: bool


def build_candidates(
    free: list[DiningTable], guests: int, tags: list[str], area: str
) -> list[Candidate]:
    """Single resources first, then combinations for parties no single resource holds."""
    by_id = {str(row.id): row for row in free}
    result: list[Candidate] = []
    for row in free:
        if row.seats < guests or row.min_party > guests:
            continue
        partners = [
            by_id[str(other)] for other in row.combinable_with[:MAX_PARTNERS] if str(other) in by_id
        ]
        result.append(
            Candidate(
                tables=[row],
                seats=row.seats,
                waste=row.seats - guests,
                combo_loss=sum(partner.seats for partner in partners),
                match=match_score([row], tags, area),
                combined=False,
            )
        )
    if result:
        return result
    seen: set[tuple[str, ...]] = set()
    for row in free:
        partners = [
            by_id[str(other)] for other in row.combinable_with[:MAX_PARTNERS] if str(other) in by_id
        ]
        for partner in partners:
            if (
                row.kind != "table"
                or partner.kind != "table"
                or (row.room_id, row.area) != (partner.room_id, partner.area)
            ):
                continue
            key = tuple(sorted([str(row.id), str(partner.id)]))
            seats = row.seats + partner.seats
            if key in seen or seats < guests or max(row.min_party, partner.min_party) > guests:
                continue
            seen.add(key)
            result.append(
                Candidate(
                    tables=[row, partner],
                    seats=seats,
                    waste=seats - guests,
                    combo_loss=0,
                    match=match_score([row, partner], tags, area),
                    combined=True,
                )
            )
    return result


def match_score(tables: list[DiningTable], tags: list[str], area: str) -> int:
    present = {tag for row in tables for tag in row.tags}
    hits = len(present & set(tags))
    if area and all(row.area.lower() == area.lower() for row in tables):
        hits += 1
    return hits


def rank(
    candidates: list[Candidate],
    weights: Weights,
    hold: int,
    free_seats: int,
    start: datetime,
    end: datetime,
) -> list[Option]:
    """Three strategies, three distinct answers where the resources allow it."""
    strategies: tuple[tuple[str, str, str, Callable[[Candidate], float]], ...] = (
        (
            "best_fit",
            "Beste Passung",
            "Sucht die passgenaueste Ressource für diese Gruppengröße.",
            lambda c: weights.fit * (1.0 / (1 + c.waste)),
        ),
        (
            "keep_open",
            "Hält den Abend offen",
            "Hält kombinierbare Nachbarn für spätere größere Gruppen frei.",
            lambda c: weights.keep_open * (1.0 / (1 + c.waste + c.combo_loss)),
        ),
        (
            "preference",
            "Nächster Wunsch",
            "Folgt zuerst den gewünschten Merkmalen und dem Bereich.",
            lambda c: weights.preference * (c.match + 1.0 / (1 + c.waste)),
        ),
    )
    options: list[Option] = []
    used: set[tuple[str, ...]] = set()
    for key, title, purpose, score_of in strategies:
        pool = [c for c in candidates if tuple(sorted(str(t.id) for t in c.tables)) not in used]
        if not pool:
            break
        best = max(pool, key=lambda c: (score_of(c), -c.waste, c.tables[0].name))
        used.add(tuple(sorted(str(t.id) for t in best.tables)))
        options.append(
            describe(
                key, title, purpose, best, round(score_of(best), 3), hold, free_seats, start, end
            )
        )
    return options


def describe(
    key: str,
    title: str,
    purpose: str,
    candidate: Candidate,
    score: float,
    hold: int,
    free_seats: int,
    start: datetime,
    end: datetime,
) -> Option:
    names = [row.name for row in candidate.tables]
    reasons: list[str] = [purpose]
    tradeoffs: list[str] = []
    if candidate.combined:
        reasons.append(f"Zusammengestellt aus {' und '.join(names)} mit {candidate.seats} Plätzen.")
    if candidate.waste == 0:
        reasons.append("Kein Sitzplatz bleibt ungenutzt.")
    elif candidate.waste <= 2:
        reasons.append(f"{candidate.waste} Plätze bleiben frei.")
    else:
        tradeoffs.append(f"{candidate.waste} Plätze bleiben ungenutzt.")
    if candidate.combo_loss:
        tradeoffs.append(
            f"Blockiert die Kombination auf bis zu {candidate.seats + candidate.combo_loss} Plätze."
        )
    else:
        reasons.append("Kombinierbare Nachbartische bleiben für größere Gruppen frei.")
    if candidate.match:
        reasons.append(f"Erfüllt {candidate.match} der gewünschten Merkmale.")
    remaining = free_seats - candidate.seats
    if hold and remaining < hold:
        tradeoffs.append(
            f"Der Rückhalt für Laufkundschaft von {hold} Plätzen wird auf {max(remaining, 0)} gedrückt."
        )
    area = candidate.tables[0].area
    return Option(
        key=key,
        title=title,
        summary=f"{' + '.join(names)} · {candidate.seats} Plätze · {area}",
        table_ids=[row.id for row in candidate.tables],
        table_names=names,
        seats=candidate.seats,
        starts_at=start,
        ends_at=end,
        score=score,
        reasons=reasons,
        tradeoffs=tradeoffs,
    )


async def interpret(prompt: str, tags: list[str], weights: Weights) -> Adjustment | None:
    """Let a configured model translate free text into weights. Never into resources."""
    from app.ai.client import get_llm

    llm = await get_llm(temperature=0.0, max_tokens=300)
    if llm is None:
        return None
    instruction = (
        "Du gewichtest Kriterien für einen Tischvorschlag in einem Restaurant. "
        "Antworte ausschließlich mit JSON in der Form "
        '{"fit": Zahl 0-3, "keep_open": Zahl 0-3, "preference": Zahl 0-3, '
        '"prefer_tags": [Merkmale], "note": "kurze Begründung auf Deutsch"}. '
        f"Erlaubte Merkmale: {', '.join(sorted(tags)) or 'keine'}. "
        "fit bewertet passgenaue Sitzplatzzahl, keep_open das Freihalten kombinierbarer "
        "Tische für größere Gruppen, preference die gewünschten Merkmale. "
        f"Bisherige Gewichte: fit={weights.fit}, keep_open={weights.keep_open}, "
        f"preference={weights.preference}."
    )
    try:
        response = await llm.ainvoke(
            [{"role": "system", "content": instruction}, {"role": "user", "content": prompt}]
        )
        content = getattr(response, "content", "")
        payload = json.loads(content if isinstance(content, str) else str(content))
        adjustment = Adjustment.model_validate(payload)
    except Exception as exc:  # A model failure must never break the proposal.
        log.warning("Prompt-Auswertung nicht verwendbar: %s", type(exc).__name__)
        return None
    known = set(tags)
    adjustment.prefer_tags = [tag for tag in adjustment.prefer_tags if tag in known]
    return adjustment


@router.post(
    "/venues/{venue_id}/reservations/propose",
    response_model=ProposalRead,
    status_code=200,
    summary="Drei begründete Tischvorschläge für eine Reservierung",
)
async def propose(venue_id: uuid.UUID, data: ProposalInput, user: Actor, db: DB) -> ProposalRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    start = data.starts_at
    end = data.ends_at or start + timedelta(minutes=venue.default_stay_minutes)
    notes: list[str] = []
    if data.ends_at is None:
        notes.append(
            f"Ohne Endzeit wird die hinterlegte Verweildauer von {venue.default_stay_minutes} "
            "Minuten angenommen."
        )
    prompt = data.prompt.strip()
    if data.use_saved_criteria:
        saved = (
            (
                await db.execute(
                    select(DecisionCriterion).where(
                        DecisionCriterion.venue_id == venue_id,
                        DecisionCriterion.kind == KIND,
                        DecisionCriterion.active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if saved:
            prompt = " ".join([prompt, *[row.text for row in saved]]).strip()[:1000]
            notes.append(f"{len(saved)} gespeicherte Kriterien wurden ergänzt.")
    tag_rows = (
        (await db.execute(select(DiningTable.tags).where(DiningTable.venue_id == venue_id)))
        .scalars()
        .all()
    )
    known_tags = sorted({tag for row in tag_rows for tag in row})
    weights = data.weights
    prefer_tags = list(data.prefer_tags)
    adjustment = await interpret(prompt, known_tags, weights) if prompt else None
    prompt_note = ""
    if adjustment is not None:
        weights = Weights(
            fit=adjustment.fit, keep_open=adjustment.keep_open, preference=adjustment.preference
        )
        prefer_tags = sorted(set(prefer_tags) | set(adjustment.prefer_tags))
        prompt_note = adjustment.note
    elif prompt:
        prompt_note = (
            "Der freie Text wurde gespeichert, aber nicht angewendet: "
            "es ist kein Modellzugang eingerichtet. Die Vorschläge sind regelbasiert."
        )
    if not known_tags and not any(row.combinable_with for row in await all_tables(db, venue_id)):
        notes.append(
            "Merkmale und kombinierbare Tische sind noch nicht gepflegt. Die Vorschläge "
            "unterscheiden sich dadurch nur in der Ressource selbst."
        )
    free = await free_tables(db, venue_id, data.kind, start, end)
    candidates = build_candidates(free, data.guests, prefer_tags, data.prefer_area)
    free_seats = sum(row.seats for row in free)
    options = rank(candidates, weights, venue.walkin_hold_seats, free_seats, start, end)
    if not options:
        options = await shifted_options(db, venue, data, start, end, weights, prefer_tags)
        notes.append(
            "Im gewünschten Fenster passt keine Ressource; die Vorschläge verschieben die Zeit."
            if options
            else "Im gewünschten Fenster und in den geprüften Ausweichzeiten passt keine Ressource."
        )
    engine = "rules+model" if adjustment is not None else "rules"
    decision = Decision(
        venue_id=venue_id,
        actor_id=user.id,
        kind=KIND,
        request=data.model_dump(mode="json"),
        options=[option.model_dump(mode="json") for option in options],
        prompt=prompt,
        prompt_applied=adjustment is not None,
        engine=engine,
    )
    db.add(decision)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "decision.proposed",
        decision.id,
        {
            "kind": KIND,
            "engine": engine,
            "prompt_applied": adjustment is not None,
            "options": [option.key for option in options],
        },
        user.id,
    )
    return ProposalRead(
        decision_id=decision.id,
        engine=engine,
        prompt_applied=adjustment is not None,
        prompt_note=prompt_note,
        considered=len(candidates),
        options=options,
        notes=notes,
    )


async def shifted_options(
    db: AsyncSession,
    venue: Venue,
    data: ProposalInput,
    start: datetime,
    end: datetime,
    weights: Weights,
    prefer_tags: list[str],
) -> list[Option]:
    """Nothing fits: offer neighbouring windows instead of a bare rejection."""
    options: list[Option] = []
    for offset in SHIFTS:
        moved_start = start + timedelta(minutes=offset)
        moved_end = end + timedelta(minutes=offset)
        if moved_start < datetime.now(UTC):
            continue
        free = await free_tables(db, venue.id, data.kind, moved_start, moved_end)
        candidates = build_candidates(free, data.guests, prefer_tags, data.prefer_area)
        ranked = rank(
            candidates,
            weights,
            venue.walkin_hold_seats,
            sum(row.seats for row in free),
            moved_start,
            moved_end,
        )
        if not ranked:
            continue
        option = ranked[0]
        option.key = f"shift_{offset:+d}"
        option.title = f"{abs(offset)} Minuten {'früher' if offset < 0 else 'später'}"
        option.reasons.insert(0, "Im ursprünglich gewünschten Fenster war nichts frei.")
        options.append(option)
        if len(options) == 3:
            break
    return options


@router.post(
    "/venues/{venue_id}/decisions/{decision_id}/accept",
    response_model=list[uuid.UUID],
    status_code=201,
    summary="Einen Vorschlag annehmen und dabei alle Regeln erneut prüfen",
)
async def accept(
    venue_id: uuid.UUID, decision_id: uuid.UUID, data: AcceptInput, user: Actor, db: DB
) -> list[uuid.UUID]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    from app.gastro.booking_models import ReservationCommand
    from app.gastro.bookings import fingerprint, prior_command

    key = uuid.uuid5(decision_id, "reservation.accept")
    digest = fingerprint("proposal.accept", data, decision_id)
    prior = await prior_command(db, venue_id, key, digest)
    if prior is not None:
        ids = prior["reservation_ids"]
        assert isinstance(ids, list)
        return [uuid.UUID(str(value)) for value in ids]
    decision = (
        await db.execute(
            select(Decision)
            .where(Decision.id == decision_id, Decision.venue_id == venue_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(404, "Vorschlag nicht gefunden.")
    svc.check_version(decision.version, data.version)
    if decision.chosen_key:
        raise HTTPException(409, "Dieser Vorschlag wurde bereits angenommen.")
    chosen = next(
        (row for row in decision.options if row.get("key") == data.option_key),
        None,
    )
    if chosen is None:
        raise HTTPException(404, "Diese Option gehört nicht zu dem Vorschlag.")
    option = Option.model_validate(chosen)
    from app.gastro.booking_service import create_group

    requested = decision.request.get("guests", 1)
    guests = requested if isinstance(requested, int) else 1
    reservation = await create_group(
        db,
        venue_id,
        option.table_ids,
        data.guest_name,
        guests,
        option.starts_at,
        option.ends_at,
        user.id,
        source="proposal",
    )
    created = [reservation.id]
    db.add(
        ReservationCommand(
            venue_id=venue_id,
            request_key=key,
            request_hash=digest,
            kind="proposal.accept",
            result={"reservation_ids": [str(reservation.id)]},
            actor_id=user.id,
        )
    )
    decision.chosen_key = option.key
    decision.chosen_at = datetime.now(UTC)
    decision.version += 1
    svc.event(
        db,
        venue_id,
        "decision.accepted",
        decision.id,
        {
            "option": option.key,
            "tables": [str(value) for value in option.table_ids],
            "reservations": [str(value) for value in created],
        },
        user.id,
    )
    return created


@router.get(
    "/venues/{venue_id}/decisions",
    response_model=list[DecisionRead],
    status_code=200,
    summary="Bisherige Vorschläge und getroffene Auswahl",
)
async def history(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Decision]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return list(
        (
            await db.execute(
                select(Decision)
                .where(Decision.venue_id == venue_id)
                .order_by(Decision.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )


@router.get(
    "/venues/{venue_id}/decision-criteria",
    response_model=list[CriterionRead],
    status_code=200,
    summary="Gespeicherte zusätzliche Kriterien",
)
async def criteria(venue_id: uuid.UUID, user: Actor, db: DB) -> list[DecisionCriterion]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return list(
        (
            await db.execute(
                select(DecisionCriterion)
                .where(DecisionCriterion.venue_id == venue_id)
                .order_by(DecisionCriterion.label)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/decision-criteria",
    response_model=CriterionRead,
    status_code=201,
    summary="Ein wiederverwendbares Kriterium hinterlegen",
)
async def add_criterion(
    venue_id: uuid.UUID, data: CriterionInput, user: Actor, db: DB
) -> DecisionCriterion:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    existing = (
        await db.execute(
            select(DecisionCriterion).where(
                DecisionCriterion.venue_id == venue_id,
                DecisionCriterion.kind == KIND,
                DecisionCriterion.label == data.label,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "Ein Kriterium mit dieser Bezeichnung existiert bereits.")
    row = DecisionCriterion(venue_id=venue_id, kind=KIND, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "decision.criterion_added", row.id, {"label": row.label}, user.id)
    return row


@router.delete(
    "/venues/{venue_id}/decision-criteria/{criterion_id}",
    status_code=204,
    summary="Ein Kriterium entfernen",
)
async def remove_criterion(
    venue_id: uuid.UUID, criterion_id: uuid.UUID, user: Actor, db: DB
) -> None:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    row = (
        await db.execute(
            select(DecisionCriterion).where(
                DecisionCriterion.id == criterion_id, DecisionCriterion.venue_id == venue_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Kriterium nicht gefunden.")
    await db.delete(row)
    svc.event(
        db, venue_id, "decision.criterion_removed", criterion_id, {"label": row.label}, user.id
    )
