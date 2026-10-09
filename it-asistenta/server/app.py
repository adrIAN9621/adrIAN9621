"""Aplicația FastAPI: API tehnicieni, WebSocket agent/tehnician, releu sesiuni."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect, WebSocketState

from . import __version__
from .config import PACKAGE_DIR, Config
from .db import Database

log = logging.getLogger("asistenta")

STATIC_DIR = os.path.join(PACKAGE_DIR, "static")
COOKIE_NAME = "cas_session"

AGENT_ID_RE = re.compile(r"^\d{9}$")
SECRET_RE = re.compile(r"^[0-9a-fA-F]{32,256}$")
CODE_RE = re.compile(r"^\d{6}$")

# tipuri de mesaje retransmise în sesiune
A2T_TYPES = {"frame_done", "cursor", "clipboard", "chat", "view_only"}
T2A_TYPES = {"ack", "mouse", "key", "text", "refresh", "monitor", "quality", "clipboard", "chat"}
INPUT_TYPES = {"mouse", "key", "text", "clipboard"}  # blocate când agentul e „doar vizualizare”
FRAME_HEADER_LEN = 17

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _clip(v: Any, n: int = 128) -> str:
    return str(v if v is not None else "")[:n]


# ---------------------------------------------------------------------------
# Conexiuni
# ---------------------------------------------------------------------------
class Peer:
    def __init__(self, ws: WebSocket, ip: str):
        self.ws = ws
        self.ip = ip
        self.lock = asyncio.Lock()
        self.closed = False
        self.session: Optional[RelaySession] = None

    async def send_json(self, obj: dict) -> None:
        if self.closed:
            return
        try:
            async with self.lock:
                await self.ws.send_text(json.dumps(obj, ensure_ascii=False))
        except Exception:
            self.closed = True

    async def send_bytes(self, data: bytes) -> None:
        if self.closed:
            return
        try:
            async with self.lock:
                await self.ws.send_bytes(data)
        except Exception:
            self.closed = True

    async def close(self, code: int = 1000) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.ws.client_state == WebSocketState.CONNECTED:
                await self.ws.close(code)
        except Exception:
            pass


class AgentConn(Peer):
    def __init__(self, ws: WebSocket, ip: str, agent_id: str, info: dict, code: str):
        super().__init__(ws, ip)
        self.agent_id = agent_id
        self.info = info
        self.code: Optional[str] = code
        self.connected_at = time.time()

    @property
    def hostname(self) -> str:
        return self.info.get("hostname", "")


class TechConn(Peer):
    def __init__(self, ws: WebSocket, ip: str, username: str, display_name: str):
        super().__init__(ws, ip)
        self.username = username
        self.display_name = display_name


class RelaySession:
    def __init__(self, agent: AgentConn, tech: TechConn, code: str):
        self.id = secrets.token_urlsafe(12)
        self.agent = agent
        self.tech = tech
        self.code = code
        self.state = "pending"  # pending | active | ended
        self.created = time.time()
        self.started: Optional[float] = None
        self.monitors: list = []
        self.view_only = False
        self.timeout_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# Hub – starea în memorie
# ---------------------------------------------------------------------------
class Hub:
    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.db = db
        self.agents: dict[str, AgentConn] = {}
        self.sessions: dict[str, RelaySession] = {}
        self.code_failures: dict[str, deque] = defaultdict(deque)
        self.login_failures: dict[str, deque] = defaultdict(deque)
        self.login_locked: dict[str, float] = {}

    # ---- limitare autentificare ----
    def login_locked_for(self, ip: str) -> float:
        until = self.login_locked.get(ip, 0)
        rem = until - time.time()
        if rem <= 0:
            self.login_locked.pop(ip, None)
            return 0
        return rem

    def login_failed(self, ip: str) -> None:
        now = time.time()
        q = self.login_failures[ip]
        q.append(now)
        while q and q[0] < now - self.cfg.login_lockout_seconds:
            q.popleft()
        if len(q) >= self.cfg.login_max_failures:
            self.login_locked[ip] = now + self.cfg.login_lockout_seconds
            q.clear()

    def login_ok(self, ip: str) -> None:
        self.login_failures.pop(ip, None)
        self.login_locked.pop(ip, None)

    # ---- limitare coduri greșite ----
    def _code_window(self, agent_id: str) -> deque:
        q = self.code_failures[agent_id]
        cutoff = time.time() - self.cfg.code_window_seconds
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def code_blocked(self, agent_id: str) -> bool:
        return len(self._code_window(agent_id)) >= self.cfg.code_max_failures

    def code_failed(self, agent_id: str) -> None:
        self._code_window(agent_id).append(time.time())

    # ---- sesiuni ----
    async def finish(self, sess: RelaySession, *, event: str, details: str,
                     tech_msg: Optional[dict] = None, agent_msg: Optional[dict] = None) -> None:
        if sess.state == "ended":
            return
        sess.state = "ended"
        self.sessions.pop(sess.id, None)
        task = sess.timeout_task
        if task and task is not asyncio.current_task():
            task.cancel()
        if sess.agent.session is sess:
            sess.agent.session = None
        if sess.tech.session is sess:
            sess.tech.session = None
        if sess.started:
            details = f"{details}; durata {int(time.time() - sess.started)} s"
        await run_in_threadpool(
            self.db.audit, event, sess.tech.display_name, sess.agent.agent_id,
            sess.agent.hostname, sess.tech.ip, details)
        if tech_msg:
            await sess.tech.send_json(tech_msg)
        if agent_msg:
            await sess.agent.send_json(agent_msg)

    async def end_active_or_pending(self, sess: RelaySession, reason: str, *,
                                    notify_tech: bool = True, notify_agent: bool = True) -> None:
        """Încheiere sesiune (activă sau în așteptare) cu `ended`/`error` către părți."""
        ended = {"t": "ended", "reason": reason}
        if sess.state == "pending":
            tech_msg = {"t": "error", "message": reason} if notify_tech else None
            await self.finish(sess, event="session_end", details=f"înainte de accept: {reason}",
                              tech_msg=tech_msg, agent_msg=ended if notify_agent else None)
        else:
            await self.finish(sess, event="session_end", details=reason,
                              tech_msg=ended if notify_tech else None,
                              agent_msg=ended if notify_agent else None)

    async def consent_timeout(self, sess: RelaySession) -> None:
        try:
            await asyncio.sleep(self.cfg.consent_timeout)
        except asyncio.CancelledError:
            return
        if sess.state == "pending":
            await self.finish(sess, event="timeout", details="fără răspuns de la utilizator",
                              tech_msg={"t": "error", "message": "Utilizatorul nu a răspuns"},
                              agent_msg={"t": "ended", "reason": "timeout"})


# ---------------------------------------------------------------------------
# Aplicația
# ---------------------------------------------------------------------------
def create_app(cfg: Config, db: Optional[Database] = None) -> FastAPI:
    db = db or Database(cfg.db_file)
    hub = Hub(cfg, db)
    app = FastAPI(title="Carpatica Asistență IT", version=__version__,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg = cfg
    app.state.db = db
    app.state.hub = hub

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def client_ip(conn) -> str:
        return conn.client.host if conn.client else ""

    def current_user(request: Request) -> Optional[dict]:
        return db.get_session_user(request.cookies.get(COOKIE_NAME))

    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "Neautentificat"}, status_code=401)

    # ------------------------------------------------------------------ HTTP
    @app.get("/")
    async def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"),
                            headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.post("/api/login")
    async def login(request: Request):
        ip = client_ip(request)
        rem = hub.login_locked_for(ip)
        if rem > 0:
            mins = max(1, int(rem // 60) + (1 if rem % 60 else 0))
            return JSONResponse(
                {"error": f"Prea multe încercări eșuate. Reîncercați peste {mins} min."},
                status_code=429)
        try:
            body = await request.json()
            username = _clip(body.get("username"), 64).strip()
            password = str(body.get("password") or "")[:256]
        except Exception:
            return JSONResponse({"error": "Cerere invalidă"}, status_code=400)
        user = await run_in_threadpool(db.verify_user, username, password) if username else None
        if not user:
            hub.login_failed(ip)
            await run_in_threadpool(db.audit, "login_failed", username, "", "", ip, "")
            return JSONResponse({"error": "Utilizator sau parolă incorectă"}, status_code=401)
        hub.login_ok(ip)
        token = await run_in_threadpool(db.create_session, user["username"], cfg.session_ttl, ip)
        await run_in_threadpool(db.audit, "login", user["display_name"], "", "", ip, "")
        resp = JSONResponse({"ok": True, "username": user["username"],
                             "display_name": user["display_name"]})
        resp.set_cookie(COOKIE_NAME, token, max_age=cfg.session_ttl, httponly=True,
                        samesite="strict", secure=request.url.scheme == "https", path="/")
        return resp

    @app.post("/api/logout")
    async def logout(request: Request):
        user = current_user(request)
        db.delete_session(request.cookies.get(COOKIE_NAME))
        if user:
            db.audit("logout", user["display_name"], "", "", client_ip(request), "")
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict",
                           secure=request.url.scheme == "https")
        return resp

    @app.get("/api/me")
    async def me(request: Request):
        user = current_user(request)
        if not user:
            return unauthorized()
        return {"username": user["username"], "display_name": user["display_name"],
                "version": __version__}

    @app.get("/api/agents")
    async def agents(request: Request):
        if not current_user(request):
            return unauthorized()
        rows = db.list_agents()
        out = []
        for r in rows:
            conn = hub.agents.get(r["agent_id"])
            item = {
                "agent_id": r["agent_id"],
                "hostname": r["hostname"] or "",
                "user": r["user"] or "",
                "os": r["os"] or "",
                "version": r["version"] or "",
                "online": conn is not None,
                "in_session": bool(conn and conn.session),
                "last_seen": time.time() if conn else r["last_seen"],
                "ip": r["last_ip"] or "",
            }
            if conn:
                item.update(hostname=conn.info.get("hostname", item["hostname"]),
                            user=conn.info.get("user", item["user"]))
            out.append(item)
        out.sort(key=lambda a: (not a["online"], -(a["last_seen"] or 0)))
        return out

    @app.get("/api/audit")
    async def audit(request: Request, limit: int = 200):
        if not current_user(request):
            return unauthorized()
        limit = max(1, min(int(limit), 2000))
        return db.get_audit(limit)

    # ------------------------------------------------------------- WS helpers
    async def receive(ws: WebSocket) -> Optional[dict]:
        """Returnează {'text':..} / {'bytes':..} sau None la deconectare/mesaj prea mare."""
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            return None
        data = msg.get("bytes")
        if data is None:
            data = msg.get("text")
        if data is not None and len(data) > cfg.max_message_size:
            try:
                await ws.close(1009)
            except Exception:
                pass
            return None
        return msg

    def parse_json(text: Optional[str]) -> Optional[dict]:
        if text is None:
            return None
        try:
            obj = json.loads(text)
        except ValueError:
            return None
        return obj if isinstance(obj, dict) and isinstance(obj.get("t"), str) else None

    # ------------------------------------------------------------- WS agent
    @app.websocket("/ws/agent")
    async def ws_agent(ws: WebSocket):
        await ws.accept()
        ip = client_ip(ws)
        try:
            first = await asyncio.wait_for(receive(ws), timeout=cfg.hello_timeout)
        except (asyncio.TimeoutError, WebSocketDisconnect):
            await _safe_close(ws, 1008)
            return
        hello = parse_json(first.get("text") if first else None)
        if not hello or hello.get("t") != "hello":
            await _reject(ws, "Mesaj hello lipsă sau invalid")
            return
        agent_id = str(hello.get("agent_id", ""))
        secret = str(hello.get("agent_secret", ""))
        code = str(hello.get("code", ""))
        if not AGENT_ID_RE.match(agent_id) or not SECRET_RE.match(secret):
            await _reject(ws, "ID sau secret invalid")
            return
        known = await run_in_threadpool(db.check_agent, agent_id, secret)
        info = {k: _clip(hello.get(k)) for k in ("hostname", "user", "os", "version")}
        if known is False:
            await run_in_threadpool(db.audit, "agent_rejected", "", agent_id,
                                    info["hostname"], ip, "secret diferit de cel înregistrat")
            await _reject(ws, "ID-ul este deja înregistrat pentru alt calculator. "
                              "Contactați departamentul IT.")
            return
        await run_in_threadpool(db.upsert_agent, agent_id, secret, info, ip)
        if known is None:
            await run_in_threadpool(db.audit, "agent_registered", "", agent_id,
                                    info["hostname"], ip, info.get("user", ""))

        agent = AgentConn(ws, ip, agent_id, info, code if CODE_RE.match(code) else None)
        old = hub.agents.get(agent_id)
        hub.agents[agent_id] = agent
        if old is not None:
            if old.session:
                await hub.end_active_or_pending(old.session, "Calculatorul s-a reconectat",
                                                notify_agent=False)
            await old.close(4000)
        await agent.send_json({"t": "welcome"})
        log.info("Agent conectat: %s (%s) de la %s", agent_id, info["hostname"], ip)

        try:
            while True:
                msg = await receive(ws)
                if msg is None:
                    break
                if msg.get("bytes") is not None:
                    data = msg["bytes"]
                    sess = agent.session
                    if (sess and sess.state == "active" and len(data) >= FRAME_HEADER_LEN
                            and data[0] in (1, 2)):
                        await sess.tech.send_bytes(data)
                    continue
                obj = parse_json(msg.get("text"))
                if obj is None:
                    continue
                await handle_agent_msg(agent, obj)
        except WebSocketDisconnect:
            pass
        except Exception:  # pragma: no cover
            log.exception("Eroare conexiune agent %s", agent_id)
        finally:
            agent.closed = True
            if hub.agents.get(agent_id) is agent:
                del hub.agents[agent_id]
            if agent.session:
                await hub.end_active_or_pending(agent.session, "Calculatorul s-a deconectat",
                                                notify_agent=False)
            await run_in_threadpool(db.touch_agent, agent_id)
            log.info("Agent deconectat: %s", agent_id)

    async def handle_agent_msg(agent: AgentConn, obj: dict) -> None:
        t = obj["t"]
        sess = agent.session
        if t == "ping":
            await agent.send_json({"t": "pong"})
            await run_in_threadpool(db.touch_agent, agent.agent_id)
        elif t == "code":
            c = str(obj.get("code", ""))
            agent.code = c if CODE_RE.match(c) else None
        elif t == "accept":
            if sess and sess.state == "pending" and obj.get("session_id") == sess.id:
                mons = obj.get("monitors")
                sess.monitors = mons if isinstance(mons, list) else []
                sess.state = "active"
                sess.started = time.time()
                if sess.timeout_task:
                    sess.timeout_task.cancel()
                if agent.code == sess.code:  # codul folosit nu mai e valabil
                    agent.code = None
                await run_in_threadpool(db.audit, "accepted", sess.tech.display_name,
                                        agent.agent_id, agent.hostname, sess.tech.ip,
                                        f"sesiune {sess.id}")
                await sess.tech.send_json({"t": "started", "session_id": sess.id,
                                           "hostname": agent.hostname,
                                           "user": agent.info.get("user", ""),
                                           "agent_id": agent.agent_id,
                                           "monitors": sess.monitors})
        elif t == "reject":
            if sess and sess.state == "pending" and obj.get("session_id") == sess.id:
                await hub.finish(sess, event="rejected", details="refuzat de utilizator",
                                 tech_msg={"t": "error",
                                           "message": "Utilizatorul a refuzat conexiunea."})
        elif t == "end":
            if sess:
                await hub.end_active_or_pending(sess, "Sesiune încheiată de utilizator")
        elif t in A2T_TYPES:
            if sess and sess.state == "active":
                if t == "view_only":
                    sess.view_only = bool(obj.get("value"))
                await sess.tech.send_json(obj)
        # alte tipuri: ignorate

    # ------------------------------------------------------------- WS tehnician
    @app.websocket("/ws/tech")
    async def ws_tech(ws: WebSocket):
        origin = ws.headers.get("origin")
        if origin:
            host = ws.headers.get("host", "")
            if urlparse(origin).netloc.lower() != host.lower():
                await ws.close(1008)
                return
        user = db.get_session_user(ws.cookies.get(COOKIE_NAME))
        if not user:
            await ws.close(4401)
            return
        await ws.accept()
        tech = TechConn(ws, client_ip(ws), user["username"], user["display_name"])
        try:
            while True:
                msg = await receive(ws)
                if msg is None:
                    break
                if msg.get("bytes") is not None:
                    continue
                obj = parse_json(msg.get("text"))
                if obj is None:
                    continue
                await handle_tech_msg(tech, obj)
        except WebSocketDisconnect:
            pass
        except Exception:  # pragma: no cover
            log.exception("Eroare conexiune tehnician %s", tech.username)
        finally:
            tech.closed = True
            if tech.session:
                await hub.end_active_or_pending(tech.session, "Tehnicianul s-a deconectat",
                                                notify_tech=False)

    async def handle_tech_msg(tech: TechConn, obj: dict) -> None:
        t = obj["t"]
        sess = tech.session
        if t == "ping":
            await tech.send_json({"t": "pong"})
        elif t == "connect":
            await tech_connect(tech, obj)
        elif t == "end":
            if sess:
                await hub.end_active_or_pending(sess, "Sesiune încheiată de tehnician")
        elif t in T2A_TYPES:
            if not sess or sess.state != "active":
                return
            if sess.view_only and t in INPUT_TYPES:
                return
            if t == "chat":
                obj = {"t": "chat", "text": str(obj.get("text", ""))[:4000],
                       "from": tech.display_name}
            await sess.agent.send_json(obj)

    async def tech_connect(tech: TechConn, obj: dict) -> None:
        if tech.session:
            await tech.send_json({"t": "error",
                                  "message": "Există deja o sesiune deschisă în această fereastră."})
            return
        agent_id = re.sub(r"\D", "", str(obj.get("agent_id", "")))[:9]
        code = re.sub(r"\D", "", str(obj.get("code", "")))[:6]
        agent = hub.agents.get(agent_id)
        if not AGENT_ID_RE.match(agent_id) or agent is None:
            await tech.send_json({"t": "error",
                                  "message": "Calculatorul cu acest ID nu este conectat."})
            return
        if hub.code_blocked(agent_id):
            await run_in_threadpool(db.audit, "wrong_code", tech.display_name, agent_id,
                                    agent.hostname, tech.ip, "blocat: prea multe încercări")
            await tech.send_json({"t": "error", "message":
                                  "Prea multe coduri greșite pentru acest calculator. "
                                  "Încercați din nou peste câteva minute."})
            return
        expected = agent.code or ""
        if not (expected and len(code) == 6
                and hmac.compare_digest(code.encode(), expected.encode())):
            hub.code_failed(agent_id)
            await run_in_threadpool(db.audit, "wrong_code", tech.display_name, agent_id,
                                    agent.hostname, tech.ip, "")
            await tech.send_json({"t": "error", "message": "ID sau cod de acces incorect."})
            return
        if agent.session:
            await tech.send_json({"t": "error", "message":
                                  "Calculatorul este deja într-o sesiune de asistență."})
            return
        sess = RelaySession(agent, tech, code)
        agent.session = sess
        tech.session = sess
        hub.sessions[sess.id] = sess
        await run_in_threadpool(db.audit, "connect_request", tech.display_name, agent_id,
                                agent.hostname, tech.ip, f"sesiune {sess.id}")
        await tech.send_json({"t": "waiting", "hostname": agent.hostname})
        await agent.send_json({"t": "request", "session_id": sess.id,
                               "tech": tech.display_name})
        sess.timeout_task = asyncio.create_task(hub.consent_timeout(sess))

    return app


async def _safe_close(ws: WebSocket, code: int = 1000) -> None:
    try:
        await ws.close(code)
    except Exception:
        pass


async def _reject(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_text(json.dumps({"t": "error", "message": message}, ensure_ascii=False))
    except Exception:
        pass
    await _safe_close(ws, 1008)
