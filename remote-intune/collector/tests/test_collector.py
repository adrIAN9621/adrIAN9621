"""Teste pentru colectorul RustDesk (pytest + FastAPI TestClient)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Permite importul pachetului `collector` când testele rulează din orice director.
_ROOT = Path(__file__).resolve().parents[2]  # .../remote-intune
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from collector.app import SESSION_COOKIE, create_app  # noqa: E402
from collector.config import Config  # noqa: E402
from collector.crypto import PasswordCipher, hash_password, verify_password  # noqa: E402
from collector.db import Database  # noqa: E402

INGEST_TOKEN = "token-de-test-foarte-secret"
ENC_SECRET = "secret-de-criptare-de-test-123456"


@pytest.fixture()
def ctx(tmp_path):
    cfg = Config(
        certfile="",
        keyfile="",
        allow_insecure=True,
        db=str(tmp_path / "test.db"),
        ingest_token=INGEST_TOKEN,
        enc_secret=ENC_SECRET,
        session_ttl=3600,
        login_max_fails=5,
        login_lockout_seconds=900,
        max_body_bytes=4096,
    )
    db = Database(cfg.db_path)
    app = create_app(cfg, db=db)
    client = TestClient(app)
    yield client, db, cfg
    db.close()


def _auth_headers():
    return {"Authorization": f"Bearer {INGEST_TOKEN}"}


def _register_body(device_id="123456789", password="parolaX", hostname="LAPTOP-01"):
    return {
        "id": device_id,
        "password": password,
        "hostname": hostname,
        "server": "rustdesk.carpatica.local",
        "user": "DOMENIU\\ion.pop",
        "reported": "2026-10-09T10:00:00",
    }


# --------------------------------------------------------------------------- #
# Înregistrare
# --------------------------------------------------------------------------- #
def test_register_upsert(ctx):
    client, db, _ = ctx
    r = client.post("/api/register", json=_register_body(), headers=_auth_headers())
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    row = db.get_device("123456789")
    assert row is not None
    first_seen = row["first_seen"]
    assert row["hostname"] == "LAPTOP-01"

    # Al doilea raport: actualizează hostname/parolă, păstrează first_seen.
    r2 = client.post(
        "/api/register",
        json=_register_body(hostname="LAPTOP-01-REDENUMIT", password="parolaNoua"),
        headers=_auth_headers(),
    )
    assert r2.status_code == 200
    row2 = db.get_device("123456789")
    assert row2["hostname"] == "LAPTOP-01-REDENUMIT"
    assert row2["first_seen"] == first_seen  # păstrat
    # Parola e criptată în repaus (nu în clar).
    assert "parolaNoua" not in row2["enc_password"]
    cipher = PasswordCipher(ENC_SECRET)
    assert cipher.decrypt(row2["enc_password"]) == "parolaNoua"


def test_register_bad_token(ctx):
    client, db, _ = ctx
    r = client.post(
        "/api/register",
        json=_register_body(),
        headers={"Authorization": "Bearer gresit"},
    )
    assert r.status_code == 401
    assert db.get_device("123456789") is None

    # Fără antet deloc.
    r2 = client.post("/api/register", json=_register_body())
    assert r2.status_code == 401


def test_register_non_digit_id(ctx):
    client, db, _ = ctx
    r = client.post(
        "/api/register", json=_register_body(device_id="12ab56789"), headers=_auth_headers()
    )
    assert r.status_code == 422
    # ID prea scurt / prea lung
    assert client.post(
        "/api/register", json=_register_body(device_id="12345"), headers=_auth_headers()
    ).status_code == 422
    assert client.post(
        "/api/register", json=_register_body(device_id="123456789012"), headers=_auth_headers()
    ).status_code == 422


def test_register_oversized_body(ctx):
    client, _, _ = ctx
    big = _register_body(password="x" * 9000)
    r = client.post("/api/register", json=big, headers=_auth_headers())
    assert r.status_code == 413


# --------------------------------------------------------------------------- #
# Utilizatori / autentificare / blocare
# --------------------------------------------------------------------------- #
def _add_user(db, username="tehnician", password="parola-tehnician"):
    h = hash_password(password, iterations=50_000)  # mai puține iterații pentru viteza testelor
    db.add_user(username, h["salt"], h["hash"], h["iterations"])


def test_adduser_and_login(ctx):
    client, db, _ = ctx
    _add_user(db)
    r = client.post(
        "/login",
        data={"username": "tehnician", "password": "parola-tehnician"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert SESSION_COOKIE in r.cookies or any(
        c for c in r.headers.get_list("set-cookie") if SESSION_COOKIE in c
    )


def test_login_wrong_password(ctx):
    client, db, _ = ctx
    _add_user(db)
    r = client.post(
        "/login",
        data={"username": "tehnician", "password": "gresit"},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_login_lockout(ctx):
    client, db, _ = ctx
    _add_user(db)
    for _ in range(5):
        client.post(
            "/login",
            data={"username": "tehnician", "password": "gresit"},
            follow_redirects=False,
        )
    # A 6-a încercare, chiar cu parola corectă, trebuie blocată (429).
    r = client.post(
        "/login",
        data={"username": "tehnician", "password": "parola-tehnician"},
        follow_redirects=False,
    )
    assert r.status_code == 429


def _login(client, db):
    _add_user(db)
    r = client.post(
        "/login",
        data={"username": "tehnician", "password": "parola-tehnician"},
        follow_redirects=False,
    )
    assert r.status_code == 303


# --------------------------------------------------------------------------- #
# Listare și endpoint de parolă
# --------------------------------------------------------------------------- #
def test_bulk_list_has_no_plaintext_password(ctx):
    client, db, _ = ctx
    client.post("/api/register", json=_register_body(password="parolaSECRETA"), headers=_auth_headers())
    _login(client, db)
    r = client.get("/api/devices")
    assert r.status_code == 200
    body = r.text
    assert "parolaSECRETA" not in body
    data = r.json()
    assert len(data["devices"]) == 1
    dev = data["devices"][0]
    assert "password" not in dev
    assert dev["id_formatat"] == "123 456 789"


def test_password_endpoint_requires_auth(ctx):
    client, db, _ = ctx
    client.post("/api/register", json=_register_body(), headers=_auth_headers())
    # Fără sesiune:
    r = client.get("/api/devices/123456789/password")
    assert r.status_code == 401


def test_password_endpoint_decrypts_and_audits(ctx):
    client, db, _ = ctx
    client.post("/api/register", json=_register_body(password="parolaSECRETA"), headers=_auth_headers())
    _login(client, db)
    assert len(db.list_audit()) == 0
    r = client.get("/api/devices/123456789/password")
    assert r.status_code == 200
    assert r.json()["password"] == "parolaSECRETA"
    # S-a scris o linie de audit.
    audit = db.list_audit()
    assert len(audit) == 1
    assert audit[0]["username"] == "tehnician"
    assert audit[0]["device_id"] == "123456789"
    assert audit[0]["ip"]  # IP consemnat


# --------------------------------------------------------------------------- #
# Criptare / PBKDF2
# --------------------------------------------------------------------------- #
def test_encryption_round_trip():
    cipher = PasswordCipher(ENC_SECRET)
    for pw in ["", "simplu", "cu diacritice șțăîâ", "x" * 500, "p@$$ 123"]:
        token = cipher.encrypt(pw)
        assert token != pw
        assert cipher.decrypt(token) == pw
    # Un secret diferit nu poate decripta.
    other = PasswordCipher("alt-secret-complet-diferit-9999")
    with pytest.raises(ValueError):
        other.decrypt(cipher.encrypt("test"))


def test_pbkdf2_verify():
    h = hash_password("parola-mea", iterations=50_000)
    assert h["iterations"] == 50_000
    assert verify_password("parola-mea", h["salt"], h["hash"], h["iterations"]) is True
    assert verify_password("gresit", h["salt"], h["hash"], h["iterations"]) is False


def test_security_headers_present(ctx):
    client, _, _ = ctx
    r = client.get("/")
    assert "default-src 'self'" in r.headers.get("content-security-policy", "")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
