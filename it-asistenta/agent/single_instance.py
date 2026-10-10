"""Garantează o singură instanță a aplicației."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


class SingleInstance:
    def __init__(self, name: str = "CarpaticaAsistentaIT"):
        self.name = name
        self._handle = None
        self._lockfile = None

    def acquire(self) -> bool:
        if sys.platform.startswith("win"):
            return self._acquire_win()
        return self._acquire_posix()

    def _acquire_win(self) -> bool:
        try:
            import ctypes
            mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\" + self.name)
            last = ctypes.windll.kernel32.GetLastError()
            self._handle = mutex
            return last != 183  # ERROR_ALREADY_EXISTS
        except Exception:
            return True

    def _acquire_posix(self) -> bool:
        import fcntl
        path = Path(tempfile.gettempdir()) / (self.name + ".lock")
        try:
            self._lockfile = open(path, "w")
            fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lockfile.write(str(os.getpid()))
            self._lockfile.flush()
            return True
        except (OSError, IOError):
            return False

    def release(self):
        try:
            if self._lockfile:
                self._lockfile.close()
        except Exception:
            pass
