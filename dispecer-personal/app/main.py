"""Dispecer Personal – server web (FastAPI).

  /            → pagina dispecerului (hartă live, trenuri, ore lucrate, cereri, pontaj)
  /mecanic     → aplicația de telefon pentru mecanici și ajutori (ofertă tip Uber)
"""
from __future__ import annotations

import csv
import io
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import integrations, matching
from .clock import Clock
from .config import Config
from .db import DB
from .engine import H, Engine, _pontaj_export
from .geo import STATIONS, station_name

BASE_DIR = Path(__file__).resolve().parent
STATIC = BASE_DIR / "static"


class Login(BaseModel):
    parola: str = ""
    id: str = ""
    pin: str = ""


class PersonRef(BaseModel):
    person_id: str


class Speed(BaseModel):
    viteza: float


class Avail(BaseModel):
    disponibil: bool


def create_app(cfg: Optional[Config] = None, db_path: Optional[str] = None, clock=None,
               run_engine: bool = True) -> FastAPI:
    cfg = cfg or Config.load()
    if db_path is None:
        data_dir = Path(os.environ.get("DISPECER_DATA", Path.home() / ".dispecer-personal"))
        data_dir.mkdir(parents=True, exist_ok=True)
        # simulatorul pornește de fiecare dată de la zero
        db_path = ":memory:" if cfg.test else str(data_dir / "dispecer.db")
    start = None
    if cfg.sursa == "simulator":
        clock = clock or Clock(cfg.viteza_ceas)
        start = clock.now()
    mers, inforu, personal = integrations.build(cfg, start or time.time())
    if clock is None:
        replay = cfg.sursa in ("fisiere", "cmdpers", "inforu") and cfg.fisiere.get("reluare", True)
        clock = Clock(cfg.viteza_ceas, inforu.start_time()) if replay else Clock(1.0)
    engine = Engine(cfg, DB(db_path), clock, mers, inforu, personal)
    tokens: dict[str, str] = {}

    @asynccontextmanager
    async def lifespan(_app):
        engine.bootstrap()
        th = None
        if run_engine:
            th = threading.Thread(target=engine.run_forever, daemon=True)
            th.start()
        yield
        engine.stop()

    app = FastAPI(title="Dispecer Personal", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.state.engine = engine
    app.state.tokens = tokens
    db = engine.db

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    def who(authorization: str = Header("")) -> str:
        tok = authorization.removeprefix("Bearer ").strip()
        if tok not in tokens:
            raise HTTPException(401, "Autentificare necesară.")
        return tokens[tok]

    def dispecer(u: str = Depends(who)) -> str:
        if u != "dispecer":
            raise HTTPException(403, "Doar pentru dispecer.")
        return u

    def personal_user(u: str = Depends(who)) -> str:
        if u == "dispecer":
            raise HTTPException(403, "Doar pentru mecanici / ajutori.")
        engine.online[u] = time.time()
        return u

    # ------------------------------------------------------------ pagini
    @app.get("/")
    def page_dispecer():
        return FileResponse(STATIC / "dispecer.html")

    @app.get("/mecanic")
    def page_mecanic():
        return FileResponse(STATIC / "mecanic.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ------------------------------------------------------------ login

    @app.post("/api/login")
    def login(body: Login):
        if body.id:
            from .comenzi_xlsx import id_persoana
            text = body.id.strip()
            # ID-ul, numărul matricol sau numele (cu/fără diacritice, oricum scris)
            p = (db.one("SELECT * FROM persons WHERE id = ?", [text.upper()])
                 or db.one("SELECT * FROM persons WHERE id = ?", [id_persoana(text)])
                 or (db.one("SELECT * FROM persons WHERE UPPER(marca) = ?", [text.upper()]) if text else None))
            if not p or not secrets.compare_digest(str(p["pin"]), body.pin):
                raise HTTPException(401, "ID sau PIN greșit.")
            user = p["id"]
        else:
            if not secrets.compare_digest(body.parola, cfg.parola_dispecer):
                raise HTTPException(401, "Parolă greșită.")
            user = "dispecer"
        tok = secrets.token_urlsafe(24)
        tokens[tok] = user
        return {"token": tok, "user": user}

    # ------------------------------------------------------- dispecer
    def crew_view(pj: dict, now: float) -> dict:
        end = engine.program_end(pj)
        left = (end - now) / H
        p = db.one("SELECT * FROM persons WHERE id=?", [pj["person_id"]]) or {}
        return {
            "pontaj_id": pj["id"], "person_id": pj["person_id"], "name": p.get("name"), "phone": p.get("phone"),
            "role": pj["role"], "start": pj["start"], "start_station": station_name(pj["start_station"]),
            "program_end": end, "ore_lucrate": round((now - pj["start"]) / H, 2), "ore_ramase": round(left, 2),
            "nivel": "rosu" if left <= 1 else "galben" if left <= cfg.alerta_inainte_ore else "verde",
        }

    def request_view(r: dict, now: float) -> dict:
        off = db.one("SELECT * FROM offers WHERE request_id=? ORDER BY id DESC", [r["id"]])
        out = {**r, "station_name": station_name(r["station"]) if r["station"] else None,
               "person_name": engine._name(r["person_id"]) if r["person_id"] else None,
               "outgoing": None, "offer": None}
        pj = db.one("SELECT * FROM pontaj WHERE id=?", [r["pontaj_id"]])
        if pj:
            out["outgoing"] = {"name": engine._name(pj["person_id"]), "program_end": engine.program_end(pj)}
        if off and off["status"] == "trimisa":
            out["offer"] = {"person": engine._name(off["person_id"]), "km": off["km"],
                            "expira_sec": max(0, round(off["expires"] - time.time()))}
        out["incercari"] = db.one("SELECT COUNT(*) n FROM offers WHERE request_id=?", [r["id"]])["n"]
        return out

    @app.get("/api/stare")
    def stare(_: str = Depends(dispecer)):
        with engine.lock:
            now = engine.clock.now()
            trains = []
            for n, tt in engine.timetables.items():
                lv = engine.live.get(n)
                if not lv:
                    continue
                crew = [crew_view(pj, now) for pj in
                        db.q("SELECT * FROM pontaj WHERE train=? AND active=1 ORDER BY role DESC", [n])]
                nxt = tt.stops[lv.last_index + 1].station if lv.last_index + 1 < len(tt.stops) else None
                trains.append({
                    "train": n, "kind": tt.kind, "route": tt.route,
                    "from": station_name(tt.route[0]), "to": station_name(tt.route[-1]),
                    "lat": lv.lat, "lon": lv.lon, "delay": round(lv.delay_min), "status": lv.status,
                    "speed": lv.speed_kmh,
                    "last": station_name(tt.route[lv.last_index]) if lv.last_index >= 0 else None,
                    "next": station_name(nxt) if nxt else None,
                    "eta_final": matching.final_eta(tt, lv), "crew": crew,
                    "nivel": min((c["nivel"] for c in crew), key=["rosu", "galben", "verde"].index, default="gri"),
                })
            reqs = [request_view(r, now) for r in
                    db.q("SELECT * FROM requests WHERE status IN ('cautare','oferta','acceptat') ORDER BY id")]
            counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM persons GROUP BY status")}
            events = db.q("SELECT * FROM events ORDER BY id DESC LIMIT 40")
            return {"now": now, "viteza": engine.clock.speed, "sursa": cfg.sursa, "trains": trains,
                    "requests": reqs, "personal": counts, "events": events,
                    "stations": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in STATIONS.items()
                                 if not k.startswith("@")}}

    @app.get("/api/cereri/{rid}/candidati")
    def candidati(rid: int, _: str = Depends(dispecer)):
        with engine.lock:
            r = db.one("SELECT * FROM requests WHERE id=?", [rid])
            if not r:
                raise HTTPException(404, "Cererea nu există.")
            cs = engine.candidates(r, engine.clock.now())
            return [{**c.__dict__, "station_name": station_name(c.station)} for c in cs[:15]]


    @app.post("/api/cereri/{rid}/ofera")
    def ofera(rid: int, body: PersonRef, _: str = Depends(dispecer)):
        engine.manual_offer(rid, body.person_id)
        return {"ok": True}

    @app.post("/api/cereri/{rid}/anuleaza")
    def anuleaza(rid: int, _: str = Depends(dispecer)):
        engine.cancel(rid)
        return {"ok": True}

    @app.get("/api/personal")
    def lista_personal(_: str = Depends(dispecer)):
        rows = db.q("SELECT id, name, role, phone, home_city, lat, lon, status, status_until, pauza_de_la, marca "
                    "FROM persons ORDER BY role, name")
        for r in rows:
            r["online"] = time.time() - engine.online.get(r["id"], 0) < 30
        return rows

    def pontaj_rows(person: Optional[str] = None) -> list[dict]:
        sql, args = "SELECT * FROM pontaj", []
        if person:
            sql, args = sql + " WHERE person_id=?", [person]
        rows = db.q(sql + " ORDER BY start DESC LIMIT 500", args)
        out = []
        for r in rows:
            e = _pontaj_export(r, engine._name(r["person_id"]))
            e["statie_inceput"] = station_name(r["start_station"])
            e["statie_sfarsit"] = station_name(r["end_station"]) if r["end_station"] else None
            e["activ"] = bool(r["active"])
            if r["active"]:
                e["ore"] = round((engine.clock.now() - r["start"]) / H, 2)
            out.append(e)
        return out

    @app.get("/api/pontaj")
    def pontaj(_: str = Depends(dispecer)):
        return pontaj_rows()

    @app.get("/api/pontaj.csv")
    def pontaj_csv(token: str = ""):
        if tokens.get(token) != "dispecer":
            raise HTTPException(401, "Autentificare necesară.")
        buf = io.StringIO()
        cols = ["tren", "id_personal", "nume", "rol", "inceput", "statie_inceput", "sfarsit",
                "statie_sfarsit", "ore", "km_deplasare", "min_deplasare", "sursa"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", delimiter=";")
        w.writeheader()
        w.writerows(pontaj_rows())
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=pontaj.csv"})


    @app.post("/api/ceas")
    def ceas(body: Speed, _: str = Depends(dispecer)):
        if not cfg.test or cfg.sursa.endswith("_live"):
            raise ValueError("Viteza ceasului se schimbă doar la reluarea unor date înregistrate.")
        engine.clock.set_speed(min(max(body.viteza, 0), 600))
        return {"ok": True}

    # ------------------------------------------------- mecanic / ajutor
    @app.get("/api/eu")
    def eu(pid: str = Depends(personal_user)):
        with engine.lock:
            now = engine.clock.now()
            p = db.one("SELECT id, name, role, home_city, status, status_until, pauza_de_la FROM persons WHERE id=?", [pid])
            off = db.one("SELECT * FROM offers WHERE person_id=? AND status='trimisa' ORDER BY id DESC", [pid])
            oferta = None
            if off:
                r = db.one("SELECT * FROM requests WHERE id=?", [off["request_id"]])
                tt, lv = engine.timetables.get(r["train"]), engine.live.get(r["train"])
                oferta = {"id": off["id"], "train": r["train"], "station": station_name(off["station"]),
                          "eta": off["eta"], "km": off["km"], "travel_min": off["travel_min"],
                          "plecare_acasa": off["eta"] - (off["travel_min"] + 5) * 60,
                          "expira_sec": max(0, round(off["expires"] - time.time())),
                          "dest": station_name(tt.route[-1]) if tt else None,
                          "delay": round(lv.delay_min) if lv else None}
            comanda = None
            acc = db.one("SELECT r.*, o.km, o.travel_min FROM requests r JOIN offers o ON o.request_id=r.id "
                         "AND o.status='acceptata' WHERE r.person_id=? AND r.status='acceptat'", [pid])
            if acc:
                lv = engine.live.get(acc["train"])
                tt = engine.timetables.get(acc["train"])
                eta = tt.stops[tt.index(acc["station"])].arr + lv.delay_min * 60 if tt and lv else acc["eta"]
                comanda = {"train": acc["train"], "station": station_name(acc["station"]), "eta": eta,
                           "km": acc["km"], "plecare_acasa": eta - (acc["travel_min"] + 5) * 60,
                           "pozitie": {"lat": lv.lat, "lon": lv.lon} if lv else None}
            tura = None
            pj = db.one("SELECT * FROM pontaj WHERE person_id=? AND active=1", [pid])
            if pj:
                tura = crew_view(pj, now)
                tura["train"] = pj["train"]
                lv = engine.live.get(pj["train"])
                tt = engine.timetables.get(pj["train"])
                if lv and tt:
                    tura["next"] = station_name(tt.route[lv.last_index + 1]) if lv.last_index + 1 < len(tt.route) else None
                    tura["delay"] = round(lv.delay_min)
                    tura["dest"] = station_name(tt.route[-1])
                    tura["schimb"] = None
                    rq = db.one("SELECT * FROM requests WHERE pontaj_id=? AND status IN ('oferta','acceptat')", [pj["id"]])
                    if rq and rq["status"] == "acceptat":
                        tura["schimb"] = {"station": station_name(rq["station"]), "eta": rq["eta"],
                                          "name": engine._name(rq["person_id"])}
            return {"now": now, "eu": p, "oferta": oferta, "comanda": comanda, "tura": tura,
                    "pontaj": pontaj_rows(pid)[:20]}


    @app.post("/api/eu/disponibil")
    def disponibil(body: Avail, pid: str = Depends(personal_user)):
        engine.set_available(pid, body.disponibil)
        return {"ok": True}

    @app.post("/api/oferte/{oid}/{actiune}")
    def raspuns(oid: int, actiune: str, pid: str = Depends(personal_user)):
        if actiune not in ("accept", "refuz"):
            raise HTTPException(404)
        return engine.answer(oid, pid, actiune == "accept")

    return app

