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
            if TM.get("meta"):  # exact cum răspunde auth.infofer.ro
                u = f'{TM["otf"]}/cgi/selfauth?code=75b7add9fff33be90'
                return self._send(200, f'<html><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8">'
                                       f'<meta http-equiv="refresh" content="0;URL=\'{u}\'" /></head><body><p>This page '
                                       f'has moved to a <a href="{u}">new location</a></p></body></html>')
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
        if self.path == "/cgi/selfauth?code=75b7add9fff33be90":
            return self._send(302, headers=[("Set-Cookie", "tm=ok; Path=/"), ("Location", PAGE)])
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


@pytest.mark.parametrize("meta", [False, True])
def test_netscaler_tm_cross_domain_handoff(meta):
    TM["meta"] = meta
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
        if meta:
            assert ("OTF GET", "/cgi/selfauth?code=75b7add9fff33be90") in TM["hits"]
            assert all("75b7add9" not in p for p in ir.pasi)
        else:
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


# ------------------------------------------------ import ComenziActive_*.xlsx
def _xlsx(path, rows):
    import zipfile
    from xml.sax.saxutils import escape
    strings, sheet_rows = [], []
    for ri, row in enumerate(rows, 1):
        cells = []
        for ci, v in enumerate(row):
            ref = chr(65 + ci) + str(ri)
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                strings.append(v)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        sheet_rows.append(f'<row r="{ri}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                                      '<sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="ws"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')


def test_import_comenzi_active_xlsx(tmp_path):
    from app import comenzi_xlsx
    f = tmp_path / "ComenziActive_2026_10_17_0043.xlsx"
    _xlsx(f, [["Comenzi active 17.10.2026"],
              ["Marca", "Nume si prenume", "Functie", "Nr. tren", "Data prezentare", "Statie prezentare", "Locomotiva"],
              ["1234", "Popescu Ion", "Mecanic", "584280", 46311.75, "Constanta", "91530401234"],
              ["5678", "Ionescu Dan", "Mecanic ajutor", "58428", "16.10.2026 18:00", "Constanta", "91530401234"],
              ["", "", "", "", "", "", ""]])
    r = comenzi_xlsx.importa(f, tmp_path / "date")
    assert r["randuri"] == 2 and r["echipaje"] == 2
    e = json.loads((tmp_path / "date" / "echipaje.json").read_text("utf-8"))
    assert e[0]["tren"] == "584280" and e[0]["id_personal"] == "1234" and e[0]["rol"] == "mecanic"
    assert e[0]["inceput"].startswith("2026-10-16T18:00")       # număr de serie Excel → dată
    assert e[1]["rol"] == "ajutor" and e[1]["inceput"] == "2026-10-16T18:00:00"


def test_crews_from_xlsx_tracked_on_inforu_train(tmp_path):
    """Echipajul din Comandă (fără personal.json) apare pe trenul InfoRU și i se urmăresc orele."""
    import time as _t
    from datetime import datetime
    from app.clock import ManualClock
    from app.config import Config
    from app.db import DB
    from app.engine import Engine
    from app.integrations.inforu_sursa import InfoRUSource

    folder, T0 = _inforu_folder(tmp_path)
    (folder / "personal.json").unlink()
    (folder / "echipaje.json").write_text(json.dumps([
        {"tren": "50001", "id_personal": "1234", "nume": "Popescu Ion", "rol": "mecanic",
         "inceput": datetime.fromtimestamp(T0 - 10 * 3600).isoformat(), "statie": "Statie Necunoscuta"}]), "utf-8")
    src = InfoRUSource(folder, replay=True)
    eng = Engine(Config(sursa="inforu"), DB(), ManualClock(T0 + 60), src, src, src)
    eng.bootstrap()
    pj = eng.db.one("SELECT * FROM pontaj WHERE person_id='1234' AND active=1")
    assert pj and pj["train"] == "500010/16"
    assert eng.db.one("SELECT name FROM persons WHERE id='1234'")["name"] == "Popescu Ion"
    assert eng.db.q("SELECT * FROM requests")  # 10 h lucrate → caută înlocuitor


def test_import_real_cmdpers_active_orders_format(tmp_path):
    from app import comenzi_xlsx
    f = tmp_path / "ComenziActive_2026_10_17_0043.xlsx"
    _xlsx(f, [["Comenzi Active (2026_10_17_0043)"], ["Locomotiva", "Personal Locomotiva"],
              [4000762, "202610_07721 - Comanda in Derulare | 16/10/2026 18:45 | 68420015 | SBENGHEA IONUT, MUNTEANU ADRIAN MIHAI"],
              [4007023, "202610_09158 - Comanda in Derulare | 16/10/2026 19:00 | 68454016, L88505816 | CARAS COSTICA"
                        "202610_09176 - Comanda Creata | 17/10/2026 07:00  | LUPU COSTEL"],
              [6010883, "202610_09172 - Comanda in Derulare | 16/10/2026 23:00 | L84004116, 58470112, f58470112 | STANGA GEORGE ILIE, TABACITU MARIAN"],
              [4008666, "202610_08034 - Comanda Creata | 14/10/2026 23:30"]])
    r = comenzi_xlsx.importa(f, tmp_path / "d")
    assert r["cmdpers"]["comenzi"] == 5 and r["cmdpers"]["in_derulare"] == 3 and r["cmdpers"]["create"] == 2
    e = json.loads((tmp_path / "d" / "echipaje.json").read_text("utf-8"))
    assert [(x["nume"], x["rol"], x["tren"]) for x in e] == [
        ("Sbenghea Ionut", "mecanic", "684200/15"), ("Munteanu Adrian Mihai", "ajutor", "684200/15"),
        ("Caras Costica", "mecanic", "684540/16|885058/16"),
        ("Stanga George Ilie", "mecanic", "840041/16|584701/12"), ("Tabacitu Marian", "ajutor", "840041/16|584701/12")]
    assert e[0]["inceput"] == "2026-10-16T18:45:00" and e[0]["locomotiva"] == "4000762"


def test_crew_list_of_trains_matches_running_inforu_train(tmp_path):
    from datetime import datetime
    from app.clock import ManualClock
    from app.config import Config
    from app.db import DB
    from app.engine import Engine
    from app.integrations.inforu_sursa import InfoRUSource

    folder, T0 = _inforu_folder(tmp_path)
    (folder / "personal.json").unlink()
    start = datetime.fromtimestamp(T0 - 2 * 3600).isoformat()
    (folder / "echipaje.json").write_text(json.dumps([
        {"tren": "884918/16|500010/16", "id_personal": "Caras Costica", "nume": "Caras Costica", "rol": "mecanic",
         "inceput": start, "statie": ""}]), "utf-8")
    src = InfoRUSource(folder, replay=True)
    eng = Engine(Config(sursa="inforu"), DB(), ManualClock(T0 + 60), src, src, src)
    eng.bootstrap()
    assert eng.db.one("SELECT train FROM pontaj WHERE person_id='Caras Costica'")["train"] == "500010/16"


# ------------------------------------------------ import DatePersonal_*.xls
def test_import_personal_html_xls(tmp_path):
    from app import personal_xls
    from app.comenzi_xlsx import id_persoana
    f = tmp_path / "DatePersonal_20261017125841.xls"
    f.write_text("""<html><body><table>
<tr><td colspan=5>Date personal</td></tr>
<tr><td>Nume si prenume</td><td>Functie</td><td>Localitate domiciliu</td><td>Judet</td><td>Telefon</td></tr>
<tr><td>POPESCU MARIAN - COSMIN</td><td>Mecanic locomotiva</td><td>Brasov</td><td>Brasov</td><td>0722</td></tr>
<tr><td>Ionescu Dan</td><td>Mecanic ajutor</td><td>Com. Predeal, Str. Garii nr. 3</td><td>Brasov</td><td></td></tr>
<tr><td>Vasile Ion</td><td>Sef tura</td><td>Arad</td><td></td><td></td></tr>
<tr><td>Marin Ana</td><td>Mecanic</td><td>Satu Nou de Jos</td><td></td><td></td></tr>
</table></body></html>""", encoding="utf-8")
    r = personal_xls.importa(f, tmp_path / "d")
    assert r["oameni"] == 2 and r["alta_functie"] == 1 and r["fara_loc"] == ["Satu Nou de Jos"]
    p = json.loads((tmp_path / "d" / "personal.json").read_text("utf-8"))
    assert p[0]["id"] == id_persoana("Popescu Marian-Cosmin") and p[0]["rol"] == "mecanic" and p[0]["statie_domiciliu"] == "BV"
    assert p[1]["rol"] == "ajutor" and p[1]["statie_domiciliu"] == "PR"


def test_personal_and_orders_share_ids_so_free_people_become_candidates(tmp_path):
    """Cu personal.json (domiciliu) + echipaje din comenzi: cei liberi sunt propuși ca înlocuitori."""
    import time as _t
    from datetime import datetime
    from app.clock import ManualClock
    from app.comenzi_xlsx import id_persoana
    from app.config import Config
    from app.db import DB
    from app.engine import Engine
    from app.integrations.inforu_sursa import InfoRUSource

    folder, T0 = _inforu_folder(tmp_path)
    (folder / "personal.json").write_text(json.dumps([
        {"id": id_persoana("SBENGHEA IONUT"), "nume": "Sbenghea Ionut", "rol": "mecanic", "lat": 44.44, "lon": 26.07},
        {"id": id_persoana("LIBER PE ACASA"), "nume": "Liber Pe Acasa", "rol": "mecanic", "lat": 45.12, "lon": 25.73},
    ]), "utf-8")
    (folder / "echipaje.json").write_text(json.dumps([
        {"tren": "500010/16", "id_personal": id_persoana("Sbenghea Ionut"), "nume": "Sbenghea Ionut", "rol": "mecanic",
         "inceput": datetime.fromtimestamp(T0 - 10 * 3600).isoformat(), "statie": ""}]), "utf-8")
    src = InfoRUSource(folder, replay=True)
    eng = Engine(Config(sursa="inforu"), DB(), ManualClock(T0 + 60), src, src, src)
    eng.online = {p.id: _t.time() for p in src.people()}
    eng.bootstrap()
    assert eng.db.one("SELECT status FROM persons WHERE id=?", [id_persoana("SBENGHEA IONUT")])["status"] == "pe_tren"
    off = eng.db.one("SELECT * FROM offers WHERE status='trimisa'")
    assert off and off["person_id"] == id_persoana("LIBER PE ACASA")



def test_import_personal_real_columns(tmp_path):
    """Coloanele reale din DatePersonal: Statie apropiata, Concediu, Data Incheiere."""
    from app import personal_xls
    f = tmp_path / "DatePersonal_x.xls"
    f.write_text("""<table><tr><td>NrCrt</td><td>Nume/Prenume</td><td>Nr matricol</td><td>Functie</td>
<td>Statie apropiata</td><td>Telefon</td><td>Data Angajare</td><td>Data Incheiere</td><td>Aria</td><td>Concediu</td></tr>
<tr><td></td><td>MAXIM GHEORGHE</td><td>A1</td><td>MECANIC LOCOMOTIVA</td><td>Brasov</td><td>0722</td><td>01.01.2020</td><td></td><td>Centru</td><td></td></tr>
<tr><td></td><td>SERBAN DANIEL</td><td>A2</td><td>MECANIC AJUTOR</td><td>Predeal</td><td></td><td>01.01.2020</td><td></td><td>Centru</td><td>CO</td></tr>
<tr><td></td><td>ION ELECTRO</td><td>A3</td><td>ELECTROMECANIC</td><td>Arad</td><td></td><td></td><td></td><td></td><td></td></tr>
<tr><td></td><td>PLECAT ION</td><td>A4</td><td>MECANIC LOCOMOTIVA</td><td>Arad</td><td></td><td></td><td>01.09.2026</td><td></td><td></td></tr>
</table>""", encoding="utf-8")
    r = personal_xls.importa(f, tmp_path / "d")
    assert r["coloane"]["localitate"] == 4 and r["oameni"] == 2 and r["plecati"] == 1 and r["alta_functie"] == 1
    p = json.loads((tmp_path / "d" / "personal.json").read_text("utf-8"))
    assert [(x["nume"], x["rol"], x["statie_domiciliu"], x["concediu"]) for x in p] == [
        ("Maxim Gheorghe", "mecanic", "BV", False), ("Serban Daniel", "ajutor", "PR", True)]
