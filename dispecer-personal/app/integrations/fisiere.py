"""Date reale din fișiere – pentru teste fără nicio legătură cu producția.

Scriptul de pe TV wall (care are deja acces la InfoFer și la Comandă) salvează
periodic ce citește într-un dosar; aplicația doar citește acel dosar. Nimic nu
se trimite înapoi: comenzile propuse și pontajul calculat se scriu local în
`<dosar>/iesire/`, ca să fie comparate cu ce s-a întâmplat în realitate.

Structura dosarului (formatul câmpurilor e cel din INTEGRARE.md):

    statii.json      (opțional) {"Brașov": {"lat": 45.66, "lon": 25.61}, ...}
    personal.json    lista personalului (ca GET /personal)
    mers.json        mersul trenurilor (ca GET /trenuri)
    instantanee/     câte un fișier la fiecare citire:
        2026-10-16T19-00-00.json  {"ora": ISO, "pozitii": {"50421": {...ca GET /pozitie}},
                                   "echipaje": [...ca GET /echipaje]}

Reluare (`reluare: true`): ceasul pornește de la primul instantaneu și „rulează”
ziua înregistrată. Fără reluare se citește mereu cel mai nou instantaneu (live).
"""
from __future__ import annotations

import bisect
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .. import geo
from .base import CrewAssignment, LivePosition, Person, StopTime, Timetable


def _ts(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    m = re.fullmatch(r"/?Date\((-?\d+)(?:[+-]\d{4})?\)/?", s)
    if m:  # formatul JSON vechi ASP.NET: /Date(1760000000000)/ (milisecunde UTC)
        return int(m.group(1)) / 1000.0
    # Python < 3.11 nu acceptă „Z” și nici mai mult de 6 zecimale (.NET dă 7)
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    return datetime.fromisoformat(s).timestamp()


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace(".", " ").split())


def _read(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8-sig"))


class FileSource:
    def __init__(self, folder: str | Path, replay: bool = True):
        self.dir = Path(folder)
        if not self.dir.is_dir():
            raise ValueError(f"Dosarul cu date reale nu există: {self.dir}")
        self.replay = replay
        self.warnings: list[str] = []
        self._load_stations()
        self._people = self._load_people()
        self._tt = self._load_timetables()
        self._snaps: list[tuple[float, Path]] = []
        self._cache: dict[Path, dict] = {}
        self._scan()
        if not self._snaps:
            raise ValueError(f"Nu există instantanee în {self.dir / 'instantanee'}")

    # --------------------------------------------------------- încărcare
    def _load_stations(self) -> None:
        self._by_name = {_norm(v[0]): k for k, v in geo.STATIONS.items()}
        self._by_name.update({_norm(k): k for k in geo.STATIONS})
        p = self.dir / "statii.json"
        if p.exists():
            for name, c in _read(p).items():
                self._register(name, c["lat"], c["lon"])

    def _register(self, name: str, lat: float, lon: float) -> str:
        code = self._by_name.get(_norm(name)) or name
        geo.STATIONS[code] = (geo.STATIONS.get(code, (name,))[0], float(lat), float(lon))
        self._by_name[_norm(name)] = code
        return code

    def station(self, name: str, lat=None, lon=None) -> Optional[str]:
        if lat is not None and lon is not None:
            return self._register(name, lat, lon)
        return self._by_name.get(_norm(name))

    def _load_people(self) -> list[Person]:
        out = []
        for r in _read(self.dir / "personal.json"):
            if r.get("lat") is None or r.get("lon") is None:
                self.warnings.append(f"Fără coordonate domiciliu: {r.get('nume')} ({r.get('id')}) – ignorat")
                continue
            out.append(Person(id=str(r["id"]), name=r["nume"], role=r["rol"], phone=r.get("telefon", ""),
                              home_city=r.get("localitate", ""), lat=float(r["lat"]), lon=float(r["lon"]),
                              pin=str(r.get("pin") or "1234")))
        return out

    def _load_timetables(self) -> dict[str, Timetable]:
        out = {}
        for r in _read(self.dir / "mers.json"):
            stops = []
            for s in r["opriri"]:
                code = self.station(s["statie"], s.get("lat"), s.get("lon"))
                if not code:
                    self.warnings.append(f"Tren {r['tren']}: stație fără coordonate „{s['statie']}” – sărită")
                    continue
                stops.append(StopTime(code, _ts(s.get("sosire")), _ts(s.get("plecare"))))
            if len(stops) < 2:
                continue
            stops[0].arr, stops[-1].dep = None, None
            for s in stops[1:]:  # fără oră de sosire (trecere) → folosim plecarea
                s.arr = s.arr if s.arr is not None else s.dep
            if any(s.arr is None for s in stops[1:]):
                self.warnings.append(f"Tren {r['tren']}: lipsesc ore din mers – ignorat")
                continue
            out[str(r["tren"])] = Timetable(str(r["tren"]), r.get("tip", ""), stops)
        return out

    def _scan(self) -> None:
        snaps = []
        for p in (self.dir / "instantanee").glob("*.json"):
            try:
                snaps.append((_ts(_read(p)["ora"]), p))
            except Exception as e:  # fișier pe jumătate scris sau stricat
                self.warnings.append(f"Instantaneu ilizibil {p.name}: {e}")
        self._snaps = sorted(snaps)

    def start_time(self) -> float:
        return self._snaps[0][0]

    def _snapshot(self, now: float) -> Optional[dict]:
        if not self.replay:
            self._scan()
            i = len(self._snaps) - 1
        else:
            i = bisect.bisect_right([t for t, _ in self._snaps], now) - 1
        if i < 0:
            return None
        p = self._snaps[i][1]
        if p not in self._cache:
            self._cache = {p: _read(p)}
        return self._cache[p]

    # ------------------------------------------------- Mersul Trenurilor
    def trains(self, now: float) -> list[Timetable]:
        return list(self._tt.values())

    # ------------------------------------------------------------ InfoRU
    def live(self, train: str, now: float) -> Optional[LivePosition]:
        snap = self._snapshot(now)
        tt = self._tt.get(train)
        r = (snap or {}).get("pozitii", {}).get(train)
        if not r or not tt:
            return None
        passed = {}
        for name, t in (r.get("treceri") or {}).items():
            code = self.station(name)
            if code:
                passed[code] = _ts(t)
        idx = r.get("index_ultima_statie")
        if idx is None:  # deducem din ultima stație atinsă
            reached = [i for i, s in enumerate(tt.stops) if s.station in passed]
            idx = max(reached) if reached else -1
        status = r.get("stare") or ("sosit" if idx == len(tt.stops) - 1 else "in_mers")
        return LivePosition(train=train, lat=float(r["lat"]), lon=float(r["lon"]),
                            delay_min=float(r.get("intarziere_min", 0)), status=status,
                            last_index=int(idx), passed=passed, speed_kmh=float(r.get("viteza_kmh", 0)))

    # ------------------------------------------------- Comandă personal
    def people(self) -> list[Person]:
        return list(self._people)

    def crews(self, now: float) -> list[CrewAssignment]:
        snap = self._snapshot(now) or {}
        out = []
        for r in snap.get("echipaje", []):
            code = self.station(r["statie"])
            if code:
                out.append(CrewAssignment(str(r["tren"]), str(r["id_personal"]), r["rol"], _ts(r["inceput"]), code))
        return [c for c in out if c.start <= now]

    # --------------------------- ieșire DOAR locală – nimic spre producție
    def _out(self, name: str, row: dict) -> None:
        d = self.dir / "iesire"
        d.mkdir(exist_ok=True)
        with open(d / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def push_pontaj(self, entry: dict) -> None:
        self._out("pontaj_calculat.jsonl", entry)

    def push_comanda(self, comanda: dict) -> None:
        self._out("comenzi_propuse.jsonl", comanda)
