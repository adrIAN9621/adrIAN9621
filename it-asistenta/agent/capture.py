"""Captură de ecran cu mss. Izolată ca să poată fi înlocuită în teste.

IMPORTANT: pe Windows `mss` NU este thread-safe — o instanță creată într-un
thread nu poate fi folosită din alt thread (contextele GDI sunt thread-local).
Agentul apelează ``monitors()`` în thread-ul care tratează cererea și ``grab()``
în thread-ul de streaming, deci păstrăm o instanță `mss` PER THREAD
(``threading.local``). Altfel ``grab`` ar arunca de fiecare dată și nu s-ar
trimite niciun cadru („Se așteaptă imaginea…").
"""
from __future__ import annotations

import threading
from typing import List

from PIL import Image


class MssCapturer:
    def __init__(self):
        self._tl = threading.local()
        self._instances: list = []
        self._lock = threading.Lock()

    def _ensure(self):
        sct = getattr(self._tl, "sct", None)
        if sct is None:
            import mss
            factory = getattr(mss, "MSS", None) or mss.mss
            sct = factory()
            self._tl.sct = sct
            with self._lock:
                self._instances.append(sct)
        return sct

    def monitors(self) -> List[dict]:
        """Listă de monitoare reale (fără intrarea 0 = toate), cu index/left/top/width/height."""
        sct = self._ensure()
        mons = sct.monitors
        out = []
        for i, m in enumerate(mons[1:]):
            out.append({
                "index": i,
                "left": m["left"], "top": m["top"],
                "width": m["width"], "height": m["height"],
                "primary": i == 0,
            })
        if not out and len(mons) == 1:  # doar intrarea agregată
            m = mons[0]
            out.append({"index": 0, "left": m["left"], "top": m["top"],
                        "width": m["width"], "height": m["height"], "primary": True})
        return out

    def grab(self, monitor: dict) -> Image.Image:
        sct = self._ensure()
        region = {"left": monitor["left"], "top": monitor["top"],
                  "width": monitor["width"], "height": monitor["height"]}
        shot = sct.grab(region)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def close(self):
        with self._lock:
            instances, self._instances = self._instances, []
        for sct in instances:
            try:
                sct.close()
            except Exception:
                pass
        self._tl = threading.local()
