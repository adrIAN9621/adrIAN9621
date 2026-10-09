"""Captură de ecran cu mss. Izolată ca să poată fi înlocuită în teste."""
from __future__ import annotations

from typing import List

from PIL import Image


class MssCapturer:
    def __init__(self):
        self._sct = None

    def _ensure(self):
        if self._sct is None:
            import mss
            factory = getattr(mss, "MSS", None) or mss.mss
            self._sct = factory()
        return self._sct

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
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
