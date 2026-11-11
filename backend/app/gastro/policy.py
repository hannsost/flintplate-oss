"""Conservative planning checks, separate from payroll/tax entitlements.

These are guardrails for known data, not a declaration of full legal compliance.
Exceptions, school schedules and reference-period compensation need their own evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta


@dataclass
class Assessment:
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def assess_interval(
    start: datetime,
    end: datetime,
    break_minutes: int,
    birth_date: date | None,
    adjacent: list[tuple[datetime, datetime]],
    weekly_minutes: int = 0,
    weekly_target: int | None = None,
) -> Assessment:
    result = Assessment()
    age = (
        None
        if birth_date is None
        else start.year
        - birth_date.year
        - ((start.month, start.day) < (birth_date.month, birth_date.day))
    )
    minor = age is not None and age < 18
    net = (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 60 - break_minutes
    if age is None:
        result.warnings.append(
            "Geburtsdatum fehlt; Jugendschutz konnte nicht vollständig geprüft werden."
        )
    if age is not None and age < 15:
        result.blockers.append(
            "Beschäftigung unter 15 Jahren benötigt einen gesondert geprüften Rahmen."
        )
    if net <= 0:
        result.blockers.append("Arbeitszeit muss positiv sein.")
    max_minutes = 480 if minor else 600
    if net > max_minutes:
        result.blockers.append("Die konservative Tageshöchstgrenze wird überschritten.")
    pause = (
        60
        if minor and net > 360
        else (
            30
            if minor and net > 270
            else 45 if not minor and net > 540 else 30 if not minor and net > 360 else 0
        )
    )
    if break_minutes < pause:
        result.blockers.append(f"Mindestens {pause} Minuten Pause sind einzuplanen.")
    if minor:
        # Until school-day/exception evidence exists, keep the standard 06–20 window.
        if (
            start.hour < 6
            or end.date() != start.date()
            or end.hour > 20
            or (end.hour == 20 and (end.minute or end.second))
        ):
            result.blockers.append(
                "Jugendliche: aktuell nur Planung zwischen 06 und 20 Uhr; Ausnahmen sind nicht freigegeben."
            )
        if weekly_minutes + net > 2400:
            result.blockers.append("Jugendliche: Wochenplanung überschreitet 40 Stunden.")
    elif net > 480:
        result.warnings.append("Mehr als acht Stunden: zulässigen Ausgleichszeitraum prüfen.")
    rest = timedelta(hours=12 if minor else 11)
    for before, after in adjacent:
        if before < end and after > start:
            result.blockers.append("Bereits eine zeitlich überlappende Schicht vorhanden.")
            break
        if (after <= start and start - after < rest) or (before >= end and before - end < rest):
            result.blockers.append(
                f"Der Ruheabstand von {int(rest.total_seconds()/3600)} Stunden wird unterschritten."
            )
            break
    if weekly_target is not None and weekly_minutes + net > weekly_target:
        result.warnings.append(
            "Die Wochen-Sollzeit wird überschritten; Mehrarbeit und Zustimmung prüfen."
        )
    result.warnings.append(
        "Pausenlage, Berufsschule, weitere Arbeitgeber und gesetzliche Ausgleichszeiträume zusätzlich prüfen."
    )
    return result
