"""Control al fluxului: maxim 2 cadre neconfirmate (ack) în zbor."""
from __future__ import annotations

import threading
import time


class FlowControl:
    def __init__(self, max_in_flight: int = 2, stall_timeout: float = 10.0, clock=time.monotonic):
        self.max_in_flight = max_in_flight
        self.stall_timeout = stall_timeout
        self._clock = clock
        self._cond = threading.Condition()
        self.reset()

    def reset(self) -> None:
        with self._cond:
            self.last_sent = 0
            self.last_acked = 0
            self._last_progress = self._clock()
            self._cond.notify_all()

    def next_seq(self) -> int:
        with self._cond:
            return self.last_sent + 1

    def in_flight(self) -> int:
        with self._cond:
            return self.last_sent - self.last_acked

    def can_send(self) -> bool:
        with self._cond:
            return self._can_send_locked()

    def _can_send_locked(self) -> bool:
        if self.last_sent - self.last_acked < self.max_in_flight:
            return True
        # Dacă tehnicianul nu mai confirmă (ex. s-a reconectat), nu blocăm la nesfârșit.
        if self.stall_timeout and self._clock() - self._last_progress > self.stall_timeout:
            self.last_acked = self.last_sent
            self._last_progress = self._clock()
            return True
        return False

    def on_sent(self, seq: int) -> None:
        with self._cond:
            if seq > self.last_sent:
                self.last_sent = seq
            if self.last_sent - self.last_acked == 1:
                self._last_progress = self._clock()

    def on_ack(self, seq: int) -> None:
        with self._cond:
            try:
                seq = int(seq)
            except (TypeError, ValueError):
                return
            if self.last_acked < seq <= self.last_sent:
                self.last_acked = seq
                self._last_progress = self._clock()
                self._cond.notify_all()

    def wait_can_send(self, timeout: float) -> bool:
        deadline = self._clock() + timeout
        with self._cond:
            while not self._can_send_locked():
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return False
                self._cond.wait(min(remaining, 0.25))
            return True

    def wake(self) -> None:
        with self._cond:
            self._cond.notify_all()
