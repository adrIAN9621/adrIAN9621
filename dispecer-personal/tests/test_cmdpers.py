"""Clientul CmdPers contra unui server CmdPers fals (login + CSRF + cookie + căutări)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from app import cmdpers

HITS = []
SESSIONS = set()

LOGIN_PAGE = """<html><head><title>Login</title></head><body><form action="/cmdpers_carpatica/Account/Login" method="post">
<input name="__RequestVerificationToken" type="hidden" value="tok123">
<input name="UserName"><input name="Password" type="password"></form></body></html>"""

ENGINEERS = """<html><head><title>Mecanici</title></head><body>
<a href="/cmdpers_carpatica/LocomotiveLocation/Index">Harta</a>
<a href="/cmdpers_carpatica/Account/LogOff">Ieșire</a>
<a href="/cmdpers_carpatica/LocomotiveEngineer/Delete/5">Șterge</a>
<a href="/cmdpers_carpatica/LocomotiveEngineer/Activities?id=5">Activități</a>
<a href="/cmdpers_carpatica/Comanda/Index?id=5&amp;action=delete">X</a>
<a href="/cmdpers_carpatica/Comanda/Accepta/5">Acceptă</a>
<a href="/cmdpers_carpatica/Notification/MarkRead/7">Citit</a>
<a href="/cmdpers_carpatica/Comanda/Ack%69ons/5" onclick="return confirm('Sigur?')">Gata</a>
<a href="/cmdpers_carpatica/Comanda/Details/9" data-ajax-method="POST">Detalii</a>
<form action="/cmdpers_carpatica/LocomotiveEngineer/Search" method="post"><input name="nume"><input name="data"></form>
<table id="grid"><tr><th>Nume</th><th>Tren</th><th>Început</th></tr>
<tr><td>Popescu Ion</td><td>50421</td><td>16.10.2026 08:00</td></tr></table>
<script>$.post('/cmdpers_carpatica/LocomotiveEngineer/GetActivities', {id: 5});</script>
</body></html>"""

ACTIVE = """<html><head><title>Comenzi active</title></head><body>
<table id="orders"><tr><th>Mecanic</th><th>Functie</th><th>Tren</th><th>Locomotiva</th><th>Ora prezentare</th><th>Statie</th></tr>
<tr><td>Popescu Ion</td><td>MEC</td><td>584280</td><td>91530401234</td><td>16.10.2026 08:00</td><td>Constanta</td></tr>
</table><a href="/cmdpers_carpatica/ActiveOrders/Close/5">Inchide</a></body></html>"""

LOC_PAGE = """<html><head><title>Locatii</title></head><body>
<input name="__RequestVerificationToken" type="hidden" value="tok123"></body></html>"""


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _logged(self):
        c = self.headers.get("Cookie", "")
        return any(f"sess={s}" in c for s in SESSIONS)

    def _send(self, code, body, ctype="text/html; charset=utf-8", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in headers:
            self.send_header(k, v)
        data = body.encode()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        HITS.append(("GET", self.path))
        path = urlparse(self.path).path
        if path.endswith("/Account/Login"):
            return self._send(200, LOGIN_PAGE)
        if not self._logged():
            return self._send(302, "", headers=[("Location", "/cmdpers_carpatica/Account/Login")])
        if "LocomotiveEngineer" in path or path.rstrip("/").endswith("cmdpers_carpatica"):
            return self._send(200, ENGINEERS)
        if path.endswith("/ActiveOrders/Index"):
            return self._send(200, ACTIVE)
        if "LocomotiveLocation" in path:
            return self._send(200, LOC_PAGE)
        return self._send(404, "nu")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(n).decode())
        HITS.append(("POST", self.path))
        if self.path.endswith("/Account/Login"):
            if form.get("UserName") == ["ion"] and form.get("Password") == ["secret"] and form.get("__RequestVerificationToken") == ["tok123"]:
                SESSIONS.add("abc")
                return self._send(302, "", headers=[("Set-Cookie", "sess=abc; Path=/"), ("Location", "/cmdpers_carpatica/")])
            return self._send(200, LOGIN_PAGE)
        if not self._logged():
            return self._send(302, "", headers=[("Location", "/cmdpers_carpatica/Account/Login")])
        if self.path.endswith("/GetLatestLocation"):
            assert form.get("__RequestVerificationToken") == ["tok123"]
            data = [{"LocomotiveNumber": "91530401234", "Lat": "45.66", "Lng": "25.61",
                     "Timestamp": "2026-10-16T19:00:00", "TrainInfo": [{"TrainNumber": "50421"}]}]
            return self._send(200, json.dumps(data), "application/json")
        return self._send(500, "nu ar fi trebuit")


@pytest.fixture()
def server():
    HITS.clear()
    SESSIONS.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_login_falls_back_to_second_server(server):
    cp = cmdpers.CmdPers("ion", "secret", ["http://127.0.0.1:9", server], timeout=3)
    assert cp.login() == server


def test_wrong_password(server):
    with pytest.raises(cmdpers.LoginEsuat):
        cmdpers.CmdPers("ion", "gresit", [server], timeout=3).login()


def test_locations_and_relogin_after_expiry(server):
    cp = cmdpers.CmdPers("ion", "secret", [server], timeout=3)
    items = cp.locations()
    assert items[0]["TrainInfo"][0]["TrainNumber"] == "50421"
    SESSIONS.clear()  # sesiunea expiră pe server
    assert cp.locations()[0]["LocomotiveNumber"] == "91530401234"


def test_write_requests_are_blocked_before_sending(server):
    cp = cmdpers.CmdPers("ion", "secret", [server], timeout=3)
    cp.login()
    for path in ("/LocomotiveEngineer/Save", "/LocomotiveEngineer/Delete", "/Comanda/Create", "/X/SetStatus"):
        with pytest.raises(cmdpers.Refuzat):
            cp.request("POST", path, {"a": 1})
    assert not any(p.endswith(("Save", "Delete", "Create", "SetStatus")) for _, p in HITS)


def test_explore_reports_structure_without_unsafe_links(server, tmp_path):
    cp = cmdpers.CmdPers("ion", "secret", [server], timeout=3)
    cp.login()
    report = cmdpers.explore(cp, tmp_path, pauza=0)
    text = report.read_text("utf-8")
    assert "Nume | Tren | Început" in text and "GetActivities" in text and "LocomotiveEngineer/Search" in text
    assert "Popescu" not in text  # raportul nu conține date personale
    paths = [p for _, p in HITS]
    assert not any("LogOff" in p or "Delete" in p for p in paths)
    assert not any(x in p for p in paths for x in ("delete", "Accepta", "MarkRead", "Comanda/Ack", "Details"))
    assert all(m == "GET" for m, p in HITS if "Login" not in p)
    saved = cmdpers.engineer_tables(cp, tmp_path)
    rows = json.loads(saved[0].read_text("utf-8"))["tabele"][0]["randuri"]
    assert rows[0]["Nume"] == "Popescu Ion"


def test_live_source_reads_cmdpers_and_saves_snapshots(server, tmp_path):
    import time

    from app.clock import ManualClock
    from app.config import Config
    from app.db import DB
    from app.engine import Engine
    from app.integrations.locatii import CmdPersLive

    cp = cmdpers.CmdPers("ion", "secret", [server], timeout=3)
    src = CmdPersLive(tmp_path / "live", cp, interval=0)
    eng = Engine(Config(sursa="cmdpers_live"), DB(), ManualClock(time.time()), src, src, src)
    eng.bootstrap()
    assert "50421" in eng.live and abs(eng.live["50421"].lat - 45.66) < 1e-6
    assert list((tmp_path / "live" / "locatii").glob("*.json"))


@pytest.mark.parametrize("path", [
    "/Comanda/SaveOrder", "/Comanda/GetAndUpdate", "/X/SearchAndDelete", "/Comanda/Accept", "/Order/Assign",
    "/Pontaj/Validate", "/Engineer/Edit/5", "/Comanda/Accept/GetData", "/Order/Assign/List", "/Comanda/GetAndAccept",
    "/Comanda/LoadAndConfirm", "/Comanda/Sav%65", "/Comanda/Accept/../GetData", "/Comanda/GetData?action=delete",
    "/Comanda/GetX%2F..%2FAccept", "/Comanda/GetX;Accept", "/Admin/Account/Login", "/Account/Login?ReturnUrl=x",
    "http://evil.example/cmdpers_carpatica/X/GetData",
])
def test_post_guard_blocks_write_like_paths(path):
    cp = cmdpers.CmdPers("ion", "secret", ["http://10.0.0.11"])
    cp.server = "http://10.0.0.11"
    with pytest.raises(cmdpers.Refuzat):
        cp._verifica("POST", cp._url(path))


@pytest.mark.parametrize("path", ["/Comanda/Accepta/5", "/Comanda/Confirma/5", "/Comanda/Aloca/5", "/Comanda/Asigneaza",
                                  "/Pontaj/Valideaza", "/Comanda/Inchide", "/Comanda/Finalizeaza", "/Raport/Genereaza",
                                  "/Comanda/Trimite", "/X/Sterge", "/X/Adauga", "/X/Salveaza", "/X/Modifica",
                                  "/Notification/MarkRead", "/Account/SignOut", "/Account/Log%4Fff", "/Home/Index?action=delete"])
def test_get_guard_blocks_romanian_and_unsafe_actions(path):
    cp = cmdpers.CmdPers("ion", "secret", ["http://10.0.0.11"])
    cp.server = "http://10.0.0.11"
    with pytest.raises(cmdpers.Refuzat):
        cp._verifica("GET", cp._url(path))


def test_guard_allows_reads_and_only_get_post():
    cp = cmdpers.CmdPers("ion", "secret", ["http://10.0.0.11"])
    cp.server = "http://10.0.0.11"
    for p in ("/LocomotiveLocation/GetLatestLocation", "/LocomotiveEngineer/Search", "/Account/Login"):
        cp._verifica("POST", cp._url(p))
    for p in ("/", "/Home/Index", "/LocomotiveLocation/Index", "/LocomotiveEngineer/Index", "/X/Details/5?id=1"):
        cp._verifica("GET", cp._url(p))
    for m in ("PUT", "DELETE", "PATCH", "HEAD"):
        with pytest.raises(cmdpers.Refuzat):
            cp._verifica(m, cp._url("/X/GetData"))


def test_wrong_password_is_not_retried_and_never_leaks(server):
    cp = cmdpers.CmdPers("ion", "parola-gresita", [server], timeout=3)
    with pytest.raises(cmdpers.LoginEsuat) as e1:
        cp.login()
    n = len(HITS)
    with pytest.raises(cmdpers.LoginEsuat) as e2:
        cp.locations()
    assert len(HITS) == n  # fără încercări noi de logare (contul nu se blochează)
    assert "parola-gresita" not in str(e1.value) + str(e2.value)


def test_active_orders_table(server):
    cp = cmdpers.CmdPers("ion", "secret", [server], timeout=3)
    cols, rows, jurnal = cp.comenzi_active()
    assert cols[:3] == ["Mecanic", "Functie", "Tren"] and rows[0]["Tren"] == "584280"
    assert not any("Close" in p for _, p in HITS)
