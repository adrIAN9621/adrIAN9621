import time

import pytest
from fastapi.testclient import TestClient

from app import matching
from app.clock import ManualClock
from app.config import Config
from app.db import DB
from app.engine import H, Engine
from app.integrations.base import LivePosition, StopTime, Timetable
from app.integrations.simulator import Simulator
from app.main import create_app

T0 = 1_760_000_000.0


def make_engine(cfg=None):
    cfg = cfg or Config()
    clock = ManualClock(T0)
    sim = Simulator(T0)
    eng = Engine(cfg, DB(), clock, sim, sim, sim)
    eng.online = {p.id: time.time() for p in sim.people()}  # fără răspunsuri automate
    eng.bootstrap()
    return eng, clock


# ------------------------------------------------------------------ matching
def tt_line():
    # A(0) -> B -> C -> D(final), opriri la +1h, +2h, +3h
    return Timetable("1", "marfă", [StopTime("BN", None, T0), StopTime("PV", T0 + H, T0 + H),
                                    StopTime("BV", T0 + 2 * H, T0 + 2 * H), StopTime("SG", T0 + 3 * H, None)])


def test_handover_points_only_ahead_and_inside_program():
    cfg = Config()
    live = LivePosition("1", 0, 0, delay_min=0, status="in_mers", last_index=0)
    pts = matching.handover_points(cfg, tt_line(), live, program_end=T0 + 2.5 * H)
    assert [p.station for p in pts] == ["PV", "BV"]          # SG = final, exclus
    pts = matching.handover_points(cfg, tt_line(), live, program_end=T0 + 1.5 * H)
    assert [p.station for p in pts] == ["PV"]


def test_delay_moves_eta_and_urgent_fallback():
    cfg = Config()
    live = LivePosition("1", 0, 0, delay_min=60, status="in_mers", last_index=0)
    pts = matching.handover_points(cfg, tt_line(), live, program_end=T0 + 1.5 * H)
    assert len(pts) == 1 and pts[0].station == "PV" and pts[0].urgent


def test_rank_prefers_nearest_person():
    cfg = Config()
    live = LivePosition("1", 0, 0, delay_min=0, status="in_mers", last_index=0)
    pts = matching.handover_points(cfg, tt_line(), live, program_end=T0 + 2.5 * H)
    people = [
        {"id": "far", "name": "Departe", "lat": 46.77, "lon": 23.59},     # Cluj
        {"id": "bv", "name": "Brașov", "lat": 45.66, "lon": 25.62},      # lângă Brașov
        {"id": "pv", "name": "Ploiești", "lat": 44.95, "lon": 26.01},    # lângă Ploiești
    ]
    ranked = matching.rank(cfg, T0, pts, people)
    assert ranked[0].person_id in ("pv", "bv")
    assert {c.person_id: c.station for c in ranked}["bv"] == "BV"
    assert "far" not in [c.person_id for c in ranked]  # nu ajunge la timp


# -------------------------------------------------------------------- engine
def test_bootstrap_imports_crews_and_raises_alerts():
    eng, _ = make_engine()
    active = eng.db.q("SELECT * FROM pontaj WHERE active=1")
    assert len(active) == 16
    reqs = eng.db.q("SELECT * FROM requests")
    assert reqs, "trenurile plecate de mult trebuie să genereze cereri de înlocuire"
    assert any(r["status"] == "oferta" for r in reqs)


def test_full_flow_accept_handover_and_pontaj():
    eng, clock = make_engine()
    off = eng.db.one("SELECT * FROM offers WHERE status='trimisa' ORDER BY id")
    req = eng.db.one("SELECT * FROM requests WHERE id=?", [off["request_id"]])
    old = eng.db.one("SELECT * FROM pontaj WHERE id=?", [req["pontaj_id"]])

    eng.answer(off["id"], off["person_id"], True)
    assert eng.db.one("SELECT status FROM persons WHERE id=?", [off["person_id"]])["status"] == "in_deplasare"

    # trenul ajunge în stația de schimb
    for _ in range(40):
        clock.advance(15 * 60)
        eng.tick()
        if eng.db.one("SELECT status FROM requests WHERE id=?", [req["id"]])["status"] == "finalizat":
            break
    assert eng.db.one("SELECT status FROM requests WHERE id=?", [req["id"]])["status"] == "finalizat"

    closed = eng.db.one("SELECT * FROM pontaj WHERE id=?", [old["id"]])
    assert closed["active"] == 0 and closed["end_station"] == off["station"]
    assert closed["end"] - closed["start"] <= eng.cfg.program_max_ore * H
    new = eng.db.one("SELECT * FROM pontaj WHERE person_id=? AND active=1", [off["person_id"]])
    assert new["train"] == req["train"] and new["start"] == closed["end"] and new["source"] == "InfoRU"
    assert eng.db.one("SELECT status FROM persons WHERE id=?", [old["person_id"]])["status"] == "odihna"


def test_refuse_goes_to_next_candidate():
    eng, _ = make_engine()
    off = eng.db.one("SELECT * FROM offers WHERE status='trimisa' ORDER BY id")
    eng.answer(off["id"], off["person_id"], False)
    nxt = eng.db.one("SELECT * FROM offers WHERE request_id=? AND status='trimisa'", [off["request_id"]])
    assert nxt and nxt["person_id"] != off["person_id"]


def test_expired_offer_moves_on():
    cfg = Config()
    cfg.oferta_expira_sec = -1
    eng, _ = make_engine(cfg)
    first = eng.db.one("SELECT * FROM offers ORDER BY id")
    eng.tick()
    assert eng.db.one("SELECT status FROM offers WHERE id=?", [first["id"]])["status"] == "expirata"


def test_no_offer_to_unavailable_people():
    eng, _ = make_engine()
    eng.db.x("UPDATE persons SET status='indisponibil' WHERE status='disponibil'")
    eng.db.x("UPDATE offers SET status='refuzata'")
    eng.db.x("UPDATE requests SET status='cautare'")
    eng.tick()
    assert not eng.db.q("SELECT * FROM offers WHERE status='trimisa'")
    assert eng.db.q("SELECT * FROM requests WHERE note='fara_candidati'")


def test_rest_blocks_availability():
    eng, _ = make_engine()
    pid = eng.db.one("SELECT id FROM persons WHERE status='disponibil'")["id"]
    eng.db.update("persons", pid, status="odihna", status_until=T0 + H)
    with pytest.raises(ValueError):
        eng.set_available(pid, True)


# ----------------------------------------------------------------------- API
def test_api_login_and_mecanic_flow():
    app = create_app(Config(), db_path=":memory:", clock=ManualClock(T0), run_engine=False)
    with TestClient(app) as c:
        assert c.post("/api/login", json={"parola": "gresit"}).status_code == 401
        d = c.post("/api/login", json={"parola": "dispecer"}).json()["token"]
        st = c.get("/api/stare", headers={"Authorization": f"Bearer {d}"}).json()
        assert len(st["trains"]) == 8 and st["requests"]

        off = app.state.engine.db.one("SELECT * FROM offers WHERE status='trimisa' ORDER BY id")
        m = c.post("/api/login", json={"id": off["person_id"], "pin": "1234"}).json()["token"]
        h = {"Authorization": f"Bearer {m}"}
        me = c.get("/api/eu", headers=h).json()
        assert me["oferta"]["id"] == off["id"]
        assert c.get("/api/stare", headers=h).status_code == 403
        assert c.post(f"/api/oferte/{off['id']}/accept", headers=h).json()["ok"]
        me = c.get("/api/eu", headers=h).json()
        assert me["comanda"]["train"] and me["oferta"] is None
        assert c.get(f"/api/pontaj.csv?token={d}").text.count("\n") >= 17
