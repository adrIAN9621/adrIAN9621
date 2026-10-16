"""Date reale din CmdPers – pozițiile locomotivelor (GetLatestLocation), DOAR CITIRE.

Pozițiile vin direct din CmdPers prin `app/cmdpers.py` (autologin): live cu
`CmdPersLive` sau înregistrate în `<dosar>/locatii/` (`python -m app.cmdpers inregistreaza`).
Acest modul le transformă în ce are nevoie aplicația, fără mersul trenurilor:

  * traseul fiecărui tren (din pozițiile succesive ale locomotivei)
  * trecerile prin stații (când traseul trece la mai puțin de `raza_statie_km`)
    → din ele se face schimbul de echipaj și pontajul
  * direcția de mers + viteza medie → stațiile din față și ora estimată de sosire

Opțional, în același dosar:
    statii.json     {"Brașov": {"lat": .., "lon": ..}, ...}  (completează lista din geo.py)
    personal.json   lista personalului cu domiciliul (ca în INTEGRARE.md)
    echipaje.json   [{"tren", "id_personal", "rol", "inceput", "statie"}]  – cine e pe tren

Nimic nu se trimite înapoi: comenzile propuse și pontajul calculat se scriu doar în
`<dosar>/iesire/`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .. import geo
from .base import CrewAssignment, LivePosition, Person, StopTime, Timetable
from .fisiere import FileSource, _read, _ts

H = 3600.0
RAZA_STATIE_KM = 3.0        # trenul „a trecut prin stație” dacă traseul trece mai aproape de atât
ORIZONT_KM = 300.0          # cât de departe în față căutăm stații de schimb
CON_DIRECTIE = 60.0         # ± grade față de direcția de mers
VITEZA_IMPLICITA = 50.0     # km/h dacă trenul stă sau nu avem destule puncte
DISPARUT_DUPA = 3 * H       # fără poziții noi atâta timp → considerăm trenul ajuns
DIRECTIE_MAX = 12 * H       # cât de vechi poate fi ultimul deplasament folosit pentru direcție (tren oprit)
TRACK_FACTOR = 1.25         # linia ferată e mai lungă decât linia dreaptă


@dataclass
class Point:
    t: float
    lat: float
    lon: float
    loco: str


def parse_items(raw: Any) -> list[dict]:
    """Răspunsul GetLatestLocation poate fi listă sau {data: [...]}."""
    if isinstance(raw, str):
        raw = json.loads(raw) if raw.strip() else []
    if isinstance(raw, dict):
        for k in ("data", "Data", "items", "locations"):
            if isinstance(raw.get(k), list):
                return raw[k]
        return []
    return raw if isinstance(raw, list) else []


def train_numbers(item: dict) -> list[str]:
    out = []
    for t in item.get("TrainInfo") or []:
        n = t.get("TrainNumber") if isinstance(t, dict) else t
        if n not in (None, ""):
            out.append(str(n).strip())
    return out


class LocatiiSource(FileSource):
    cere_date = True

    def __init__(self, folder: str | Path, replay: bool = True):
        self.dir = Path(folder)
        if not self.dir.is_dir():
            if self.cere_date:
                raise ValueError(f"Dosarul cu date reale nu există: {self.dir}")
            self.dir.mkdir(parents=True)
        self.replay = replay
        self.warnings: list[str] = []
        self._load_stations()
        self._people = self._load_people() if (self.dir / "personal.json").exists() else []
        if not self._people:
            self.warnings.append("Lipsește personal.json – se văd trenurile, dar nu se pot căuta înlocuitori")
        self._crews = self._load_crews()
        self._seen: set[Path] = set()
        self._tracks: dict[str, list[Point]] = {}
        self._times: list[float] = []
        self._memo: tuple[float, dict] = (-1.0, {})
        self._pcache: dict[str, tuple[int, Point, dict]] = {}  # tren -> treceri deja calculate
        self._scan()
        if not self._times and self.cere_date:
            raise ValueError(f"Nu există înregistrări în {self.dir / 'locatii'}")

    # ------------------------------------------------------- încărcare
    def _load_crews(self) -> list[CrewAssignment]:
        p = self.dir / "echipaje.json"
        if not p.exists():
            self.warnings.append("Lipsește echipaje.json – nu se știe cine e pe tren, deci nu se urmăresc orele")
            return []
        out = []
        for r in _read(p):
            code = self.station(r.get("statie") or "")
            if not code:  # stația fără coordonate nu oprește urmărirea orelor – doar afișarea pe hartă
                self.warnings.append(f"Echipaj tren {r['tren']}: stație fără coordonate „{r.get('statie')}”")
                code = r.get("statie") or "?"
            out.append(CrewAssignment(str(r["tren"]), str(r["id_personal"]), r["rol"], _ts(r["inceput"]), code,
                                      r.get("nume", "")))
        return out

    def _scan(self) -> None:
        files = sorted((self.dir / "locatii").glob("*.json"))
        for p in files:
            if p in self._seen:
                continue
            self._seen.add(p)
            try:
                snap = _read(p)
                t_snap = _ts(snap["ora"])
                items = parse_items(snap.get("date"))
            except Exception as e:  # fișier stricat – îl sărim
                self.warnings.append(f"Înregistrare ilizibilă {p.name}: {e}")
                continue
            self._ingest(t_snap, items)
        self._times.sort()
        for tr in self._tracks.values():
            tr.sort(key=lambda p: p.t)

    def _ingest(self, t_snap: float, items: list[dict]) -> None:
        self._times.append(t_snap)
        for it in items:
            try:
                lat, lon = float(it.get("Lat") or 0), float(it.get("Lng") or 0)
            except (TypeError, ValueError):
                continue
            if not lat or not lon:
                continue
            try:
                t = _ts(it.get("Timestamp")) or t_snap
            except ValueError:
                t = t_snap
            t = min(t, t_snap)
            for n in train_numbers(it):
                tr = self._tracks.setdefault(n, [])
                if tr and tr[-1].t >= t:
                    continue  # aceeași poziție raportată din nou
                tr.append(Point(t, lat, lon, str(it.get("LocomotiveNumber") or "")))

    def start_time(self) -> float:
        return self._times[0]

    # ------------------------------------------------------ calcul stare
    def _state(self, now: float) -> dict:
        if not self.replay:
            self._scan()
        if self._memo[0] == now:
            return self._memo[1]
        out = {}
        for n, tr in self._tracks.items():
            pts = [p for p in tr if p.t <= now]
            if not pts or now - pts[-1].t > 2 * DISPARUT_DUPA:
                continue
            out[n] = self._train_state(n, pts, now)
        self._memo = (now, out)
        return out

    def _passed(self, pts: list[Point], key: Optional[str] = None) -> dict[str, float]:
        """Ultima trecere prin fiecare stație (cu interpolare între două poziții).

        Cu `key` (numărul trenului) segmentele deja calculate la ciclul anterior nu se mai
        recalculează: pozițiile unui tren doar se adaugă la final, deci reluăm de unde am rămas.
        """
        passed: dict[str, float] = {}
        codes = [c for c in geo.STATIONS if not c.startswith("@")]
        start = 0
        if key is not None:
            c = self._pcache.get(key)
            if c and 0 < c[0] <= len(pts) and pts[c[0] - 1] is c[1]:
                start, passed = c[0] - 1, dict(c[2])
        for a, b in zip(pts[start:], pts[start + 1:]):
            lo_lat, hi_lat = min(a.lat, b.lat) - 0.05, max(a.lat, b.lat) + 0.05
            lo_lon, hi_lon = min(a.lon, b.lon) - 0.07, max(a.lon, b.lon) + 0.07
            for c in codes:
                _, sl, so = geo.STATIONS[c]
                if not (lo_lat <= sl <= hi_lat and lo_lon <= so <= hi_lon):
                    continue
                d, f = geo.closest_on_segment(a.lat, a.lon, b.lat, b.lon, sl, so)
                if d <= RAZA_STATIE_KM:
                    passed[c] = a.t + f * (b.t - a.t)
        if key is not None and pts:
            self._pcache[key] = (len(pts), pts[-1], dict(passed))
        if pts:
            last = pts[-1]
            for c in codes:
                _, sl, so = geo.STATIONS[c]
                if geo.haversine_km(last.lat, last.lon, sl, so) <= RAZA_STATIE_KM:
                    passed.setdefault(c, last.t)
        return passed

    def _train_state(self, n: str, pts: list[Point], now: float) -> dict:
        cur = pts[-1]
        # direcția: față de ultima poziție aflată la cel puțin 2 km (ultimul deplasament);
        # un tren care stă de peste o oră în stație își păstrează direcția de mers,
        # altfel stațiile din spate ar deveni „în față”
        heading = None
        for p in reversed(pts[:-1]):
            if cur.t - p.t > DIRECTIE_MAX:
                break
            if geo.haversine_km(p.lat, p.lon, cur.lat, cur.lon) >= 2:
                heading = geo.bearing_deg(p.lat, p.lon, cur.lat, cur.lon)
                break
        # viteza medie pe ultimele 30 de minute
        recent = [p for p in pts if cur.t - p.t <= 1800]
        km = sum(geo.haversine_km(a.lat, a.lon, b.lat, b.lon) for a, b in zip(recent, recent[1:]))
        dt = (recent[-1].t - recent[0].t) / H if len(recent) > 1 else 0
        speed = km / dt if dt > 0 else 0.0

        here = f"@{n}"
        geo.STATIONS[here] = ("poziția curentă", cur.lat, cur.lon)
        ahead = []
        for c, (name, sl, so) in list(geo.STATIONS.items()):
            if c.startswith("@"):
                continue
            d = geo.haversine_km(cur.lat, cur.lon, sl, so)
            if d <= RAZA_STATIE_KM or d > ORIZONT_KM:
                continue
            if heading is not None and geo.angle_diff(geo.bearing_deg(cur.lat, cur.lon, sl, so), heading) > CON_DIRECTIE:
                continue
            ahead.append((d, c))
        ahead.sort()
        v = speed if speed >= 20 else VITEZA_IMPLICITA
        t0 = max(now, cur.t)
        stops = [StopTime(here, None, t0)]
        for d, c in ahead:
            eta = t0 + d * TRACK_FACTOR / v * H
            stops.append(StopTime(c, eta, eta))
        # destinația nu se știe: un capăt virtual după ultima stație, ca orice stație reală să poată fi schimb
        end = f"@{n}>"
        far = geo.STATIONS[ahead[-1][1]] if ahead else geo.STATIONS[here]
        geo.STATIONS[end] = ("(în direcția de mers)", far[1], far[2])
        stops.append(StopTime(end, t0 + 48 * H, None))

        passed = self._passed(pts, n)
        gone = now - cur.t > DISPARUT_DUPA
        if gone:
            passed[end] = cur.t
        status = "sosit" if gone else ("in_mers" if speed >= 5 else "in_statie")
        tt = Timetable(n, f"loc. {cur.loco}".strip(), stops)
        live = LivePosition(n, cur.lat, cur.lon, delay_min=0.0, status=status,
                            last_index=len(stops) - 1 if gone else 0, passed=passed, speed_kmh=round(speed))
        return {"tt": tt, "live": live}

    # ------------------------------------------------- interfețele aplicației
    def trains(self, now: float) -> list[Timetable]:
        return [s["tt"] for s in self._state(now).values()]

    def live(self, train: str, now: float) -> Optional[LivePosition]:
        s = self._state(now).get(train)
        return s["live"] if s else None

    def crews(self, now: float) -> list[CrewAssignment]:
        return [c for c in self._crews if c.start <= now]

    def people(self) -> list:
        """personal.json reimportat e preluat fără repornire."""
        p = self.dir / "personal.json"
        mt = p.stat().st_mtime if p.exists() else 0
        if mt and mt != getattr(self, "_people_mtime", None):
            self._people_mtime = mt
            self._people = self._load_people()
        return list(self._people)


class CmdPersLive(LocatiiSource):
    """Pozițiile vin direct din CmdPers (autologin, doar citire).

    La fiecare `interval` secunde se cere GetLatestLocation; fiecare răspuns se salvează și în
    `<dosar>/locatii/`, ca ziua să poată fi reluată apoi în modul test.
    """
    cere_date = False

    def __init__(self, folder: str | Path, client, interval: float = 60.0):
        self.client = client
        self.interval = interval
        self._last_fetch = 0.0
        super().__init__(folder, replay=True)

    def _poll(self, now: float) -> None:
        import time as _time
        if _time.time() - self._last_fetch < self.interval:
            return
        self._last_fetch = _time.time()
        try:
            items = self.client.locations()
        except Exception as e:
            self.warnings.append(f"CmdPers: {e}")
            return
        d = self.dir / "locatii"
        d.mkdir(exist_ok=True)
        from datetime import datetime
        ts = datetime.fromtimestamp(now).replace(microsecond=0)
        path = d / f"{ts:%Y-%m-%dT%H-%M-%S}.json"
        path.write_text(json.dumps({"ora": ts.isoformat(), "sursa": self.client.server, "date": items},
                                   ensure_ascii=False), encoding="utf-8")
        self._seen.add(path)
        self._ingest(now, items)
        self._memo = (-1.0, {})

    def _state(self, now: float) -> dict:
        self._poll(now)
        return super()._state(now)

    def start_time(self) -> float:
        import time as _time
        return _time.time()
