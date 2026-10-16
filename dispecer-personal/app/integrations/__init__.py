from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import CrewAssignment, InfoRU, LivePosition, MersTrenuri, Person, Personal, StopTime, Timetable


def build(cfg: Config, start: float):
    """Întoarce (mers_trenuri, inforu, personal) după sursa configurată."""
    if cfg.sursa == "cmdpers_live":
        from ..cmdpers import from_config
        from .locatii import CmdPersLive
        client = from_config()
        client.login()
        src = CmdPersLive(_folder(cfg), client)
        return src, src, src
    if cfg.sursa in ("inforu", "inforu_live"):
        from .inforu_sursa import InfoRUSource
        client = None
        if cfg.sursa == "inforu_live":
            from ..inforu import from_config as inforu_client
            client = inforu_client()
        src = InfoRUSource(_folder(cfg), replay=cfg.sursa == "inforu" and bool(cfg.fisiere.get("reluare", True)),
                           client=client)
        return src, src, src
    if cfg.sursa == "cmdpers":
        from .locatii import LocatiiSource
        src = LocatiiSource(_folder(cfg), bool(cfg.fisiere.get("reluare", True)))
        return src, src, src
    if cfg.sursa == "fisiere":
        from .fisiere import FileSource
        src = FileSource(_folder(cfg), bool(cfg.fisiere.get("reluare", True)))
        return src, src, src
    if cfg.sursa == "http":
        from .http_adapters import HttpInfoRU, HttpMersTrenuri, HttpPersonal
        personal = HttpPersonal(cfg.http)
        if cfg.doar_citire:
            personal = ReadOnly(personal)
        return HttpMersTrenuri(cfg.http), HttpInfoRU(cfg.http), personal
    from .simulator import Simulator
    sim = Simulator(start)
    return sim, sim, sim


def _folder(cfg: Config) -> Path:
    folder = Path(cfg.fisiere.get("dosar", "date-reale"))
    return folder if folder.is_absolute() else Path(__file__).resolve().parents[2] / folder


class ReadOnly:
    """Blochează orice scriere spre sistemul de personal (doar_citire = true)."""

    def __init__(self, inner):
        self.inner = inner

    def people(self):
        return self.inner.people()

    def crews(self, now):
        return self.inner.crews(now)

    def push_pontaj(self, entry):
        pass

    def push_comanda(self, comanda):
        pass


__all__ = ["build", "CrewAssignment", "InfoRU", "LivePosition", "MersTrenuri",
           "Person", "Personal", "StopTime", "Timetable"]
