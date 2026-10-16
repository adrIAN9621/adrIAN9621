"""Simulator pentru Mersul Trenurilor + InfoRU + Comandă personal.

Generează trenuri de marfă care circulă pe rute reale, cu întârzieri, și
personal cu domiciliul în orașele de pe rețea. Totul e determinist (seed fix),
ca demonstrațiile și testele să arate la fel de fiecare dată.
"""
from __future__ import annotations

import random
from typing import Optional

from ..geo import STATIONS, station_km
from .base import CrewAssignment, LivePosition, Person, StopTime, Timetable

H = 3600.0
FREIGHT_KMH = 50.0       # viteză medie pe linie dreaptă (include restricții)
TRACK_FACTOR = 1.25
DWELL_MIN = 10.0

# (număr, tip, rută, plecare față de pornirea simulării în ore)
TRAINS = [
    ("50421", "marfă", ["BN", "PV", "CP", "PR", "BV", "SG", "MD", "CM", "TE", "AI", "SI", "DE", "AR"], -8.6),
    ("50422", "marfă", ["AR", "DE", "SI", "AI", "TE", "CM", "MD", "SG", "BV", "PR", "CP", "PV", "BN"], -6.0),
    ("80311", "marfă", ["CT", "MG", "FT", "BN", "PT", "CR"], -8.0),
    ("60125", "marfă", ["IS", "PS", "BC", "AD", "MR", "FO", "BZ", "PV", "BN"], -7.4),
    ("60126", "marfă", ["BN", "BZ", "FO", "MR", "AD", "BC", "PS", "SV"], -3.0),
    ("70451", "marfă", ["CR", "FI", "TJ", "PE", "SI", "DE", "AR", "TM"], -9.8),
    ("40233", "marfă", ["CJ", "RA", "TE", "AI", "SI", "DE", "AR"], -5.0),
    ("40234", "marfă", ["BV", "SG", "MD", "CM", "TE", "RA", "CJ"], -1.0),
]

FIRST = ["Ion", "Gheorghe", "Vasile", "Constantin", "Mihai", "Andrei", "Florin", "Marius", "Cristian",
         "Adrian", "Dan", "Bogdan", "Ionuț", "Sorin", "Cătălin", "Radu", "Alexandru", "Nicolae",
         "Ștefan", "Lucian", "Daniel", "Valentin", "Ciprian", "Ovidiu", "Mircea", "Elena", "Maria"]
LAST = ["Popescu", "Ionescu", "Popa", "Stan", "Dumitru", "Stoica", "Gheorghe", "Matei", "Ciobanu",
        "Rusu", "Munteanu", "Moldovan", "Tudor", "Lazăr", "Dinu", "Barbu", "Neagu", "Marin",
        "Toma", "Nistor", "Florea", "Diaconu", "Sârbu", "Crăciun", "Pavel", "Oprea"]

# orașele în care locuiește personalul (mai mulți în nodurile mari)
HOMES = ["BN", "BN", "BN", "PV", "BV", "BV", "SG", "MD", "TE", "AI", "SI", "DE", "AR", "TM",
         "CJ", "BZ", "FO", "AD", "BC", "PS", "SV", "IS", "FT", "CT", "PT", "CR", "TJ", "PE", "CM", "RA"]


class Simulator:
    def __init__(self, start: float, seed: int = 7):
        self.start = start
        rnd = random.Random(seed)
        self._tt: dict[str, Timetable] = {}
        self._delay: dict[str, tuple[float, float]] = {}
        for number, kind, route, dep_h in TRAINS:
            self._tt[number] = self._build(number, kind, route, start + dep_h * H)
            # întârziere inițială (min) + derivă (min pe oră de mers)
            self._delay[number] = (rnd.uniform(0, 35), rnd.uniform(-1.5, 4.0))

        self._people: list[Person] = []
        names = set()
        for role, prefix in (("mecanic", "M"), ("ajutor", "A")):
            for i, home in enumerate(HOMES):
                while True:
                    n = f"{rnd.choice(LAST)} {rnd.choice(FIRST)}"
                    if n not in names:
                        names.add(n)
                        break
                _, lat, lon = STATIONS[home]
                # domiciliul e în jurul orașului, nu fix în stație
                lat += rnd.uniform(-0.12, 0.12)
                lon += rnd.uniform(-0.15, 0.15)
                self._people.append(Person(
                    id=f"{prefix}{i + 1:03d}", name=n, role=role,
                    phone=f"07{rnd.randint(20, 89)}{rnd.randint(100000, 999999)}",
                    home_city=STATIONS[home][0], lat=round(lat, 5), lon=round(lon, 5),
                ))

        # echipajele inițiale: cel mai apropiat de stația de plecare, fiecare o singură dată
        self._crews: list[CrewAssignment] = []
        used: set[str] = set()
        for number, _, route, _dep in TRAINS:
            tt = self._tt[number]
            origin = route[0]
            for role in ("mecanic", "ajutor"):
                pool = [p for p in self._people if p.role == role and p.id not in used]
                _, la, lo = STATIONS[origin]
                best = min(pool, key=lambda p: (p.lat - la) ** 2 + (p.lon - lo) ** 2)
                used.add(best.id)
                self._crews.append(CrewAssignment(
                    train=number, person_id=best.id, role=role,
                    start=tt.stops[0].dep - 1 * H, station=origin))

    @staticmethod
    def _build(number: str, kind: str, route: list[str], dep: float) -> Timetable:
        stops = [StopTime(route[0], None, dep)]
        t = dep
        for a, b in zip(route, route[1:]):
            t += station_km(a, b) * TRACK_FACTOR / FREIGHT_KMH * H
            arr = t
            t += DWELL_MIN * 60
            stops.append(StopTime(b, arr, t))
        stops[-1].dep = None
        return Timetable(number, kind, stops)

    # ------------------------------------------------------- Mersul Trenurilor
    def trains(self, now: float) -> list[Timetable]:
        return list(self._tt.values())

    # ------------------------------------------------------------------ InfoRU
    def _delay_at(self, train: str, t: float) -> float:
        d0, drift = self._delay[train]
        dep = self._tt[train].stops[0].dep
        return max(0.0, d0 + drift * max(0.0, t - dep) / H)

    def _actual(self, train: str, planned: float) -> float:
        return planned + self._delay_at(train, planned) * 60

    def live(self, train: str, now: float) -> Optional[LivePosition]:
        tt = self._tt.get(train)
        if tt is None:
            return None
        stops = tt.stops
        dep0 = self._actual(train, stops[0].dep)
        _, lat, lon = STATIONS[stops[0].station]
        if now < dep0:
            return LivePosition(train, lat, lon, self._delay_at(train, now), "neplecat", -1)

        passed = {stops[0].station: dep0}
        for i in range(1, len(stops)):
            a_dep = self._actual(train, stops[i - 1].dep)
            a_arr = self._actual(train, stops[i].arr)
            delay = self._delay_at(train, min(now, a_arr))
            if now < a_arr:  # între stația i-1 și i
                f = (now - a_dep) / max(a_arr - a_dep, 1)
                _, la, lo = STATIONS[stops[i - 1].station]
                _, lb, lob = STATIONS[stops[i].station]
                km_h = station_km(stops[i - 1].station, stops[i].station) * TRACK_FACTOR / ((a_arr - a_dep) / H)
                return LivePosition(train, la + (lb - la) * f, lo + (lob - lo) * f, delay,
                                    "in_mers", i - 1, passed, round(km_h))
            passed[stops[i].station] = a_arr
            if stops[i].dep is None:
                _, la, lo = STATIONS[stops[i].station]
                return LivePosition(train, la, lo, delay, "sosit", i, passed)
            if now < self._actual(train, stops[i].dep):
                _, la, lo = STATIONS[stops[i].station]
                return LivePosition(train, la, lo, delay, "in_statie", i, passed)
        raise AssertionError("unreachable")

    # ---------------------------------------------- Comandă personal / SIT / RCC
    def people(self) -> list[Person]:
        return list(self._people)

    def crews(self, now: float) -> list[CrewAssignment]:
        return [c for c in self._crews if c.start <= now]

    def push_pontaj(self, entry: dict) -> None:
        pass

    def push_comanda(self, comanda: dict) -> None:
        pass
