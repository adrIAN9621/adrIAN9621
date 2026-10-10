import os
import struct
import sys

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import __main__ as cli  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import Config  # noqa: E402
from server.db import Database  # noqa: E402

AGENT_ID = "123456789"
SECRET = "ab" * 32
CODE = "482913"


@pytest.fixture
def env(tmp_path):
    cfg = Config(db_path=str(tmp_path / "t.db"), allow_insecure=True, consent_timeout=0.5,
                 certfile="", keyfile="")
    db = Database(cfg.db_file)
    db.add_user("ion", "parola-secreta", "Ion Popescu")
    app = create_app(cfg, db)
    with TestClient(app) as client:
        yield cfg, db, client


def login(client, user="ion", pw="parola-secreta"):
    return client.post("/api/login", json={"username": user, "password": pw})


def hello(ws, agent_id=AGENT_ID, secret=SECRET, code=CODE):
    ws.send_json({"t": "hello", "agent_id": agent_id, "agent_secret": secret,
                  "hostname": "PC-CONTA-01", "user": "maria", "os": "Windows 11",
                  "version": "1.0", "code": code})
    return ws.receive_json()


def audit_events(db):
    return [r["event"] for r in reversed(db.get_audit(500))]


# --------------------------------------------------------------------------- auth
def test_adduser_cli_and_login_logout(env, monkeypatch, tmp_path):
    cfg, db, client = env
    pw = iter(["altaparola1", "altaparola1"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(pw))
    args = cli.argparse.Namespace(username="vasile", display_name="Vasile Ionescu")
    assert cli.cmd_adduser(cfg, args) == 0
    row = db._one("SELECT * FROM users WHERE username='vasile'")
    assert row["iterations"] >= 200_000 and len(row["salt"]) == 16
    assert row["pw_hash"] != b"altaparola1"

    assert client.get("/api/me").status_code == 401
    assert client.get("/api/agents").status_code == 401
    r = login(client, "vasile", "altaparola1")
    assert r.status_code == 200
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc
    assert client.get("/api/me").json()["display_name"] == "Vasile Ionescu"
    assert client.post("/api/logout").status_code == 200
    client.cookies.clear()
    assert client.get("/api/me").status_code == 401

    assert cli.cmd_deluser(cfg, cli.argparse.Namespace(username="vasile")) == 0
    assert login(client, "vasile", "altaparola1").status_code == 401
    assert "login" in audit_events(db) and "login_failed" in audit_events(db)


def test_security_headers(env):
    _, _, client = env
    r = client.get("/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert client.get("/static/console.js").status_code == 200


def test_login_rate_limit(env):
    _, _, client = env
    for _ in range(5):
        assert login(client, pw="gresit").status_code == 401
    r = login(client)  # chiar și parola corectă e blocată
    assert r.status_code == 429
    assert "Prea multe" in r.json()["error"]


def test_tech_ws_requires_auth(env):
    _, _, client = env
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/tech") as ws:
            ws.receive_json()


# --------------------------------------------------------------------------- agent
def test_agent_tofu(env):
    _, db, client = env
    with client.websocket_connect("/ws/agent") as a:
        assert hello(a) == {"t": "welcome"}
        a.send_json({"t": "ping"})
        assert a.receive_json() == {"t": "pong"}
    with client.websocket_connect("/ws/agent") as a:
        r = hello(a, secret="cd" * 32)
        assert r["t"] == "error"
        with pytest.raises(WebSocketDisconnect):
            a.receive_json()
    with client.websocket_connect("/ws/agent") as a:  # secretul original merge în continuare
        assert hello(a) == {"t": "welcome"}
    assert "agent_rejected" in audit_events(db)
    assert login(client).status_code == 200
    agents = client.get("/api/agents").json()
    assert agents[0]["agent_id"] == AGENT_ID and agents[0]["hostname"] == "PC-CONTA-01"


# --------------------------------------------------------------------------- flux complet
def frame(seq=1, x=0, y=64, w=64, h=64, sw=1280, sh=720, payload=b"\xff\xd8JPEGDATA\xff\xd9"):
    return struct.pack("<BIHHHHHH", 1, seq, x, y, w, h, sw, sh) + payload


def test_full_flow(env):
    _, db, client = env
    assert login(client).status_code == 200
    with client.websocket_connect("/ws/agent") as a:
        assert hello(a)["t"] == "welcome"
        with client.websocket_connect("/ws/tech") as t:
            # ID inexistent
            t.send_json({"t": "connect", "agent_id": "999999999", "code": CODE})
            assert t.receive_json()["t"] == "error"
            # cod greșit
            t.send_json({"t": "connect", "agent_id": AGENT_ID, "code": "000000"})
            err = t.receive_json()
            assert err["t"] == "error" and "incorect" in err["message"]
            # cod corect
            t.send_json({"t": "connect", "agent_id": "123 456 789", "code": CODE})
            assert t.receive_json()["t"] == "waiting"
            req = a.receive_json()
            assert req["t"] == "request" and req["tech"] == "Ion Popescu"
            sid = req["session_id"]
            mons = [{"index": 0, "width": 1920, "height": 1080, "primary": True}]
            a.send_json({"t": "accept", "session_id": sid, "monitors": mons})
            st = t.receive_json()
            assert st == {"t": "started", "session_id": sid, "hostname": "PC-CONTA-01",
                          "user": "maria", "agent_id": AGENT_ID, "monitors": mons}

            data = frame()
            a.send_bytes(data)
            assert t.receive_bytes() == data
            a.send_json({"t": "frame_done", "seq": 1})
            assert t.receive_json() == {"t": "frame_done", "seq": 1}
            a.send_json({"t": "evil", "x": 1})  # tip necunoscut – ignorat
            t.send_json({"t": "ack", "seq": 1})
            assert a.receive_json() == {"t": "ack", "seq": 1}
            mv = {"t": "mouse", "action": "move", "x": 10, "y": 20}
            t.send_json(mv)
            assert a.receive_json() == mv
            kd = {"t": "key", "action": "down", "code": "KeyA", "key": "a"}
            t.send_json(kd)
            assert a.receive_json() == kd
            t.send_json({"t": "chat", "text": "Bună ziua", "from": "fals"})
            assert a.receive_json() == {"t": "chat", "text": "Bună ziua", "from": "Ion Popescu"}
            a.send_json({"t": "chat", "text": "Mulțumesc", "from": "maria"})
            assert t.receive_json()["text"] == "Mulțumesc"
            # doar vizualizare – input-ul nu mai ajunge la agent
            a.send_json({"t": "view_only", "value": True})
            assert t.receive_json() == {"t": "view_only", "value": True}
            t.send_json(mv)
            t.send_json({"t": "refresh"})
            assert a.receive_json() == {"t": "refresh"}
            # al doilea tehnician nu se poate conecta cu același cod
            t.send_json({"t": "end"})
            assert t.receive_json()["t"] == "ended"
            assert a.receive_json()["t"] == "ended"
            # codul folosit nu mai e valabil
            t.send_json({"t": "connect", "agent_id": AGENT_ID, "code": CODE})
            assert t.receive_json()["t"] == "error"
    ev = audit_events(db)
    for e in ("wrong_code", "connect_request", "accepted", "session_end"):
        assert e in ev, ev
    row = [r for r in db.get_audit() if r["event"] == "session_end"][0]
    assert row["tech"] == "Ion Popescu" and row["agent_id"] == AGENT_ID
    assert row["hostname"] == "PC-CONTA-01" and "tehnician" in row["details"]
    assert client.get("/api/audit").status_code == 200


def test_reject_and_disconnects(env):
    _, db, client = env
    login(client)
    with client.websocket_connect("/ws/agent") as a:
        hello(a)
        with client.websocket_connect("/ws/tech") as t:
            t.send_json({"t": "connect", "agent_id": AGENT_ID, "code": CODE})
            t.receive_json()
            sid = a.receive_json()["session_id"]
            a.send_json({"t": "reject", "session_id": sid})
            m = t.receive_json()
            assert m["t"] == "error" and "refuzat" in m["message"]
            # sesiune nouă; tehnicianul se deconectează → agentul primește ended
            t.send_json({"t": "connect", "agent_id": AGENT_ID, "code": CODE})
            t.receive_json()
            sid = a.receive_json()["session_id"]
            a.send_json({"t": "accept", "session_id": sid, "monitors": []})
            assert t.receive_json()["t"] == "started"
        assert a.receive_json()["t"] == "ended"
        a.send_json({"t": "code", "code": "111222"})
        with client.websocket_connect("/ws/tech") as t:
            t.send_json({"t": "connect", "agent_id": AGENT_ID, "code": "111222"})
            t.receive_json()
            sid = a.receive_json()["session_id"]
            a.send_json({"t": "accept", "session_id": sid, "monitors": []})
            assert t.receive_json()["t"] == "started"
            a.close()
            assert t.receive_json()["t"] == "ended"
    assert "rejected" in audit_events(db)
    assert audit_events(db).count("session_end") == 2


def test_wrong_code_limit(env):
    _, db, client = env
    login(client)
    with client.websocket_connect("/ws/agent") as a:
        hello(a)
        with client.websocket_connect("/ws/tech") as t:
            for _ in range(5):
                t.send_json({"t": "connect", "agent_id": AGENT_ID, "code": "000000"})
                assert "incorect" in t.receive_json()["message"]
            t.send_json({"t": "connect", "agent_id": AGENT_ID, "code": CODE})
            assert "Prea multe" in t.receive_json()["message"]


def test_consent_timeout(env):
    _, db, client = env
    login(client)
    with client.websocket_connect("/ws/agent") as a:
        hello(a)
        with client.websocket_connect("/ws/tech") as t:
            t.send_json({"t": "connect", "agent_id": AGENT_ID, "code": CODE})
            assert t.receive_json()["t"] == "waiting"
            assert a.receive_json()["t"] == "request"
            m = t.receive_json()  # sosește după ~0.5 s
            assert m == {"t": "error", "message": "Utilizatorul nu a răspuns"}
            assert a.receive_json() == {"t": "ended", "reason": "timeout"}
    assert "timeout" in audit_events(db)


def test_gencert(tmp_path):
    cfg = Config(certfile=str(tmp_path / "c.crt"), keyfile=str(tmp_path / "c.key"),
                 db_path=str(tmp_path / "x.db"), hostname="asistenta.local")
    args = cli.argparse.Namespace(hostname=None, san=["10.0.0.5"], days=30, config=None)
    assert cli.cmd_gencert(cfg, args) == 0
    assert cfg.tls_available


def test_refuses_without_tls(tmp_path, capsys):
    cfg = Config(certfile=str(tmp_path / "no.crt"), keyfile=str(tmp_path / "no.key"),
                 db_path=str(tmp_path / "x.db"), allow_insecure=False)
    args = cli.argparse.Namespace(host=None, port=None)
    assert cli.cmd_run(cfg, args) == 2
    assert "gencert" in capsys.readouterr().err
