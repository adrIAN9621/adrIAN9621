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
