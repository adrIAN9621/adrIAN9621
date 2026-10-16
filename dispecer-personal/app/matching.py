"""Alegerea înlocuitorului: cel mai apropiat mecanic / ajutor de trenul care vine.

1. Stațiile candidate pentru schimb = stațiile din fața trenului (în sensul de
   mers) pe care trenul le atinge înainte ca echipajul actual să-și termine
   programul (minus o marjă). Stația finală nu contează – acolo se termină oricum.
2. Pentru fiecare om disponibil se calculează distanța domiciliu → fiecare stație
   candidată și dacă ajunge acolo înaintea trenului.
3. Fiecare om primește stația cea mai apropiată de el; lista se sortează după
   distanță. Primul din listă primește oferta.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .config import Config
from .geo import road_km, travel_minutes
from .integrations.base import LivePosition, Timetable

SAFETY_MIN = 5.0   # omul trebuie să fie în stație cu cel puțin 5 min înaintea trenului


@dataclass
class HandoverPoint:
    station: str
    index: int
    eta: float           # sosirea estimată a trenului (planificat + întârziere)
    urgent: bool = False  # nicio stație nu încape în program – se ia prima din față


@dataclass
class Candidate:
    person_id: str
    name: str
    station: str
    eta: float
    km: float
    travel_min: float
    slack_min: float     # cât așteaptă omul în stație până vine trenul


def eta_at(tt: Timetable, live: LivePosition, index: int) -> float:
    stop = tt.stops[index]
    return stop.arr + live.delay_min * 60


def handover_points(cfg: Config, tt: Timetable, live: LivePosition, program_end: float) -> list[HandoverPoint]:
    limit = program_end - cfg.marja_predare_min * 60
    ahead = range(live.last_index + 1, len(tt.stops) - 1)
    pts = [HandoverPoint(tt.stops[i].station, i, eta_at(tt, live, i)) for i in ahead]
    ok = [p for p in pts if p.eta <= limit]
    if ok:
        return ok
    if pts:  # programul se termină înainte de următoarea stație: schimbul cât mai repede
        first = pts[0]
        first.urgent = True
        return [first]
    return []


def final_eta(tt: Timetable, live: LivePosition) -> float:
    return eta_at(tt, live, len(tt.stops) - 1)


def needs_replacement(cfg: Config, tt: Timetable, live: LivePosition, program_end: float) -> bool:
    """Nu trebuie înlocuitor dacă trenul ajunge la destinație în program."""
    return final_eta(tt, live) > program_end - cfg.marja_predare_min * 60


def rank(cfg: Config, now: float, points: list[HandoverPoint], people: Iterable[dict],
         only_station: Optional[str] = None) -> list[Candidate]:
    if only_station:
        points = [p for p in points if p.station == only_station] or points
    out: list[Candidate] = []
    for p in people:
        if p.get("lat") is None or p.get("lon") is None:
            continue  # fără domiciliu cunoscut nu putem calcula distanța
        best: Optional[Candidate] = None
        for hp in points:
            if p.get("status") == "pauza" and p.get("pauza_de_la"):
                # tura a 2-a: începe (la sosirea trenului) după minimum 2 h și maximum 6 h de pauză
                start = hp.eta
                if not (p["pauza_de_la"] + cfg.pauza_min_ore * 3600 <= start <= p["pauza_de_la"] + cfg.pauza_max_ore * 3600):
                    continue
            km = road_km(p["lat"], p["lon"], hp.station)
            if km > cfg.raza_max_km:
                continue
            tmin = travel_minutes(km, cfg.viteza_deplasare_kmh, cfg.pregatire_min)
            slack = (hp.eta - now) / 60 - tmin
            if slack < SAFETY_MIN and not hp.urgent:
                continue
            c = Candidate(p["id"], p["name"], hp.station, hp.eta, round(km, 1), round(tmin), round(slack))
            # cea mai apropiată stație; la egalitate, cea mai îndepărtată pe traseu
            if best is None or (c.km, -c.eta) < (best.km, -best.eta):
                best = c
        if best:
            out.append(best)
    out.sort(key=lambda c: (c.km, -c.slack_min))
    return out
