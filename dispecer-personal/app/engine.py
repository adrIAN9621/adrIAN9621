"""Motorul de dispecerat – rulează la fiecare câteva secunde.

  * citește mersul trenurilor și poziția live din InfoRU
  * ține evidența orelor lucrate de fiecare mecanic / ajutor de pe tren
  * cu `alerta_inainte_ore` înainte de final de program caută înlocuitor
  * trimite oferta celui mai apropiat (ca la Bolt/Uber); dacă refuză sau nu
    răspunde în timp, trece la următorul
  * când trenul ajunge în stația de schimb (confirmat de InfoRU) închide
    pontajul echipajului vechi și îl deschide pe al celui nou
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Optional

from . import matching
from .config import Config
from .db import DB
from .geo import station_name
from .integrations.base import LivePosition, Timetable

H = 3600.0
log = logging.getLogger("dispecer")


class Engine:
    def __init__(self, cfg: Config, db: DB, clock, mers, inforu, personal):
        self.cfg, self.db, self.clock = cfg, db, clock
        self.mers, self.inforu, self.personal = mers, inforu, personal
        self.timetables: dict[str, Timetable] = {}
        self.live: dict[str, LivePosition] = {}
        self.lock = threading.RLock()
        self.online: dict[str, float] = {}      # person_id -> ultima activitate în aplicație (real)
        self._auto: dict[int, float] = {}       # offer_id -> când răspunde automat (simulator)
        self._rnd = random.Random(11)
        self._stop = threading.Event()

    # ------------------------------------------------------------- pornire
    def bootstrap(self) -> None:
        for p in self.personal.people():
            if self.db.one("SELECT id FROM persons WHERE id = ?", [p.id]):
                self.db.x("UPDATE persons SET name=?, role=?, phone=?, home_city=?, lat=?, lon=?, pin=? WHERE id=?",
                          [p.name, p.role, p.phone, p.home_city, p.lat, p.lon, p.pin, p.id])
            else:
                self.db.insert("persons", id=p.id, name=p.name, role=p.role, phone=p.phone,
                               home_city=p.home_city, lat=p.lat, lon=p.lon, pin=p.pin, status="disponibil")
        self.tick()

    def run_forever(self, interval: float = 2.0) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # motorul nu are voie să se oprească din cauza unei erori de date
                log.exception("Eroare în ciclul de dispecerat")
            self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()

    def event(self, kind: str, text: str) -> None:
        self.db.insert("events", t=self.clock.now(), kind=kind, text=text)

    # ---------------------------------------------------------------- ciclu
    def tick(self) -> None:
        with self.lock:
            now = self.clock.now()
            self._refresh(now)
            self._sync_crews(now)
            self._release_rest(now)
            self._check_programs(now)
            self._process_requests(now)
            if self.cfg.test:
                self._simulate_answers(now)

    def _refresh(self, now: float) -> None:
        self.timetables = {t.train: t for t in self.mers.trains(now)}
        live = {}
        for n in self.timetables:
            pos = self.inforu.live(n, now)
            if pos:
                live[n] = pos
        self.live = live

    def _sync_crews(self, now: float) -> None:
        """Preia echipajele aflate deja pe tren conform sistemului de comandă personal."""
        for c in self.personal.crews(now):
            dup = self.db.one("SELECT id FROM pontaj WHERE train=? AND person_id=? AND ABS(start-?) < ?",
                              [c.train, c.person_id, c.start, 12 * H])
            if dup:
                continue
            # rolul e deja acoperit pe tren (ex. de schimbul făcut de aplicație) sau omul e pe alt tren
            taken = self.db.one("SELECT id FROM pontaj WHERE active=1 AND ((train=? AND role=?) OR person_id=?)",
                                [c.train, c.role, c.person_id])
            if taken or not self.db.one("SELECT id FROM persons WHERE id=?", [c.person_id]):
                continue
            self.db.insert("pontaj", train=c.train, person_id=c.person_id, role=c.role, start=c.start,
                           start_station=c.station, active=1, source="comandă personal")
            self.db.update("persons", c.person_id, status="pe_tren", status_until=None)

    def _release_rest(self, now: float) -> None:
        after = "disponibil" if self.cfg.test else "indisponibil"
        for p in self.db.q("SELECT id FROM persons WHERE status='odihna' AND status_until <= ?", [now]):
            self.db.update("persons", p["id"], status=after, status_until=None)

    def program_end(self, pontaj: dict) -> float:
        return pontaj["start"] + self.cfg.program_max_ore * H

    def _check_programs(self, now: float) -> None:
        for pj in self.db.q("SELECT * FROM pontaj WHERE active = 1"):
            tt, lv = self.timetables.get(pj["train"]), self.live.get(pj["train"])
            if not tt or not lv:
                continue
            if lv.status == "sosit":
                final = tt.stops[-1].station
                self._close_pontaj(pj, lv.passed.get(final, now), final)
                for r in self.db.q("SELECT * FROM requests WHERE pontaj_id=? AND status IN ('cautare','oferta','acceptat')", [pj["id"]]):
                    self._cancel_request(r, "trenul a ajuns la destinație")
                continue
            end = self.program_end(pj)
            if now < end - self.cfg.alerta_inainte_ore * H:
                continue
            if self.db.one("SELECT id FROM requests WHERE pontaj_id = ?", [pj["id"]]):
                continue
            if not matching.needs_replacement(self.cfg, tt, lv, end):
                continue
            rid = self.db.insert("requests", train=pj["train"], role=pj["role"], pontaj_id=pj["id"],
                                 created=now, status="cautare")
            name = self._name(pj["person_id"])
            self.event("alerta", f"Tren {pj['train']}: {pj['role']} {name} termină programul la "
                                 f"{_hm(end)} – caut înlocuitor (cererea #{rid})")

    def _close_pontaj(self, pj: dict, t: float, station: str) -> None:
        self.db.update("pontaj", pj["id"], end=t, end_station=station, active=0)
        self.db.update("persons", pj["person_id"], status="odihna", status_until=t + self.cfg.odihna_ore * H)
        row = self.db.one("SELECT * FROM pontaj WHERE id=?", [pj["id"]])
        try:
            self.personal.push_pontaj(_pontaj_export(row, self._name(row["person_id"])))
        except Exception:
            log.exception("Trimiterea pontajului a eșuat")
        self.event("pontaj", f"Pontaj închis: {self._name(pj['person_id'])}, tren {pj['train']}, "
                             f"{station_name(pj['start_station'])} → {station_name(station)}, "
                             f"{(t - pj['start']) / H:.1f} h")

    # --------------------------------------------------- cereri și oferte
    def _process_requests(self, now: float) -> None:
        for r in self.db.q("SELECT * FROM requests WHERE status IN ('cautare','oferta','acceptat') ORDER BY id"):
            if r["status"] == "oferta":
                off = self.db.one("SELECT * FROM offers WHERE request_id=? AND status='trimisa'", [r["id"]])
                if off and time.time() >= off["expires"]:
                    self.db.update("offers", off["id"], status="expirata")
                    self.event("oferta", f"{self._name(off['person_id'])} nu a răspuns la oferta pt. trenul {r['train']}")
                    off = None
                if off:
                    continue
                self.db.update("requests", r["id"], status="cautare")
                r["status"] = "cautare"
            if r["status"] == "acceptat":
                self._try_handover(r, now)
            elif r["status"] == "cautare":
                self._offer_next(r, now)

    def candidates(self, r: dict, now: float) -> list[matching.Candidate]:
        pj = self.db.one("SELECT * FROM pontaj WHERE id=?", [r["pontaj_id"]])
        tt, lv = self.timetables.get(r["train"]), self.live.get(r["train"])
        if not pj or not tt or not lv:
            return []
        points = matching.handover_points(self.cfg, tt, lv, self.program_end(pj))
        tried = {o["person_id"] for o in self.db.q("SELECT person_id FROM offers WHERE request_id=?", [r["id"]])}
        busy = {o["person_id"] for o in self.db.q("SELECT person_id FROM offers WHERE status='trimisa'")}
        people = [p for p in self.db.q("SELECT * FROM persons WHERE status='disponibil' AND role=?", [r["role"]])
                  if p["id"] not in tried and p["id"] not in busy]
        # dacă celălalt membru al echipajului are deja stație de schimb, preferăm aceeași stație
        other = self.db.one("SELECT station FROM requests WHERE train=? AND role<>? AND status IN ('oferta','acceptat') "
                            "AND station IS NOT NULL ORDER BY id DESC", [r["train"], r["role"]])
        cands = matching.rank(self.cfg, now, points, people, other["station"] if other else None)
        if not cands and points:
            # nimeni nu ajunge înaintea trenului: cel mai apropiat, iar trenul așteaptă în stație
            for hp in points:
                hp.urgent = True
            cands = matching.rank(self.cfg, now, points, people, other["station"] if other else None)
        return cands

    def _offer_next(self, r: dict, now: float) -> None:
        cands = self.candidates(r, now)
        if not cands and not self._has_handover_station(r):
            if r["note"] != "fara_statie":
                self.db.update("requests", r["id"], note="fara_statie")
                self.event("critic", f"Tren {r['train']}: nu mai are stații de schimb până la destinație – "
                                     f"{r['role']}ul depășește programul, decizie dispecer")
            return
        if not cands:
            if r["note"] != "fara_candidati":
                self.db.update("requests", r["id"], note="fara_candidati")
                self.event("critic", f"Tren {r['train']}: niciun {r['role']} disponibil în rază – intervenție dispecer")
            return
        self.make_offer(r, cands[0])

    def _has_handover_station(self, r: dict) -> bool:
        tt, lv = self.timetables.get(r["train"]), self.live.get(r["train"])
        return bool(tt and lv and lv.last_index + 1 < len(tt.stops) - 1)

    def make_offer(self, r: dict, c: matching.Candidate) -> int:
        oid = self.db.insert("offers", request_id=r["id"], person_id=c.person_id, station=c.station, eta=c.eta,
                             km=c.km, travel_min=c.travel_min, created=self.clock.now(),
                             expires=time.time() + self.cfg.oferta_expira_sec, status="trimisa")
        self.db.update("requests", r["id"], status="oferta", station=c.station, eta=c.eta, note=None)
        self.event("oferta", f"Ofertă către {c.name} ({c.km:.0f} km): tren {r['train']} în "
                             f"{station_name(c.station)} la {_hm(c.eta)}")
        return oid

    def _cancel_request(self, r: dict, why: str) -> None:
        self.db.update("requests", r["id"], status="anulat", note=why)
        for o in self.db.q("SELECT * FROM offers WHERE request_id=? AND status='trimisa'", [r["id"]]):
            self.db.update("offers", o["id"], status="anulata")
        if r["status"] == "acceptat" and r["person_id"]:
            self.db.update("persons", r["person_id"], status="disponibil")

    def _try_handover(self, r: dict, now: float) -> None:
        tt, lv = self.timetables.get(r["train"]), self.live.get(r["train"])
        if not tt or not lv or r["station"] not in lv.passed:
            # trenul a trecut deja de stație fără schimb (ex. a fost deviat) → anulăm
            if tt and lv and r["station"] in tt.route and tt.index(r["station"]) < lv.last_index:
                self._cancel_request(r, "trenul a trecut de stația de schimb")
            return
        t = lv.passed[r["station"]]
        old = self.db.one("SELECT * FROM pontaj WHERE id=?", [r["pontaj_id"]])
        if old and old["active"]:
            self._close_pontaj(old, t, r["station"])
        off = self.db.one("SELECT * FROM offers WHERE request_id=? AND status='acceptata'", [r["id"]])
        self.db.insert("pontaj", train=r["train"], person_id=r["person_id"], role=r["role"], start=t,
                       start_station=r["station"], active=1, km_deplasare=off["km"] if off else None,
                       min_deplasare=off["travel_min"] if off else None, request_id=r["id"], source="InfoRU")
        self.db.update("persons", r["person_id"], status="pe_tren", status_until=None)
        self.db.update("requests", r["id"], status="finalizat")
        self.event("schimb", f"Tren {r['train']}: {self._name(r['person_id'])} a preluat trenul în "
                             f"{station_name(r['station'])} la {_hm(t)} (pontaj pornit automat)")

    # ------------------------------------------------ acțiuni din aplicații
    def answer(self, offer_id: int, person_id: str, accept: bool) -> dict:
        with self.lock:
            off = self.db.one("SELECT * FROM offers WHERE id=?", [offer_id])
            if not off or off["person_id"] != person_id:
                raise ValueError("Oferta nu există.")
            if off["status"] != "trimisa" or time.time() >= off["expires"]:
                raise ValueError("Oferta nu mai este valabilă.")
            r = self.db.one("SELECT * FROM requests WHERE id=?", [off["request_id"]])
            name = self._name(person_id)
            if not accept:
                self.db.update("offers", offer_id, status="refuzata")
                self.db.update("requests", r["id"], status="cautare")
                self.event("oferta", f"{name} a refuzat trenul {r['train']}")
                self._offer_next({**r, "status": "cautare"}, self.clock.now())
                return {"ok": True}
            self.db.update("offers", offer_id, status="acceptata")
            self.db.update("requests", r["id"], status="acceptat", person_id=person_id,
                           station=off["station"], eta=off["eta"])
            self.db.update("persons", person_id, status="in_deplasare")
            self.event("acceptat", f"{name} a acceptat trenul {r['train']} – schimb în "
                                   f"{station_name(off['station'])} la {_hm(off['eta'])}")
            try:
                self.personal.push_comanda({"tren": r["train"], "id_personal": person_id, "rol": r["role"],
                                            "statie": off["station"], "ora": _iso(off["eta"])})
            except Exception:
                log.exception("Trimiterea comenzii a eșuat")
            return {"ok": True}

    def manual_offer(self, request_id: int, person_id: str) -> None:
        with self.lock:
            r = self.db.one("SELECT * FROM requests WHERE id=?", [request_id])
            if not r or r["status"] not in ("cautare", "oferta"):
                raise ValueError("Cererea nu mai așteaptă înlocuitor.")
            pending = self.db.one("SELECT id FROM offers WHERE status='trimisa' AND person_id=?", [person_id])
            if pending:
                raise ValueError("Omul are deja o ofertă în așteptare.")
            p = self.db.one("SELECT * FROM persons WHERE id=?", [person_id])
            if not p or p["status"] != "disponibil" or p["role"] != r["role"]:
                raise ValueError("Persoana nu este disponibilă pentru acest rol.")
            for o in self.db.q("SELECT id FROM offers WHERE request_id=? AND status='trimisa'", [request_id]):
                self.db.update("offers", o["id"], status="anulata")
            pj = self.db.one("SELECT * FROM pontaj WHERE id=?", [r["pontaj_id"]])
            tt, lv = self.timetables[r["train"]], self.live[r["train"]]
            points = matching.handover_points(self.cfg, tt, lv, self.program_end(pj))
            for hp in points:  # la ofertă manuală acceptăm și sosirea la limită
                hp.urgent = True
            cands = matching.rank(self.cfg, self.clock.now(), points, [p])
            if not cands:
                raise ValueError("Persoana e în afara razei de căutare.")
            self.make_offer(r, cands[0])

    def cancel(self, request_id: int) -> None:
        with self.lock:
            r = self.db.one("SELECT * FROM requests WHERE id=?", [request_id])
            if r and r["status"] in ("cautare", "oferta", "acceptat"):
                self._cancel_request(r, "anulat de dispecer")
                self.event("info", f"Cererea #{request_id} (tren {r['train']}) anulată de dispecer")

    def set_available(self, person_id: str, available: bool) -> None:
        with self.lock:
            p = self.db.one("SELECT * FROM persons WHERE id=?", [person_id])
            if p["status"] in ("pe_tren", "in_deplasare"):
                raise ValueError("Nu poți schimba starea cât ești comandat pe tren.")
            if p["status"] == "odihna" and available:
                raise ValueError(f"Ești în odihnă până la {_hm(p['status_until'])}.")
            self.db.update("persons", person_id, status="disponibil" if available else "indisponibil")

    # ---------------------------------------------------------- simulator
    def _simulate_answers(self, now: float) -> None:
        """Oamenii care nu au aplicația deschisă răspund singuri (80% acceptă) – doar în demo."""
        t = time.time()
        for o in self.db.q("SELECT * FROM offers WHERE status='trimisa'"):
            if t - self.online.get(o["person_id"], 0) < 30:
                continue  # răspunde omul real din aplicație
            due = self._auto.setdefault(o["id"], t + self._rnd.uniform(4, 15))
            if t >= due:
                self._auto.pop(o["id"], None)
                try:
                    self.answer(o["id"], o["person_id"], self._rnd.random() < 0.8)
                except ValueError:
                    pass

    # -------------------------------------------------------------- utile
    def _name(self, pid: str) -> str:
        p = self.db.one("SELECT name FROM persons WHERE id=?", [pid])
        return p["name"] if p else pid


def _hm(t: Optional[float]) -> str:
    return time.strftime("%H:%M", time.localtime(t)) if t else "–"


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def _pontaj_export(row: dict, name: str) -> dict:
    hours = ((row["end"] or 0) - row["start"]) / H if row["end"] else None
    return {
        "id": row["id"], "tren": row["train"], "id_personal": row["person_id"], "nume": name,
        "rol": row["role"], "inceput": _iso(row["start"]), "statie_inceput": row["start_station"],
        "sfarsit": _iso(row["end"]) if row["end"] else None, "statie_sfarsit": row["end_station"],
        "ore": round(hours, 2) if hours is not None else None,
        "km_deplasare": row["km_deplasare"], "min_deplasare": row["min_deplasare"], "sursa": row["source"],
    }
