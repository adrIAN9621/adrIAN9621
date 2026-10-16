"""Modelele de date comune și interfețele către sistemele externe.

Fiecare sistem (Mersul Trenurilor, InfoRU, Comandă personal / SIT / RCC) e un
modul separat cu aceeași interfață; aplicația nu știe dacă datele vin din
simulator sau din sistemele reale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class StopTime:
    station: str                  # cod stație (vezi geo.STATIONS)
    arr: Optional[float]          # sosire planificată (epoch, sec); None la stația de plecare
    dep: Optional[float]          # plecare planificată; None la stația finală


@dataclass
class Timetable:
    train: str                    # numărul trenului
    kind: str                     # marfă / călători / izolată
    stops: list[StopTime]

    @property
    def route(self) -> list[str]:
        return [s.station for s in self.stops]

    def index(self, station: str) -> int:
        return self.route.index(station)


@dataclass
class LivePosition:
    train: str
    lat: float
    lon: float
    delay_min: float                       # întârzierea curentă raportată
    status: str                            # "neplecat" | "in_mers" | "in_statie" | "sosit"
    last_index: int                        # indexul ultimei stații atinse (-1 dacă n-a plecat)
    passed: dict[str, float] = field(default_factory=dict)  # stație -> ora reală a sosirii/trecerii
    speed_kmh: float = 0.0


@dataclass
class Person:
    id: str
    name: str
    role: str                     # "mecanic" | "ajutor"
    phone: str
    home_city: str
    lat: float
    lon: float
    pin: str = "1234"


@dataclass
class CrewAssignment:
    """Echipa cunoscută deja de sistemul de comandă personal (pornirea în program)."""
    train: str
    person_id: str
    role: str
    start: float                  # ora luării în primire
    station: str


class MersTrenuri(Protocol):
    def trains(self, now: float) -> list[Timetable]: ...


class InfoRU(Protocol):
    def live(self, train: str, now: float) -> Optional[LivePosition]: ...


class Personal(Protocol):
    def people(self) -> list[Person]: ...
    def crews(self, now: float) -> list[CrewAssignment]: ...
    def push_pontaj(self, entry: dict) -> None: ...
    def push_comanda(self, comanda: dict) -> None: ...
