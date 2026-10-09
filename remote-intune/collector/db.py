"""Strat de acces la baza de date SQLite (doar biblioteca standard)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id            TEXT PRIMARY KEY,
    hostname      TEXT NOT NULL DEFAULT '',
    enc_password  TEXT NOT NULL DEFAULT '',
    device_user   TEXT NOT NULL DEFAULT '',
    server        TEXT NOT NULL DEFAULT '',
    first_seen    REAL NOT NULL,
    last_reported REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    username   TEXT PRIMARY KEY,
    salt       TEXT NOT NULL,
    hash       TEXT NOT NULL,
    iterations INTEGER NOT NULL,
    created    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL,
    device_id TEXT NOT NULL,
    hostname  TEXT NOT NULL DEFAULT '',
    ip        TEXT NOT NULL DEFAULT '',
    ts        REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: uvicorn/Starlette rulează handlerele în
        # thread-uri de lucru; accesul este serializat de SQLite + GIL aici.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- dispozitive --------------------------------------------------- #
    def upsert_device(
        self,
        *,
        device_id: str,
        hostname: str,
        enc_password: str,
        device_user: str,
        server: str,
        last_reported: float,
    ) -> None:
        now = last_reported
        cur = self.conn.execute(
            "SELECT id FROM devices WHERE id = ?", (device_id,)
        )
        if cur.fetchone() is None:
            self.conn.execute(
                "INSERT INTO devices "
                "(id, hostname, enc_password, device_user, server, first_seen, last_reported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (device_id, hostname, enc_password, device_user, server, now, now),
            )
        else:
            self.conn.execute(
                "UPDATE devices SET hostname=?, enc_password=?, device_user=?, "
                "server=?, last_reported=? WHERE id=?",
                (hostname, enc_password, device_user, server, now, device_id),
            )
        self.conn.commit()

    def list_devices(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT id, hostname, device_user, server, first_seen, last_reported "
                "FROM devices ORDER BY last_reported DESC"
            )
        )

    def get_device(self, device_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()

    # --- utilizatori --------------------------------------------------- #
    def add_user(self, username: str, salt: str, hash_: str, iterations: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO users (username, salt, hash, iterations, created) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, salt, hash_, iterations, time.time()),
        )
        self.conn.commit()

    def delete_user(self, username: str) -> bool:
        cur = self.conn.execute("DELETE FROM users WHERE username = ?", (username,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_user(self, username: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    def list_users(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT username, created FROM users ORDER BY username"))

    # --- audit --------------------------------------------------------- #
    def add_audit(self, username: str, device_id: str, hostname: str, ip: str) -> None:
        self.conn.execute(
            "INSERT INTO audit (username, device_id, hostname, ip, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, device_id, hostname, ip, time.time()),
        )
        self.conn.commit()

    def list_audit(self, limit: int = 500) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT username, device_id, hostname, ip, ts FROM audit "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
        )
