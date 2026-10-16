"""Trenurile din InfoRU („Trenuri în circulație – În parcurs”) ca sursă pentru motor – DOAR CITIRE.

Pentru fiecare tren InfoRU dă ultima stație raportată cu ora reală, întârzierea și destinația.
Din instantanee succesive (la 1-2 minute) rezultă trecerile prin stații → schimbul de echipaj
și pontajul se fac pe orele oficiale. Direcția e sigură: spre destinația din „Relatia”.

  * stații de schimb = stațiile dintre poziția curentă și destinație, din cele care apar ca
    „Raportat” în InfoRU (stații reale, nu halte) plus lista din geo.py
  * dacă există și poziții GPS din CmdPers (`<dosar>/locatii/`), markerul de pe hartă le folosește

Dosarul: `<dosar>/inforu/*.json` = {"ora", "coloane", "trenuri": [rânduri ca în tabel]}
(scrise de `python -m app.inforu inregistreaza` sau de modul live).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .. import geo
from ..inforu import normalizeaza
from ..statii import Statii
from .base import CrewAssignment, LivePosition, StopTime, Timetable
from .fisiere import _read, _ts
from .locatii import LocatiiSource

H = 3600.0
VITEZA = 45.0           # km/h medie marfă, pentru ora estimată în stațiile din față
TRACK_FACTOR = 1.25
DISPARUT = 30 * 60      # trenul nu mai apare în „În parcurs” de atâta timp → considerat ajuns
GPS_PROASPAT = 15 * 60


class InfoRUSource(LocatiiSource):
    cere_date = False

    def __init__(self, folder: str | Path, replay: bool = True, client=None, interval: float = 120.0):
        self.statii = Statii()
        self._snaps: list[float] = []
        self._hist: dict[str, list[tuple[float, dict]]] = {}   # id -> [(ora instantaneu, rând normalizat)]
        self._seen_inforu: set[Path] = set()
        self._raportate: set[str] = set()                       # coduri de stații raportate în InfoRU
        self._edges: dict[str, dict[str, float]] = {}           # legături învățate: stație → stație următoare (km)
        self._prev_code: dict[str, str] = {}
        self.client, self.interval, self._last_fetch = client, interval, 0.0
        super().__init__(folder, replay)
        if not self._snaps and client is None:
            raise ValueError(f"Nu există înregistrări InfoRU în {self.dir / 'inforu'}")

    # ------------------------------------------------------------- încărcare
    def station(self, name: str, lat=None, lon=None) -> Optional[str]:
        return super().station(name, lat, lon) or self.statii.code(name)

    def _scan(self) -> None:
        if (self.dir / "locatii").is_dir():
            super()._scan()  # GPS din CmdPers, opțional
        for p in sorted((self.dir / "inforu").glob("*.json")) if (self.dir / "inforu").is_dir() else []:
            if p in self._seen_inforu:
                continue
            self._seen_inforu.add(p)
            try:
                snap = _read(p)
                self._ingest_inforu(_ts(snap["ora"]), snap.get("trenuri") or [])
            except Exception as e:
                self.warnings.append(f"Instantaneu InfoRU ilizibil {p.name}: {e}")

    def _ingest_inforu(self, t: float, rows: list[dict]) -> None:
        self._snaps.append(t)
        self._snaps.sort()
        for row in rows:
            rec = normalizeaza(row)
            if not rec:
                continue
            code = self.statii.code(rec["statie"])
            if code:
                self._raportate.add(code)
                prev = self._prev_code.get(rec["id"])
                if prev and prev != code:  # trenul a mers din prev în code → legătură pe rețea
                    km = geo.station_km(prev, code)
                    if km < 150:  # salturi mari = raportări lipsă, nu legătură directă
                        self._edges.setdefault(prev, {})[code] = km
                        self._edges.setdefault(code, {})[prev] = km
                self._prev_code[rec["id"]] = code
            self._hist.setdefault(rec["id"], []).append((t, rec))
        self._memo = (-1.0, {})

    def start_time(self) -> float:
        return self._snaps[0] if self._snaps else time.time()

    def _poll(self, now: float) -> None:
        if self.client is None or time.time() - self._last_fetch < self.interval:
            return
        self._last_fetch = time.time()
        try:
            cols, rows = self.client.trenuri()
        except Exception as e:
            self.warnings.append(f"InfoRU: {e}")
            return
        d = self.dir / "inforu"
        d.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        ts = datetime.fromtimestamp(now).replace(microsecond=0)
        path = d / f"{ts:%Y-%m-%dT%H-%M-%S}.json"
        path.write_text(json.dumps({"ora": ts.isoformat(), "coloane": cols, "trenuri": rows}, ensure_ascii=False),
                        encoding="utf-8")
        self._seen_inforu.add(path)
        self._ingest_inforu(now, rows)

    # ---------------------------------------------------------------- stare
    def _state(self, now: float) -> dict:
        self._poll(now)
        if not self.replay:
            self._scan()
        if self._memo[0] == now:
            return self._memo[1]
        snaps = [t for t in self._snaps if t <= now]
        if not snaps:
            return {}
        last_snap = snaps[-1]
        out = {}
        for rid, hist in self._hist.items():
            h = [(t, r) for t, r in hist if t <= now]
            if not h:
                continue
            st = self._train_from_inforu(h, last_snap, now)
            if st:
                out[st["tt"].train] = st
        self._memo = (now, out)
        return out

    def _path(self, cur: str, dest: str) -> Optional[list[tuple[float, str]]]:
        """Drumul cel mai scurt pe legăturile învățate din InfoRU → [(km de la cur, stație)] fără cur/dest."""
        import heapq
        dist, prev, seen = {cur: 0.0}, {}, set()
        q = [(0.0, cur)]
        while q:
            d, u = heapq.heappop(q)
            if u in seen:
                continue
            seen.add(u)
            if u == dest:
                break
            for v, km in self._edges.get(u, {}).items():
                if d + km < dist.get(v, 1e18):
                    dist[v], prev[v] = d + km, u
                    heapq.heappush(q, (d + km, v))
        if dest not in seen:
            return None
        path, u = [], dest
        while u != cur:
            path.append(u)
            u = prev[u]
        path.reverse()
        return [(dist[c], c) for c in path[:-1]]

    def _ahead(self, cur: str, dest: Optional[str], heading: Optional[float] = None) -> list[tuple[float, str]]:
        if not dest or dest == cur:
            return []
        learned = self._path(cur, dest)
        if learned is not None:
            return learned
        _, la, lo = geo.STATIONS[cur]
        _, ld, lod = geo.STATIONS[dest]
        total = geo.haversine_km(la, lo, ld, lod)
        cands = self._raportate | {c for c in geo.STATIONS if c.isupper() and len(c) <= 3}
        out = []
        for c in cands:
            if c in (cur, dest) or c.startswith("@") or c not in geo.STATIONS:
                continue
            _, ls, los = geo.STATIONS[c]
            a, b = geo.haversine_km(la, lo, ls, los), geo.haversine_km(ls, los, ld, lod)
            if a < total and b < total and a + b <= total * 1.25 + 10:
                if heading is not None and geo.angle_diff(geo.bearing_deg(la, lo, ls, los), heading) > 75:
                    continue
                out.append((a, c))
        out.sort()
        return out

    def _train_from_inforu(self, h: list[tuple[float, dict]], last_snap: float, now: float) -> Optional[dict]:
        t_seen, rec = h[-1]
        cur = self.statii.code(rec["statie"])
        if not cur:
            return None
        dest = self.statii.code(rec["destinatie"])
        key = f"{rec['tren']}/{rec['zi']}" if rec["zi"] else rec["tren"]

        # trecerile: ora reală raportată, altfel momentul în care stația a apărut prima dată
        passed: dict[str, float] = {}
        prev = None
        for t, r in h:
            c = self.statii.code(r["statie"])
            if c and (c != prev or r["ora_raportare"]):
                passed[c] = r["ora_raportare"] or passed.get(c) or t
            prev = c

        gone = last_snap - t_seen > DISPARUT
        speed = VITEZA
        _, lat, lon = geo.STATIONS[cur]
        gps = self._tracks.get(rec["tren"]) or self._tracks.get(rec["tren"][:5])
        if gps:
            pts = [p for p in gps if p.t <= now]
            if pts and now - pts[-1].t <= GPS_PROASPAT:
                lat, lon = pts[-1].lat, pts[-1].lon

        # direcția din ultimele două stații raportate (până avem drum învățat spre destinație)
        heading, codes = None, [c for c in passed if c != cur]
        if codes:
            last_prev = max(codes, key=lambda c: passed[c])
            _, pa, po = geo.STATIONS[last_prev]
            heading = geo.bearing_deg(pa, po, geo.STATIONS[cur][1], geo.STATIONS[cur][2])
        delay = rec["intarziere_min"]
        t0 = max(now, rec["ora_raportare"] or t_seen)
        stops = [StopTime(cur, None, t0)]
        for km, c in self._ahead(cur, dest, heading):
            eta = t0 + km * TRACK_FACTOR / speed * H
            stops.append(StopTime(c, eta - delay * 60, eta - delay * 60))
        if dest and dest != cur:
            _, ld, lod = geo.STATIONS[dest]
            km_dest = geo.haversine_km(geo.STATIONS[cur][1], geo.STATIONS[cur][2], ld, lod) * TRACK_FACTOR
            if len(stops) > 1:  # pe drumul învățat distanța e cel puțin cea până la ultima stație
                km_dest = max(km_dest, (stops[-1].arr + delay * 60 - t0) / H * speed)
            eta = t0 + km_dest / speed * H
            stops.append(StopTime(dest, eta - delay * 60, None))
        else:  # destinație necunoscută sau deja acolo
            end = f"@{key}>"
            geo.STATIONS[end] = ("(destinație)", lat, lon)
            stops.append(StopTime(end, t0 + 48 * H, None))
        final = stops[-1].station

        arrived = gone or (dest is not None and cur == dest)
        if arrived:
            passed.setdefault(final, rec["ora_raportare"] or t_seen)
        status = "sosit" if arrived else ("in_statie" if rec["sosire_reala"] and not rec["plecare_reala"] else "in_mers")
        tt = Timetable(key, f"rang {rec['rang']} · {rec['origine']} → {rec['destinatie']}".strip(), stops)
        live = LivePosition(key, lat, lon, delay_min=delay, status=status,
                            last_index=len(stops) - 1 if arrived else 0, passed=passed, speed_kmh=0)
        return {"tt": tt, "live": live}

    # ------------------------------------------------------------ echipaje
    def crews(self, now: float) -> list[CrewAssignment]:
        """În echipaje.json trenul poate fi scris „584640” – îl legăm de circulația activă."""
        active = list(self._state(now).keys())
        out = []
        for c in super().crews(now):
            if c.train in active:
                out.append(c)
                continue
            # Comanda poate scrie trenul mai scurt (58428 față de 584280 în InfoRU)
            match = sorted(k for k in active if k.split("/")[0] == c.train
                           or (len(c.train) >= 5 and k.split("/")[0].startswith(c.train)))
            if match:
                out.append(CrewAssignment(match[-1], c.person_id, c.role, c.start, c.station, c.name))
        return out


def snapshot_rows(path: Path) -> list[dict]:
    return _read(path).get("trenuri") or []
