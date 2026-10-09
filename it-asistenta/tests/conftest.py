"""Asigură un DISPLAY X11 (Xvfb) dacă e disponibil, înainte de importul pynput."""
import atexit
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_proc = None


def _start_xvfb():
    global _proc
    if os.environ.get("DISPLAY"):
        return
    if not shutil.which("Xvfb"):
        return
    disp = ":99"
    _proc = subprocess.Popen(["Xvfb", disp, "-screen", "0", "1280x1024x24"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"] = disp
    time.sleep(1.0)
    atexit.register(_stop_xvfb)


def _stop_xvfb():
    global _proc
    if _proc is not None:
        _proc.terminate()
        _proc = None


_start_xvfb()
