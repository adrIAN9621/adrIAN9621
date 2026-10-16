"""Adaptoare HTTP pentru sistemele reale.

Formatul JSON așteptat e descris în INTEGRARE.md. Dacă un sistem nu are API
în acest format, se scrie doar maparea în funcția `_map_*` corespunzătoare –
restul aplicației rămâne neschimbat.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional

from .base import CrewAssignment, LivePosition, Person, StopTime, Timetable


def _ts(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return datetime.fromisoformat(str(v)).timestamp()


class _Client:
    def __init__(self, http: dict, key: str):
        self.base = (http.get(key) or "").rstrip("/")
        self.token = http.get("token", "")
        self.timeout = float(http.get("timeout_sec", 10))
        if not self.base:
            raise ValueError(f"Lipsește '{key}' în config.json → http")

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self._req("GET", path)

    def post(self, path: str, body: Any) -> Any:
        return self._req("POST", path, body)


class HttpMersTrenuri:
    """GET {mers_trenuri_url}/trenuri?data=YYYY-MM-DD"""

    def __init__(self, http: dict):
        self.c = _Client(http, "mers_trenuri_url")
        self._cache: tuple[float, list[Timetable]] = (0.0, [])

    def trains(self, now: float) -> list[Timetable]:
        if time.time() - self._cache[0] < 300:
            return self._cache[1]
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        rows = self.c.get(f"/trenuri?data={day}") or []
        tts = [Timetable(
            train=str(r["tren"]), kind=r.get("tip", ""),
            stops=[StopTime(s["statie"], _ts(s.get("sosire")), _ts(s.get("plecare"))) for s in r["opriri"]],
        ) for r in rows]
        self._cache = (time.time(), tts)
        return tts


class HttpInfoRU:
    """GET {inforu_url}/pozitie/{tren}"""

    def __init__(self, http: dict):
        self.c = _Client(http, "inforu_url")

    def live(self, train: str, now: float) -> Optional[LivePosition]:
        try:
            r = self.c.get(f"/pozitie/{urllib.parse.quote(train)}")
        except Exception:
            return None
        if not r:
            return None
        return LivePosition(
            train=train, lat=float(r["lat"]), lon=float(r["lon"]),
            delay_min=float(r.get("intarziere_min", 0)), status=r.get("stare", "in_mers"),
            last_index=int(r.get("index_ultima_statie", -1)),
            passed={k: _ts(v) for k, v in (r.get("treceri") or {}).items()},
            speed_kmh=float(r.get("viteza_kmh", 0)),
        )


class HttpPersonal:
    """Comandă personal / SIT / RCC: personal, echipaje curente, pontaj, comenzi."""

    def __init__(self, http: dict):
        self.c = _Client(http, "personal_url")

    def people(self) -> list[Person]:
        return [Person(
            id=str(r["id"]), name=r["nume"], role=r["rol"], phone=r.get("telefon", ""),
            home_city=r.get("localitate", ""), lat=float(r["lat"]), lon=float(r["lon"]),
            pin=str(r.get("pin", "")),
        ) for r in self.c.get("/personal") or []]

    def crews(self, now: float) -> list[CrewAssignment]:
        return [CrewAssignment(
            train=str(r["tren"]), person_id=str(r["id_personal"]), role=r["rol"],
            start=_ts(r["inceput"]), station=r["statie"],
        ) for r in self.c.get("/echipaje") or []]

    def push_pontaj(self, entry: dict) -> None:
        self.c.post("/pontaj", entry)

    def push_comanda(self, comanda: dict) -> None:
        self.c.post("/comenzi", comanda)
