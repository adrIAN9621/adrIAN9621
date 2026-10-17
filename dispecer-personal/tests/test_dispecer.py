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
    # după prima tură: pauză de 2–6 h în care poate lua a doua tură
    assert eng.db.one("SELECT status FROM persons WHERE id=?", [old["person_id"]])["status"] == "pauza"


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


# ------------------------------------------------- date reale din fișiere
def test_file_source_replay_is_read_only(tmp_path, monkeypatch):
    import json
    import sys
    import urllib.request
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrumente"))
    from exemplu_din_simulator import export
    from app.integrations.fisiere import FileSource

    start = float(int(T0))
    folder = export(tmp_path / "date", start=start, hours=10, step_min=5)

    def no_network(*a, **k):
        raise AssertionError("modul fișiere nu are voie să facă cereri în rețea")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)

    src = FileSource(folder, replay=True)
    assert not src.warnings
    clock = ManualClock(src.start_time())
    eng = Engine(Config(sursa="fisiere"), DB(), clock, src, src, src)
    eng.online = {p.id: time.time() for p in src.people()}
    eng.bootstrap()
    assert len(eng.db.q("SELECT * FROM pontaj WHERE active=1")) == 16
    off = eng.db.one("SELECT * FROM offers WHERE status='trimisa' ORDER BY id")
    assert off, "pe datele înregistrate trebuie să apară cereri de înlocuire"
    eng.answer(off["id"], off["person_id"], True)
    for _ in range(60):
        clock.advance(5 * 60)
        eng.tick()
    assert eng.db.one("SELECT status FROM requests WHERE id=?", [off["request_id"]])["status"] == "finalizat"
    out = folder / "iesire"
    comenzi = [json.loads(x) for x in (out / "comenzi_propuse.jsonl").read_text("utf-8").splitlines()]
    assert comenzi[0]["id_personal"] == off["person_id"]
    assert (out / "pontaj_calculat.jsonl").read_text("utf-8").strip()


def test_http_read_only_blocks_writes():
    from app.integrations import ReadOnly

    class Boom:
        def push_pontaj(self, e): raise AssertionError("scriere în producție")
        def push_comanda(self, c): raise AssertionError("scriere în producție")
    ro = ReadOnly(Boom())
    ro.push_pontaj({})
    ro.push_comanda({})


# --------------------------------------------- poziții CmdPers (laptop_proxy)
def _cmdpers_folder(tmp_path):
    import json
    from datetime import datetime
    from app.geo import STATIONS
    from app.integrations.simulator import Simulator

    d = tmp_path / "cmdpers"
    (d / "locatii").mkdir(parents=True)
    sim = Simulator(T0)
    (d / "personal.json").write_text(json.dumps([
        {"id": p.id, "nume": p.name, "rol": p.role, "lat": p.lat, "lon": p.lon, "localitate": p.home_city}
        for p in sim.people()]), encoding="utf-8")
    iso = lambda t: datetime.fromtimestamp(t).isoformat()
    # echipajul a luat trenul cu 10 h înainte, în București Nord
    (d / "echipaje.json").write_text(json.dumps([
        {"tren": "50001", "id_personal": "M001", "rol": "mecanic", "inceput": iso(T0 - 10 * H), "statie": "București Nord"},
        {"tren": "50001", "id_personal": "A001", "rol": "ajutor", "inceput": iso(T0 - 10 * H), "statie": "București Nord"},
    ]), encoding="utf-8")
    route = ["BN", "PV", "CP", "PR", "BV", "SG"]
    legs = []
    t = T0
    for a, b in zip(route, route[1:]):
        _, la, lo = STATIONS[a]
        _, lb, lob = STATIONS[b]
        dur = 50 * 60
        legs.append((t, t + dur, la, lo, lb, lob))
        t += dur
    k = 0
    for t0, t1, la, lo, lb, lob in legs:
        for s in range(0, int(t1 - t0), 120):
            f = s / (t1 - t0)
            ts = t0 + s
            item = {"LocomotiveNumber": "91530401234", "Lat": str(la + (lb - la) * f), "Lng": lo + (lob - lo) * f,
                    "Timestamp": iso(ts), "Source": "GPS", "TrainInfo": [{"TrainNumber": "50001"}]}
            other = {"LocomotiveNumber": "X", "Lat": 0, "Lng": 0, "TrainInfo": []}  # fără tren / fără GPS
            (d / "locatii" / f"{k:06d}.json").write_text(json.dumps(
                {"ora": iso(ts), "date": {"data": [item, other]}}), encoding="utf-8")
            k += 1
    return d


def test_cmdpers_positions_drive_handover_and_pontaj(tmp_path):
    from app.integrations.locatii import LocatiiSource

    folder = _cmdpers_folder(tmp_path)
    src = LocatiiSource(folder, replay=True)
    clock = ManualClock(src.start_time() + 20 * 60)
    eng = Engine(Config(sursa="cmdpers"), DB(), clock, src, src, src)
    eng.online = {p.id: time.time() for p in src.people()}
    eng.bootstrap()

    tt, lv = eng.timetables["50001"], eng.live["50001"]
    assert "BN" in lv.passed and lv.status == "in_mers"
    ahead = tt.route[1:-1]
    assert ahead[0] == "PV" and "BV" in ahead and "CR" not in ahead  # doar în direcția de mers

    off = eng.db.one("SELECT * FROM offers WHERE status='trimisa' AND person_id LIKE 'M%'")
    assert off, "cu 2 h rămase din program trebuie căutat mecanic"
    eng.answer(off["id"], off["person_id"], True)
    for _ in range(80):
        clock.advance(120)
        eng.tick()
    req = eng.db.one("SELECT * FROM requests WHERE id=?", [off["request_id"]])
    assert req["status"] == "finalizat"
    old = eng.db.one("SELECT * FROM pontaj WHERE person_id='M001'")
    new = eng.db.one("SELECT * FROM pontaj WHERE person_id=?", [off["person_id"]])
    assert old["active"] == 0 and old["end_station"] == off["station"]
    assert new["start"] == old["end"] and new["start_station"] == off["station"]



# ------------------------------------------- ciclul: tura 1 → pauză 2–6 h → tura 2 → odihnă cât ciclul
def _pj(eng, pid, start, end, station="BV"):
    return eng.db.insert("pontaj", train="X", person_id=pid, role="mecanic", start=start, start_station="BN",
                         end=end, end_station=station, active=0)


def test_cycle_first_shift_gives_pause_then_long_rest():
    eng, clock = make_engine()
    pid = "M030"
    t1 = T0
    a = _pj(eng, pid, t1, t1 + 11 * H)
    eng._dupa_tura(eng.db.one("SELECT * FROM pontaj WHERE id=?", [a]), t1 + 11 * H)
    p = eng.db.one("SELECT * FROM persons WHERE id=?", [pid])
    assert p["status"] == "pauza" and p["pauza_de_la"] == t1 + 11 * H and p["status_until"] == t1 + 17 * H
    # tura 2 începe după 4 h pauză și ține 10 h → odihnă = 11 + 4 + 10 = 25 h
    b = _pj(eng, pid, t1 + 15 * H, t1 + 25 * H)
    eng._dupa_tura(eng.db.one("SELECT * FROM pontaj WHERE id=?", [b]), t1 + 25 * H)
    p = eng.db.one("SELECT * FROM persons WHERE id=?", [pid])
    assert p["status"] == "odihna" and p["status_until"] == t1 + 25 * H + 25 * H


def test_third_shift_is_a_new_cycle_not_a_second():
    eng, _ = make_engine()
    pid = "M029"
    _pj(eng, pid, T0, T0 + 10 * H)
    _pj(eng, pid, T0 + 13 * H, T0 + 20 * H)                 # tura 2 a ciclului
    c = _pj(eng, pid, T0 + 22 * H, T0 + 30 * H)             # (în practică interzis) – nu e „a doua” iar
    eng._dupa_tura(eng.db.one("SELECT * FROM pontaj WHERE id=?", [c]), T0 + 30 * H)
    assert eng.db.one("SELECT status FROM persons WHERE id=?", [pid])["status"] == "pauza"


def test_pause_expired_becomes_normal_rest():
    eng, clock = make_engine()
    pid = "M028"
    eng.db.update("persons", pid, status="pauza", pauza_de_la=T0, status_until=T0 + 6 * H)
    clock.t = T0 + 6 * H + 1
    eng._release_rest(clock.now())
    p = eng.db.one("SELECT * FROM persons WHERE id=?", [pid])
    assert p["status"] == "odihna" and p["status_until"] == T0 + eng.cfg.odihna_ore * H


def test_pause_window_and_location_in_matching():
    cfg = Config()
    live = LivePosition("1", 0, 0, delay_min=0, status="in_mers", last_index=0)
    pts = matching.handover_points(cfg, tt_line(), live, program_end=T0 + 2.5 * H)   # PV la +1 h, BV la +2 h
    near_pv = {"id": "p", "name": "P", "lat": 44.94, "lon": 26.0, "status": "pauza"}
    # pauza a început acum 30 min: la PV (+1 h) ar avea doar 1,5 h pauză, la BV (+2 h) 2,5 h → doar BV e permisă
    r = matching.rank(cfg, T0 - 3 * H, pts, [{**near_pv, "pauza_de_la": T0 - 0.5 * H}])
    assert r and r[0].station == "BV"
    # pauza a început acum 7 h → peste 6 h, nicio stație
    assert not matching.rank(cfg, T0 - 3 * H, pts, [{**near_pv, "pauza_de_la": T0 - 7 * H}])


def test_person_in_pause_is_located_at_handover_station():
    eng, _ = make_engine()
    pid = "M027"
    _pj(eng, pid, T0 - 12 * H, T0 - 1 * H, station="CT")
    eng.db.update("persons", pid, status="pauza", pauza_de_la=T0 - H, status_until=T0 + 5 * H)
    loc = eng._locatie(eng.db.one("SELECT * FROM persons WHERE id=?", [pid]))
    from app.geo import STATIONS
    assert (loc["lat"], loc["lon"]) == STATIONS["CT"][1:]


def test_mechanic_login_by_marca_or_name():
    from app.integrations.base import Person
    app = create_app(Config(), db_path=":memory:", clock=ManualClock(T0), run_engine=False)
    with TestClient(app) as c:
        eng = app.state.engine
        eng.db.insert("persons", id="HOGEA MIHAI-CLAUDIU", name="Hogea Mihai-Claudiu", role="mecanic", phone="",
                      home_city="", lat=45.1, lon=25.7, pin="1234", marca="A1234", status="disponibil")
        for ident in ("A1234", "a1234", "Hogea Mihai - Claudiu", "HOGEA MIHAI-CLAUDIU", "hogea mihai-claudiu"):
            r = c.post("/api/login", json={"id": ident, "pin": "1234"})
            assert r.status_code == 200 and r.json()["user"] == "HOGEA MIHAI-CLAUDIU", ident
        assert c.post("/api/login", json={"id": "A1234", "pin": "0000"}).status_code == 401
