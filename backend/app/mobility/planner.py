"""Maximum coverage, then minimum person travel minutes on supplied direct trips.

Successive shortest augmenting paths on a residual network. Reverse edges allow
reassigning a generalist so a scarce qualification is not lost to greedy ordering.
This optimizes the given options; it does not invent road routes or travel times.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Demand(StrictModel):
    key: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=120)
    headcount: int = Field(ge=1, le=100)
    required_skills: list[str] = Field(default_factory=list, max_length=30)


class Trip(StrictModel):
    key: str = Field(min_length=1, max_length=60)
    demand_key: str
    pickup: str = Field(min_length=1, max_length=100)
    vehicle: str = Field(min_length=1, max_length=80)
    seats: int = Field(ge=1, le=100)
    outbound_minutes: int = Field(ge=1, le=240)
    return_minutes: int = Field(ge=1, le=240)
    source: str = Field(min_length=3, max_length=200)


class WorkerOption(StrictModel):
    worker_id: UUID
    pickup: str = Field(min_length=1, max_length=100)
    available_from: datetime
    available_until: datetime
    max_commute_minutes: int = Field(ge=1, le=240)

    @model_validator(mode="after")
    def dates(self) -> Self:
        if (
            self.available_from.tzinfo is None
            or self.available_until.tzinfo is None
            or self.available_until <= self.available_from
        ):
            raise ValueError("Verfügbarkeit benötigt gültige Zeitpunkte mit Zeitzone.")
        return self


class PlanInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    time_zone: str = Field(default="Europe/Berlin", max_length=80)
    shift_start: datetime
    shift_end: datetime
    arrival_buffer_minutes: int = Field(default=15, ge=0, le=120)
    demands: list[Demand] = Field(min_length=1, max_length=20)
    trips: list[Trip] = Field(min_length=1, max_length=40)
    workers: list[WorkerOption] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unbekannte Zeitzone.") from exc
        if (
            self.shift_start.tzinfo is None
            or self.shift_end.tzinfo is None
            or not timedelta(0) < self.shift_end - self.shift_start <= timedelta(hours=12)
        ):
            raise ValueError("Schicht benötigt Zeitzonen und eine Dauer zwischen 0 und 12 Stunden.")
        for keys in (
            [d.key for d in self.demands],
            [t.key for t in self.trips],
            [t.vehicle.casefold() for t in self.trips],
            [str(w.worker_id) for w in self.workers],
        ):
            if len(keys) != len(set(keys)):
                raise ValueError(
                    "Bedarfe, Fahrten, Fahrzeuge und Mitarbeitende müssen eindeutig sein."
                )
        demand_keys = {d.key for d in self.demands}
        if any(t.demand_key not in demand_keys for t in self.trips):
            raise ValueError("Jede Fahrt benötigt einen vorhandenen Bedarf.")
        if any(not s.strip() or len(s) > 100 for d in self.demands for s in d.required_skills):
            raise ValueError("Fähigkeiten müssen 1 bis 100 Zeichen enthalten.")
        return self


class Allocation(BaseModel):
    worker_id: UUID
    worker_name: str
    demand_key: str
    trip_key: str
    departure: datetime
    return_arrival: datetime
    travel_minutes: int
    matched_skills: list[str]


class DemandResult(BaseModel):
    key: str
    title: str
    requested: int
    allocated: int
    unfilled: int


class Exclusion(BaseModel):
    worker_id: UUID
    reason: str


class PlanResult(BaseModel):
    allocations: list[Allocation]
    demands: list[DemandResult]
    unassigned: list[Exclusion]
    total_travel_minutes: int
    method: str = (
        "Maximale Besetzung, danach minimale Personen-Fahrtminuten für die eingegebenen Direktfahrten."
    )
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Planungsvorschlag: Es werden keine Einsätze gebucht oder Fahrten beauftragt.",
            "Fahrzeiten stammen aus den eingegebenen Quellen; Live-Verkehr, Mehrstopp-Routen und neue Routen werden nicht berechnet.",
            "Hinterlegte Fähigkeiten sind kein Qualifikationsnachweis. Zertifikate, Arbeitszeit, Ruhezeiten, Tarif- und Überlassungsgrenzen müssen vor Einsatzfreigabe geprüft werden.",
            "Sitzplätze verstehen sich ohne Fahrpersonal; Fahrerberechtigung, Fahrzeug und Rückfahrt müssen gesichert sein.",
        ]
    )


@dataclass
class Person:
    name: str
    skills: set[str]
    conflict: bool = False


@dataclass
class Edge:
    to: int
    reverse: int
    capacity: int
    cost: int


def optimise(data: PlanInput, people: dict[UUID, Person]) -> PlanResult:
    nworkers, ntrips, ndemands = len(data.workers), len(data.trips), len(data.demands)
    trip_offset = 1 + nworkers
    demand_offset = trip_offset + 2 * ntrips
    sink = demand_offset + ndemands
    graph: list[list[Edge]] = [[] for _ in range(sink + 1)]

    def add(left: int, right: int, capacity: int, cost: int = 0) -> Edge:
        edge = Edge(right, len(graph[right]), capacity, cost)
        graph[left].append(edge)
        graph[right].append(Edge(left, len(graph[left]) - 1, 0, -cost))
        return edge

    demand_index = {d.key: i for i, d in enumerate(data.demands)}
    for i, demand in enumerate(data.demands):
        add(demand_offset + i, sink, demand.headcount)
    for i, trip in enumerate(data.trips):
        add(trip_offset + 2 * i, trip_offset + 2 * i + 1, trip.seats)
        add(trip_offset + 2 * i + 1, demand_offset + demand_index[trip.demand_key], trip.seats)
    options: list[tuple[int, int, Edge]] = []
    reasons: dict[UUID, str] = {}
    for wi, worker in enumerate(data.workers):
        person = people[worker.worker_id]
        if person.conflict:
            reasons[worker.worker_id] = (
                "Vorhandener Einsatz oder offene/bestätigte Abwesenheit im Planungszeitraum."
            )
            continue
        add(0, wi + 1, 1)
        eligible = 0
        for ti, trip in enumerate(data.trips):
            demand = data.demands[demand_index[trip.demand_key]]
            departure = data.shift_start - timedelta(
                minutes=trip.outbound_minutes + data.arrival_buffer_minutes
            )
            returned = data.shift_end + timedelta(minutes=trip.return_minutes)
            if (
                worker.pickup.casefold() != trip.pickup.casefold()
                or not {s.strip().casefold() for s in demand.required_skills}.issubset(
                    person.skills
                )
                or max(trip.outbound_minutes, trip.return_minutes) > worker.max_commute_minutes
                or worker.available_from > departure
                or worker.available_until < returned
            ):
                continue
            eligible += 1
            options.append(
                (
                    wi,
                    ti,
                    add(
                        wi + 1, trip_offset + 2 * ti, 1, trip.outbound_minutes + trip.return_minutes
                    ),
                )
            )
        reasons[worker.worker_id] = (
            "Kein zulässiger Weg: Fähigkeiten, Treffpunkt, Verfügbarkeit einschließlich Fahrt oder Pendellimit prüfen."
            if not eligible
            else "Bedarf oder Sitzplätze durch andere zulässige Zuordnungen ausgeschöpft."
        )
    # Bellman-Ford accommodates negative reverse edges and avoids greedy mismatches.
    while True:
        dist = [10**9] * len(graph)
        prev: list[tuple[int, int] | None] = [None] * len(graph)
        dist[0] = 0
        for _ in range(len(graph) - 1):
            changed = False
            for node, edges in enumerate(graph):
                if dist[node] == 10**9:
                    continue
                for ei, edge in enumerate(edges):
                    if edge.capacity and dist[edge.to] > dist[node] + edge.cost:
                        dist[edge.to] = dist[node] + edge.cost
                        prev[edge.to] = (node, ei)
                        changed = True
            if not changed:
                break
        if prev[sink] is None:
            break
        node = sink
        while node != 0:
            predecessor = prev[node]
            assert predecessor is not None
            left, ei = predecessor
            edge = graph[left][ei]
            edge.capacity -= 1
            graph[node][edge.reverse].capacity += 1
            node = left
    allocations = []
    for wi, ti, edge in options:
        if edge.capacity != 0:
            continue
        worker, trip = data.workers[wi], data.trips[ti]
        demand = data.demands[demand_index[trip.demand_key]]
        allocations.append(
            Allocation(
                worker_id=worker.worker_id,
                worker_name=people[worker.worker_id].name,
                demand_key=demand.key,
                trip_key=trip.key,
                departure=data.shift_start
                - timedelta(minutes=trip.outbound_minutes + data.arrival_buffer_minutes),
                return_arrival=data.shift_end + timedelta(minutes=trip.return_minutes),
                travel_minutes=trip.outbound_minutes + trip.return_minutes,
                matched_skills=demand.required_skills,
            )
        )
    allocated_ids = {a.worker_id for a in allocations}
    counts = {d.key: sum(a.demand_key == d.key for a in allocations) for d in data.demands}
    return PlanResult(
        allocations=allocations,
        demands=[
            DemandResult(
                key=d.key,
                title=d.title,
                requested=d.headcount,
                allocated=counts[d.key],
                unfilled=d.headcount - counts[d.key],
            )
            for d in data.demands
        ],
        unassigned=[
            Exclusion(worker_id=w.worker_id, reason=reasons[w.worker_id])
            for w in data.workers
            if w.worker_id not in allocated_ids
        ],
        total_travel_minutes=sum(a.travel_minutes for a in allocations),
    )
