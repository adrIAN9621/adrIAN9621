"""Ceasul aplicației. În simulator poate rula accelerat ca să se vadă fluxul complet."""
from __future__ import annotations

import time


class Clock:
    def __init__(self, speed: float = 1.0, start: float | None = None):
        self._real0 = time.time()
        self._sim0 = start if start is not None else self._real0
        self.speed = speed

    def now(self) -> float:
        return self._sim0 + (time.time() - self._real0) * self.speed

    def set_speed(self, speed: float) -> None:
        now = self.now()
        self._real0, self._sim0 = time.time(), now
        self.speed = max(0.0, speed)


class ManualClock:
    """Ceas controlat manual – folosit în teste."""

    def __init__(self, start: float = 0.0):
        self.t = start
        self.speed = 1.0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

    def set_speed(self, speed: float) -> None:
        self.speed = speed
