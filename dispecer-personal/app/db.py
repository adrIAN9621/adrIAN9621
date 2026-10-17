"""Stocare SQLite: personal, pontaj (= ture pe tren), cereri de înlocuire, oferte, jurnal."""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS persons (
    id TEXT PRIMARY KEY, name TEXT, role TEXT, phone TEXT, home_city TEXT,
    lat REAL, lon REAL, pin TEXT,
    status TEXT DEFAULT 'disponibil',   -- disponibil | indisponibil | in_deplasare | pe_tren | pauza | odihna
    status_until REAL,
    pauza_de_la REAL,                   -- sfârșitul turei 1 (pauza de 2–6 h în care poate lua tura 2)
    marca TEXT                          -- nr. matricol
);
CREATE TABLE IF NOT EXISTS pontaj (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    train TEXT, person_id TEXT, role TEXT,
    start REAL, start_station TEXT,
    end REAL, end_station TEXT,
    active INTEGER DEFAULT 1,
    km_deplasare REAL, min_deplasare REAL,
    request_id INTEGER, source TEXT
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    train TEXT, role TEXT, pontaj_id INTEGER, created REAL,
    status TEXT,          -- cautare | oferta | acceptat | finalizat | anulat
    station TEXT, eta REAL, person_id TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER, person_id TEXT, station TEXT, eta REAL,
    km REAL, travel_min REAL, created REAL, expires REAL,
    status TEXT           -- trimisa | acceptata | refuzata | expirata | anulata
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, kind TEXT, text TEXT
);
"""


class DB:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(persons)")}
            for col in ("pauza_de_la REAL", "marca TEXT"):  # baze de date create de versiuni mai vechi
                if col.split()[0] not in cols:
                    self.conn.execute(f"ALTER TABLE persons ADD COLUMN {col}")

    def q(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(args)).fetchall()]

    def one(self, sql: str, args: Iterable[Any] = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, tuple(args))
            self.conn.commit()
            return cur.lastrowid

    def insert(self, table: str, **cols: Any) -> int:
        keys = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        return self.x(f"INSERT INTO {table} ({keys}) VALUES ({marks})", cols.values())

    def update(self, table: str, id_: Any, **cols: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in cols)
        self.x(f"UPDATE {table} SET {sets} WHERE id = ?", [*cols.values(), id_])
