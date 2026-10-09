"""Stare în memorie: sesiuni web, limitare rată și blocare la autentificare.

Procesul colectorului este unul singur (uvicorn, un worker), deci starea în
memorie este suficientă și evită scrierea token-urilor de sesiune pe disc.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class Session:
    username: str
    expires_at: float


class SessionStore:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = Session(username, time.time() + self.ttl)
        return token

    def get(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            sess = self._sessions.get(token)
            if sess is None:
                return None
            if sess.expires_at < time.time():
                self._sessions.pop(token, None)
                return None
            return sess.username

    def destroy(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)


class RateLimiter:
    """Fereastră glisantă simplă, per cheie (ex. adresă IP)."""

    def __init__(self, max_events: int, window_seconds: int):
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            q = self._events[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            return True


class LoginGuard:
    """Blocare la autentificare după prea multe eșecuri de la aceeași IP."""

    def __init__(self, max_fails: int, lockout_seconds: int):
        self.max_fails = max_fails
        self.lockout = lockout_seconds
        self._fails: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_locked(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            fails = [t for t in self._fails[key] if t > now - self.lockout]
            self._fails[key] = fails
            return len(fails) >= self.max_fails

    def record_fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
