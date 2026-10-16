"""Clientul InfoRU contra unor servere false: login propriu, poartă NetScaler, grilă AJAX."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from app import inforu
from app.cmdpers import LoginEsuat, Refuzat

PAGE = "/CarpaticaFeroviarSA/TrenuriCirculatie_InParcurs"
STATE = {"mode": "form", "hits": [], "gw": None}
SESS = set()

TABLE = """<html><head><title>Trenuri in parcurs</title></head><body>
<table id="t"><tr><th>Tren</th><th>Ultima statie</th><th>Ora</th><th>Intarziere</th></tr>
<tr><td>50421</td><td>Brasov</td><td>19:02</td><td>12</td></tr>
<tr><td>60125</td><td>Buzau</td><td>18:55</td><td>0</td></tr></table></body></html>"""
GRID = """<html><head><title>Trenuri in parcurs</title></head><body><div id="grid"></div>
<input name="__RequestVerificationToken" type="hidden" value="tk">
<script>$("#grid").kendoGrid({dataSource:{transport:{read:{url:"/CarpaticaFeroviarSA/TrenuriCirculatie_InParcurs_Read",type:"POST"}}}});
var x = "/CarpaticaFeroviarSA/Tren_Delete";</script></body></html>"""
LOGIN = """<html><body><form action="/Account/Login?ReturnUrl=%2FCarpaticaFeroviarSA" method="post">
<input type="hidden" name="__RequestVerificationToken" value="tk"><input type="text" name="UserName">
<input type="password" name="Password"><input type="checkbox" name="RememberMe" value="true"></form></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body="", ctype="text/html; charset=utf-8", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in headers:
            self.send_header(k, v)
        b = body.encode()
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _ok(self):
        return any(f"s={s}" in self.headers.get("Cookie", "") for s in SESS)

    def do_GET(self):
        STATE["hits"].append(("GET", self.path))
        p = urlparse(self.path).path
        if STATE["mode"] == "operator":
            if p == "/":
                return self._send(200, '<html><body><a href="/CargoTransVagon/Default.aspx">Cargo Trans Vagon</a>'
                                       '<a href="/Home/SetOtf?otf=CarpaticaFeroviarSA">CarpaticaFeroviarSA</a></body></html>')
            if p == "/Home/SetOtf":
                return self._send(302, headers=[("Set-Cookie", "op=cf; Path=/"), ("Location", "/")])
            if p == PAGE:
                return self._send(404, "nu")
            if p == PAGE + ".aspx":
                ok = "op=cf" in self.headers.get("Cookie", "")
                return self._send(200, TABLE if ok else "<html><body>Alegeti OTF</body></html>")
            if p.startswith("/CargoTransVagon"):
                return self._send(500, "operator greșit")
        if p == PAGE:
            if self._ok():
                return self._send(200, GRID if STATE["mode"] == "grid" else TABLE)
            if STATE["mode"] == "netscaler":
                return self._send(302, headers=[("Location", STATE["gw"] + "/vpn/tmindex.html")])
            if STATE["mode"] == "foreign":
                return self._send(302, headers=[("Location", "http://evil.example/steal")])
            return self._send(302, headers=[("Location", "/Account/Login?ReturnUrl=" + PAGE)])
        if p == "/Account/Login":
            return self._send(200, LOGIN)
        if p == "/vpn/tmindex.html":
            return self._send(200, "<html><body><script src='/vpn/js/login.js'></script></body></html>")
        if p.startswith("/cgi/setclient"):
            return self._send(302, headers=[("Location", PAGE)])
        return self._send(404, "nu")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        f = parse_qs(self.rfile.read(n).decode())
        STATE["hits"].append(("POST", self.path))
        p = urlparse(self.path).path
        if p == "/Account/Login":
            if f.get("UserName") == ["ion"] and f.get("Password") == ["pw"] and f.get("__RequestVerificationToken") == ["tk"]:
                SESS.add("1")
                return self._send(302, headers=[("Set-Cookie", "s=1; Path=/"), ("Location", PAGE)])
            return self._send(200, LOGIN)
        if p == "/cgi/login":
            if f.get("login") == ["ion"] and f.get("passwd") == ["pw"]:
                SESS.add("1")
                return self._send(302, headers=[("Set-Cookie", "s=1; Path=/"), ("Location", "/cgi/setclient?wica")])
            return self._send(302, headers=[("Location", "/vpn/tmindex.html")])
        if p == PAGE + "_Read" and self._ok():
            return self._send(200, json.dumps({"Data": [{"NrTren": "50421", "Statie": "Brasov", "Intarziere": 12}],
                                               "Total": 1}), "application/json")
        return self._send(500, "nu ar fi trebuit")


@pytest.fixture()
def srv():
    STATE.update(mode="form", hits=[])
    SESS.clear()
    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    STATE["gw"] = base
    yield base
    s.shutdown()


def client(base, pw="pw"):
    return inforu.InfoRU("ion", pw, base + PAGE, base, timeout=3)


def test_form_login_and_table(srv):
    cols, rows = client(srv).trenuri()
    assert cols == ["Tren", "Ultima statie", "Ora", "Intarziere"]
    assert rows[0]["Tren"] == "50421" and len(rows) == 2


def test_netscaler_gateway_login(srv):
    STATE["mode"] = "netscaler"
    cols, rows = client(srv).trenuri()
    assert rows and ("POST", "/cgi/login") in STATE["hits"]


def test_kendo_grid_read_but_never_delete(srv):
    STATE["mode"] = "grid"
    cols, rows = client(srv).trenuri()
    assert rows == [{"NrTren": "50421", "Statie": "Brasov", "Intarziere": 12}]
    assert not any("Delete" in p for _, p in STATE["hits"])


def test_wrong_password_single_attempt(srv):
    ir = client(srv, pw="gresit")
    with pytest.raises(LoginEsuat):
        ir.trenuri()
    n = sum(1 for m, p in STATE["hits"] if m == "POST")
    with pytest.raises(LoginEsuat):
        ir.trenuri()
    assert sum(1 for m, p in STATE["hits"] if m == "POST") == n == 1
    assert all("gresit" not in s for s in ir.pasi)


def test_foreign_redirect_and_writes_blocked(srv):
    STATE["mode"] = "foreign"
    with pytest.raises(Refuzat):
        client(srv).trenuri()
    ir = client(srv)
    for path in ("/CarpaticaFeroviarSA/Tren_Delete", "/X/Save", "/X/GetAndUpdate", "/X/Read?delete=1"):
        with pytest.raises(Refuzat):
            ir._raw("POST", srv + path, {})
    with pytest.raises(Refuzat):
        ir._raw("GET", "http://evil.example/x")


def test_explore_report_has_structure_not_data(srv, tmp_path):
    STATE["mode"] = "grid"
    rep = inforu.explore(client(srv), tmp_path).read_text("utf-8")
    assert "TrenuriCirculatie_InParcurs_Read" in rep and "NrTren, Statie, Intarziere" in rep
    assert "Brasov" not in rep and "Tren_Delete" in rep
    assert not any("Delete" in p for _, p in STATE["hits"])


# ------------------------------------------ tabelul real „Trenuri în parcurs”
COLS = ["Tren", "Rang", "Relatia", "Raportat", "Linia", "Fir", "S", "Sosire", "P", "Plecare/Trecere",
        "ONI", "TFO", "Min", "Monitorizare", "Identificator trasa"]


def test_normalize_real_rows():
    r = inforu.normalizeaza(dict(zip(COLS, ["58428015/", "5", "Constanta Port Zona C -Dornesti", "Ramnicu Sarat",
                                            "5", "", "M", "16.10.2026 20:18", "E", "15.10.2026 21:46", "Y", "", "0",
                                            "Monitorizare", "584280"])))
    assert (r["tren"], r["zi"], r["origine"], r["destinatie"]) == ("584280", "15", "Constanta Port Zona C", "Dornesti")
    assert r["sosire_reala"] and not r["plecare_reala"] and r["ora_raportare"] == r["sosire"]
    r = inforu.normalizeaza(dict(zip(COLS, ["68423016/", "6", "Brazi-Bacau", "Valea Seaca Hm", "4", "", "M",
                                            "16.10.2026 23:45", "E", "16.10.2026 23:51", "", "", "528", "", "684230"])))
    assert (r["origine"], r["destinatie"], r["intarziere_min"]) == ("Brazi", "Bacau", 528.0)


def test_station_names_match():
    from app.statii import Statii
    s = Statii()
    assert s.code("Bucuresti Nord") == "BN" and s.code("Brasov Triaj") == "BV"
    assert s.code("Constanta Port Zona C") == "CT" and s.code("Drobeta Tr.Severin") is None


def _inforu_folder(tmp_path):
    from datetime import datetime
    from app.integrations.simulator import Simulator
    T0, H = 1_760_000_000.0, 3600.0
    d = tmp_path / "ir"
    (d / "inforu").mkdir(parents=True)
    sim = Simulator(T0)
    (d / "personal.json").write_text(json.dumps([
        {"id": p.id, "nume": p.name, "rol": p.role, "lat": p.lat, "lon": p.lon} for p in sim.people()]), "utf-8")
    iso = lambda t: datetime.fromtimestamp(t).isoformat()
    fmt = lambda t: datetime.fromtimestamp(t).strftime("%d.%m.%Y %H:%M")
    (d / "echipaje.json").write_text(json.dumps([
        {"tren": "500010", "id_personal": "M001", "rol": "mecanic", "inceput": iso(T0 - 10 * H), "statie": "Bucuresti Nord"},
        {"tren": "500010", "id_personal": "A001", "rol": "ajutor", "inceput": iso(T0 - 10 * H), "statie": "Bucuresti Nord"},
    ]), "utf-8")
    route = ["Bucuresti Nord", "Ploiesti Vest", "Campina", "Predeal", "Brasov", "Sighisoara", "Medias", "Copsa Mica"]
    for k in range(0, 8 * 10):
        t = T0 + k * 300
        st = route[min(k // 10, len(route) - 1)]
        leg_start = T0 + (k // 10) * 3000
        row = dict(zip(COLS, ["50001016/", "5", "Bucuresti Nord-Arad", st, "1", "1", "", "", "M", fmt(leg_start),
                              "", "", "35", "Monitorizare", "500010"]))
        (d / "inforu" / f"{k:05d}.json").write_text(json.dumps({"ora": iso(t), "coloane": COLS, "trenuri": [row]}), "utf-8")
    return d, T0


def test_inforu_source_drives_handover(tmp_path):
    import time as _t
    from app.clock import ManualClock
    from app.config import Config
    from app.db import DB
    from app.engine import Engine
    from app.integrations.inforu_sursa import InfoRUSource

    folder, T0 = _inforu_folder(tmp_path)
    src = InfoRUSource(folder, replay=True)
    clock = ManualClock(T0 + 60)
    eng = Engine(Config(sursa="inforu"), DB(), clock, src, src, src)
    eng.online = {p.id: _t.time() for p in src.people()}
    eng.bootstrap()
    tt, lv = eng.timetables["500010/16"], eng.live["500010/16"]
    assert tt.route[0] == "BN" and tt.route[-1] == "AR" and "BV" in tt.route
    assert lv.delay_min == 35
    clock.advance(3100)  # după Ploiești Vest direcția e spre nord → Pitești / Craiova nu mai sunt „în față”
    eng.tick()
    route = eng.timetables["500010/16"].route
    assert route[0] == "PV" and "BV" in route and "PT" not in route and "CR" not in route
    assert len(eng.db.q("SELECT * FROM pontaj WHERE active=1")) == 2   # echipaje.json „500010” legat de 500010/16
    off = eng.db.one("SELECT * FROM offers WHERE status='trimisa' AND person_id LIKE 'M%'")
    assert off
    eng.answer(off["id"], off["person_id"], True)
    for _ in range(80):
        clock.advance(300)
        eng.tick()
    assert eng.db.one("SELECT status FROM requests WHERE id=?", [off["request_id"]])["status"] == "finalizat"
    assert [c for _, c in src._path("BN", "MD")] == ["PV", "CP", "PR", "BV", "SG"]  # drum învățat
    old = eng.db.one("SELECT * FROM pontaj WHERE person_id='M001'")
    assert old["end_station"] == off["station"] and old["active"] == 0


# ---------------- NetScaler AAA-TM: poarta și pagina cu date pe gazde diferite (ca auth./otf.infofer.ro)
TM = {"hits": [], "gw": "", "otf": ""}


class Gw(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body="", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in headers:
            self.send_header(k, v)
        b = body.encode()
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        TM["hits"].append(("GW GET", self.path))
        if self.path.startswith("/vpn/tmindex.html"):
            return self._send(200, "<html><body><script src='/vpn/js/l.js'></script></body></html>")
        if self.path == "/cgi/tm":
            if "aaa=ok" not in self.headers.get("Cookie", ""):
                return self._send(302, headers=[("Location", "/vpn/tmindex.html")])
            body = (f'<html><body onload="document.forms[0].submit()"><form method="POST" '
                    f'action="{TM["otf"]}/cgi/selfauth"><input type="hidden" name="NSC_TMAS" value="TOKEN123">'
                    f'<input type="hidden" name="NSC_TMAA" value="x"></form></body></html>')
            return self._send(200, body)
        return self._send(404, "nu")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        f = parse_qs(self.rfile.read(n).decode())
        TM["hits"].append(("GW POST", self.path))
        if self.path == "/cgi/login" and f.get("login") == ["ion"] and f.get("passwd") == ["pw"]:
            return self._send(302, headers=[("Set-Cookie", "aaa=ok; Path=/"), ("Location", "/cgi/tm")])
        return self._send(200, "<html>login</html>")


class Otf(Gw):
    def do_GET(self):
        TM["hits"].append(("OTF GET", self.path))
        if self.path == PAGE:
            if "tm=ok" in self.headers.get("Cookie", ""):
                return self._send(200, TABLE)
            return self._send(302, headers=[("Location", TM["gw"] + "/cgi/tm")])
        return self._send(404, "nu")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        f = parse_qs(self.rfile.read(n).decode())
        TM["hits"].append(("OTF POST", self.path))
        if self.path == "/cgi/selfauth" and f.get("NSC_TMAS") == ["TOKEN123"]:
            return self._send(302, headers=[("Set-Cookie", "tm=ok; Path=/"), ("Location", PAGE)])
        return self._send(500, "nu ar fi trebuit")


def test_netscaler_tm_cross_domain_handoff():
    gw = ThreadingHTTPServer(("127.0.0.1", 0), Gw)
    otf = ThreadingHTTPServer(("127.0.0.1", 0), Otf)
    for s in (gw, otf):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    TM["hits"].clear()
    TM["gw"] = f"http://localhost:{gw.server_address[1]}"      # gazde diferite → cookie-uri separate
    TM["otf"] = f"http://127.0.0.1:{otf.server_address[1]}"
    try:
        ir = inforu.InfoRU("ion", "pw", TM["otf"] + PAGE, TM["gw"], timeout=3)
        cols, rows = ir.trenuri()
        assert rows and rows[0]["Tren"] == "50421"
        assert ("OTF POST", "/cgi/selfauth") in TM["hits"]
        assert any("NSC_TMAS" in p for p in ir.pasi) and all("TOKEN123" not in p for p in ir.pasi)
    finally:
        gw.shutdown()
        otf.shutdown()


def test_operator_selected_from_menu_and_aspx_page(srv):
    STATE["mode"] = "operator"
    SESS.add("1")  # deja trecut de poartă
    ir = client(srv)
    ir.logat = True
    import http.cookiejar
    c = http.cookiejar.Cookie(0, "s", "1", None, False, "127.0.0.1", False, False, "/", True, False, None, False,
                              None, None, {})
    ir.jar.set_cookie(c)
    cols, rows = ir.trenuri()
    assert rows and ir.adresa.endswith(".aspx")
    assert ("GET", "/Home/SetOtf?otf=CarpaticaFeroviarSA") in STATE["hits"]
    assert not any("CargoTransVagon" in p for _, p in STATE["hits"])
    assert any("operator ales" in p for p in ir.pasi)
