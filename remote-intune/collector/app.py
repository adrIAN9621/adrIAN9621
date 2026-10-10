"""Aplicația FastAPI a colectorului RustDesk – Carpatica Feroviar.

Primește înregistrări de dispozitive de la laptopurile gestionate și oferă o
interfață web pentru tehnicieni (listare, dezvăluire parolă auditată).
"""
from __future__ import annotations

import hmac
import html
import json
import re
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from .config import Config
from .crypto import PasswordCipher, verify_password
from .db import Database
from .state import LoginGuard, RateLimiter, SessionStore

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

SESSION_COOKIE = "cf_collector_session"
_ID_RE = re.compile(r"^\d{9,10}$")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; object-src 'none'; base-uri 'self'; "
        "frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def _client_ip(request: Request) -> str:
    # Serviciu intern, fără proxy de încredere: folosim adresa conexiunii.
    return request.client.host if request.client else "necunoscut"


def _format_id(device_id: str) -> str:
    """Formatează ID-ul RustDesk ca '123 456 789'."""
    d = re.sub(r"\D", "", device_id or "")
    groups = [d[i : i + 3] for i in range(0, len(d), 3)]
    return " ".join(groups) if groups else device_id


def _parse_reported(reported: str | None) -> float:
    if reported:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return time.mktime(time.strptime(reported, fmt))
            except (ValueError, OverflowError):
                continue
    return time.time()


def _render_template(name: str, **ctx: str) -> str:
    text = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    for key, value in ctx.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def create_app(config: Config, *, db: Database | None = None) -> FastAPI:
    app = FastAPI(title="Colector RustDesk – Carpatica Feroviar", docs_url=None, redoc_url=None)

    database = db if db is not None else Database(config.db_path)
    cipher = PasswordCipher(config.enc_secret)
    sessions = SessionStore(config.session_ttl)
    register_limiter = RateLimiter(config.register_rate_limit, config.register_rate_window)
    login_guard = LoginGuard(config.login_max_fails, config.login_lockout_seconds)
    cookie_secure = config.tls_enabled  # Secure doar când rulăm peste TLS

    app.state.config = config
    app.state.db = database
    app.state.cipher = cipher
    app.state.sessions = sessions

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---------------------------------------------------------------- #
    # Middleware: antete de securitate pe fiecare răspuns
    # ---------------------------------------------------------------- #
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    # ---------------------------------------------------------------- #
    # Autentificare sesiune web
    # ---------------------------------------------------------------- #
    def current_user(request: Request) -> str | None:
        return sessions.get(request.cookies.get(SESSION_COOKIE))

    def _set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=config.session_ttl,
            httponly=True,
            samesite="strict",
            secure=cookie_secure,
            path="/",
        )

    # ---------------------------------------------------------------- #
    # UI tehnician
    # ---------------------------------------------------------------- #
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        user = current_user(request)
        if not user:
            return HTMLResponse(_render_template("login.html", error=""))
        return HTMLResponse(
            _render_template("dashboard.html", user=html.escape(user))
        )

    @app.post("/login")
    async def login(request: Request):
        ip = _client_ip(request)
        form = await request.form()
        username = (form.get("username") or "").strip()
        password = form.get("password") or ""

        if login_guard.is_locked(ip):
            return HTMLResponse(
                _render_template(
                    "login.html",
                    error="Prea multe încercări eșuate. Reîncercați mai târziu.",
                ),
                status_code=429,
            )

        row = database.get_user(username)
        ok = False
        if row is not None:
            ok = verify_password(password, row["salt"], row["hash"], row["iterations"])
        else:
            # Verificare falsă, în timp comparabil, pentru a evita enumerarea.
            verify_password(password, "00", "00", 200_000)

        if not ok:
            login_guard.record_fail(ip)
            return HTMLResponse(
                _render_template(
                    "login.html",
                    error="Utilizator sau parolă incorecte.",
                ),
                status_code=401,
            )

        login_guard.reset(ip)
        token = sessions.create(username)
        response = RedirectResponse(url="/", status_code=303)
        _set_session_cookie(response, token)
        return response

    @app.post("/logout")
    async def logout(request: Request):
        sessions.destroy(request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse(url="/", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    # ---------------------------------------------------------------- #
    # API tehnician (necesită sesiune)
    # ---------------------------------------------------------------- #
    @app.get("/api/devices")
    async def api_devices(request: Request):
        if not current_user(request):
            return JSONResponse({"error": "neautentificat"}, status_code=401)
        devices = []
        for row in database.list_devices():
            devices.append(
                {
                    "id": row["id"],
                    "id_formatat": _format_id(row["id"]),
                    "hostname": row["hostname"],
                    "user": row["device_user"],
                    "server": row["server"],
                    "first_seen": row["first_seen"],
                    "last_reported": row["last_reported"],
                }
            )
        return JSONResponse({"devices": devices})

    @app.get("/api/devices/{device_id}/password")
    async def api_device_password(device_id: str, request: Request):
        user = current_user(request)
        if not user:
            return JSONResponse({"error": "neautentificat"}, status_code=401)
        row = database.get_device(device_id)
        if row is None:
            return JSONResponse({"error": "dispozitiv inexistent"}, status_code=404)
        try:
            plaintext = cipher.decrypt(row["enc_password"]) if row["enc_password"] else ""
        except ValueError:
            return JSONResponse(
                {"error": "parola nu a putut fi decriptată"}, status_code=500
            )
        # Jurnalizăm dezvăluirea (cine, ce dispozitiv, când, de la ce IP).
        database.add_audit(user, device_id, row["hostname"], _client_ip(request))
        return JSONResponse({"id": device_id, "password": plaintext})

    @app.get("/api/audit")
    async def api_audit(request: Request):
        if not current_user(request):
            return JSONResponse({"error": "neautentificat"}, status_code=401)
        entries = [
            {
                "username": r["username"],
                "device_id": r["device_id"],
                "id_formatat": _format_id(r["device_id"]),
                "hostname": r["hostname"],
                "ip": r["ip"],
                "ts": r["ts"],
            }
            for r in database.list_audit()
        ]
        return JSONResponse({"audit": entries})

    # ---------------------------------------------------------------- #
    # Ingestie de la laptopuri (token Bearer)
    # ---------------------------------------------------------------- #
    @app.post("/api/register")
    async def api_register(request: Request):
        ip = _client_ip(request)

        # Limitare rată per IP.
        if not register_limiter.allow(ip):
            return JSONResponse(
                {"ok": False, "error": "prea multe cereri"}, status_code=429
            )

        # Autentificare prin token Bearer, comparație în timp constant.
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else ""
        if not token or not hmac.compare_digest(token, config.ingest_token):
            return JSONResponse({"ok": False, "error": "token invalid"}, status_code=401)

        # Respingem corpuri supradimensionate (Content-Length și efectiv).
        max_bytes = config.max_body_bytes
        clen = request.headers.get("content-length")
        if clen is not None:
            try:
                if int(clen) > max_bytes:
                    return JSONResponse(
                        {"ok": False, "error": "corp prea mare"}, status_code=413
                    )
            except ValueError:
                return JSONResponse(
                    {"ok": False, "error": "Content-Length invalid"}, status_code=400
                )
        raw = await request.body()
        if len(raw) > max_bytes:
            return JSONResponse(
                {"ok": False, "error": "corp prea mare"}, status_code=413
            )

        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"ok": False, "error": "JSON invalid"}, status_code=400)
        if not isinstance(data, dict):
            return JSONResponse({"ok": False, "error": "format invalid"}, status_code=400)

        device_id = str(data.get("id") or "").strip()
        if not _ID_RE.match(device_id):
            return JSONResponse(
                {"ok": False, "error": "ID RustDesk invalid (9-10 cifre)"},
                status_code=422,
            )

        password = str(data.get("password") or "")
        hostname = str(data.get("hostname") or "").strip()[:255]
        server = str(data.get("server") or "").strip()[:255]
        device_user = str(data.get("user") or "").strip()[:255]
        last_reported = _parse_reported(str(data.get("reported") or ""))

        enc_password = cipher.encrypt(password)
        database.upsert_device(
            device_id=device_id,
            hostname=hostname,
            enc_password=enc_password,
            device_user=device_user,
            server=server,
            last_reported=last_reported,
        )
        return JSONResponse({"ok": True})

    return app
