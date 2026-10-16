from __future__ import annotations

from ..config import Config
from .base import CrewAssignment, InfoRU, LivePosition, MersTrenuri, Person, Personal, StopTime, Timetable


def build(cfg: Config, start: float):
    """Întoarce (mers_trenuri, inforu, personal) după sursa configurată."""
    if cfg.sursa == "http":
        from .http_adapters import HttpInfoRU, HttpMersTrenuri, HttpPersonal
        return HttpMersTrenuri(cfg.http), HttpInfoRU(cfg.http), HttpPersonal(cfg.http)
    from .simulator import Simulator
    sim = Simulator(start)
    return sim, sim, sim


__all__ = ["build", "CrewAssignment", "InfoRU", "LivePosition", "MersTrenuri",
           "Person", "Personal", "StopTime", "Timetable"]
