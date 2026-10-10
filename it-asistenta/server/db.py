"""Stocare SQLite: tehnicieni, sesiuni web, agenți (TOFU), jurnal de audit."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from typing import Optional

PBKDF2_ITERATIONS = 260_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    salt          BLOB NOT NULL,
    pw_hash       BLOB NOT NULL,
    iterations    INTEGER NOT NULL,
    created       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    created    REAL NOT NULL,
    expires    REAL NOT NULL,
    ip         TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    agent_id    TEXT PRIMARY KEY,
    secret_hash TEXT NOT NULL,
    hostname    TEXT,
    user        TEXT,
    os          TEXT,
    version     TEXT,
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    last_ip     TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    event    TEXT NOT NULL,
    tech     TEXT,
    agent_id TEXT,
    hostname TEXT,
    ip       TEXT,
    details  TEXT
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts);
"""


def hash_password(password: str, salt: Optional[bytes] = None,
                  iterations: int = PBKDF2_ITERATIONS) -> tuple[bytes, bytes, int]:
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return salt, h, iterations


def sha256_hex(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
        # hash fictiv pentru a egaliza timpul când utilizatorul nu există
        self._dummy = hash_password("x" * 12)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute(sql, params).fetchone()
        return dict(r) if r else None

    # ---------------- utilizatori ----------------
    def add_user(self, username: str, password: str, display_name: Optional[str] = None) -> None:
        salt, h, it = hash_password(password)
        self._exec(
            "INSERT INTO users(username, display_name, salt, pw_hash, iterations, created) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET "
            "display_name=excluded.display_name, salt=excluded.salt, pw_hash=excluded.pw_hash, "
            "iterations=excluded.iterations",
            (username, display_name or username, salt, h, it, time.time()),
        )

    def delete_user(self, username: str) -> bool:
        cur = self._exec("DELETE FROM users WHERE username=?", (username,))
        self._exec("DELETE FROM web_sessions WHERE username=?", (username,))
        return cur.rowcount > 0

    def list_users(self) -> list[dict]:
        return self._all("SELECT username, display_name, created FROM users ORDER BY username")

    def get_user(self, username: str) -> Optional[dict]:
        return self._one("SELECT username, display_name FROM users WHERE username=?", (username,))

    def verify_user(self, username: str, password: str) -> Optional[dict]:
        row = self._one("SELECT * FROM users WHERE username=?", (username,))
        if row is None:
            salt, ref, it = self._dummy
            hash_password(password, salt, it)
            return None
        _, h, _ = hash_password(password, row["salt"], row["iterations"])
        if hmac.compare_digest(h, row["pw_hash"]):
            return {"username": row["username"], "display_name": row["display_name"]}
        return None

    # ---------------- sesiuni web ----------------
    def create_session(self, username: str, ttl: int, ip: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        self._exec("DELETE FROM web_sessions WHERE expires < ?", (now,))
        self._exec("INSERT INTO web_sessions VALUES(?,?,?,?,?)",
                   (sha256_hex(token), username, now, now + ttl, ip))
        return token

    def get_session_user(self, token: Optional[str]) -> Optional[dict]:
        if not token or len(token) > 200:
            return None
        row = self._one(
            "SELECT u.username, u.display_name, s.expires FROM web_sessions s "
            "JOIN users u ON u.username = s.username WHERE s.token_hash=?",
            (sha256_hex(token),))
        if not row or row["expires"] < time.time():
            return None
        return {"username": row["username"], "display_name": row["display_name"]}

    def delete_session(self, token: Optional[str]) -> None:
        if token:
            self._exec("DELETE FROM web_sessions WHERE token_hash=?", (sha256_hex(token),))

    # ---------------- agenți ----------------
    def check_agent(self, agent_id: str, secret: str) -> Optional[bool]:
        """None = agent nou, True = secret corect, False = secret greșit."""
        row = self._one("SELECT secret_hash FROM agents WHERE agent_id=?", (agent_id,))
        if row is None:
            return None
        return hmac.compare_digest(row["secret_hash"], sha256_hex(secret))

    def upsert_agent(self, agent_id: str, secret: str, info: dict, ip: str) -> None:
        now = time.time()
        self._exec(
            "INSERT INTO agents(agent_id, secret_hash, hostname, user, os, version, first_seen, "
            "last_seen, last_ip) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET "
            "hostname=excluded.hostname, user=excluded.user, os=excluded.os, "
            "version=excluded.version, last_seen=excluded.last_seen, last_ip=excluded.last_ip",
            (agent_id, sha256_hex(secret), info.get("hostname", ""), info.get("user", ""),
             info.get("os", ""), info.get("version", ""), now, now, ip))

    def touch_agent(self, agent_id: str) -> None:
        self._exec("UPDATE agents SET last_seen=? WHERE agent_id=?", (time.time(), agent_id))

    def list_agents(self) -> list[dict]:
        return self._all("SELECT agent_id, hostname, user, os, version, first_seen, last_seen, "
                         "last_ip FROM agents")

    # ---------------- audit ----------------
    def audit(self, event: str, tech: str = "", agent_id: str = "", hostname: str = "",
              ip: str = "", details: str = "") -> None:
        self._exec("INSERT INTO audit(ts, event, tech, agent_id, hostname, ip, details) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (time.time(), event, tech or "", agent_id or "", hostname or "", ip or "",
                    details or ""))

    def get_audit(self, limit: int = 200) -> list[dict]:
        return self._all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
