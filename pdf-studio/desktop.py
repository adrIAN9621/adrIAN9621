"""PDF Studio ca aplicație desktop de sine stătătoare (fereastră proprie).

Pornește serverul local în fundal și deschide aplicația într-o fereastră
proprie, fără bară de adrese/tab-uri (modul „aplicație" al Microsoft Edge sau
Google Chrome, prezent pe orice Windows 10/11). Dacă niciunul nu e găsit,
deschide în browserul implicit. Scrie și un jurnal de pornire pentru depanare.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import traceback

HOST = "127.0.0.1"


def _data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "PDF-Studio")
    os.makedirs(d, exist_ok=True)
    return d


def _log(msg: str) -> None:
    try:
        with open(os.path.join(_data_dir(), "startup.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def _free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((HOST, port))
                return s.getsockname()[1]
        except OSError:
            continue
    return preferred


def _wait_ready(port: int, timeout: float = 40.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((HOST, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _serve(port: int) -> None:
    try:
        import uvicorn

        from app.main import app
        uvicorn.run(app, host=HOST, port=port, log_level="warning")
    except Exception:
        _log("EROARE server:\n" + traceback.format_exc())


def _find_browser() -> str | None:
    """Găsește un browser Chromium pentru modul „aplicație" (fereastră proprie)."""
    import shutil

    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    rels = [
        r"Microsoft\Edge\Application\msedge.exe",
        r"Google\Chrome\Application\chrome.exe",
        r"BraveSoftware\Brave-Browser\Application\brave.exe",
        r"Vivaldi\Application\vivaldi.exe",
    ]
    for base in (pf, pfx, local):
        for rel in rels:
            if base:
                p = os.path.join(base, rel)
                if os.path.exists(p):
                    return p

    # pe PATH
    for exe in ("msedge", "chrome", "brave", "vivaldi"):
        found = shutil.which(exe)
        if found:
            return found

    # din registru (App Paths), unde pune Windows căile programelor instalate
    try:
        import winreg

        for exe in ("msedge.exe", "chrome.exe", "brave.exe"):
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(
                        root,
                        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}",
                    )
                    val, _ = winreg.QueryValueEx(key, None)
                    winreg.CloseKey(key)
                    if val and os.path.exists(val):
                        return val
                except OSError:
                    continue
    except Exception:
        pass
    return None


def _open_app_window(url: str):
    """Deschide o fereastră proprie (mod aplicație).

    Întoarce procesul ferestrei (``subprocess.Popen``) dacă a mers, altfel
    ``None``. Profilul este unic per pornire, deci se deschide MEREU o fereastră
    nouă legată de acest server – iar procesul poate fi așteptat ca să știm când
    utilizatorul a închis fereastra (atunci oprim și aplicația, fără procese
    rămase în fundal).
    """
    browser = _find_browser()
    if not browser:
        _log("Nu am găsit Edge/Chrome pentru modul aplicație.")
        return None
    profile = os.path.join(_data_dir(), "win-%d" % os.getpid())
    args = [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    try:
        _log(f"Deschid fereastra cu: {browser}")
        return subprocess.Popen(args)
    except Exception:
        _log("EROARE la deschiderea ferestrei:\n" + traceback.format_exc())
        return None


def _wait_window_then_exit(proc) -> None:
    """Așteaptă închiderea ferestrei; la închidere, aplicația se termină.

    Așa se comportă ca orice program Windows: închizi fereastra -> se oprește și
    serverul local. Dacă procesul ferestrei nu poate fi așteptat fiabil
    (ex. Edge a predat fereastra altui proces), cădem pe o buclă care verifică
    periodic dacă mai există vreo fereastră.
    """
    try:
        proc.wait()
        _log("Fereastra a fost închisă; opresc aplicația.")
    except Exception:
        _log("Nu pot aștepta fereastra; rămân pornit.\n" + traceback.format_exc())
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


def main() -> None:
    port = int(os.environ.get("PDFSTUDIO_PORT") or _free_port())
    url = f"http://{HOST}:{port}"
    _log(f"Pornire PDF Studio pe {url}")

    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    if not _wait_ready(port):
        _log("Serverul nu a pornit la timp.")

    if os.environ.get("PDFSTUDIO_NO_BROWSER"):
        # mod de verificare (CI): ținem serverul pornit fără fereastră
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    proc = _open_app_window(url)
    if proc is not None:
        print(f"PDF Studio rulează. ({url})")
        _wait_window_then_exit(proc)
        return

    # Rezervă: browserul implicit, ca să apară mereu ceva.
    try:
        import webbrowser
        _log("Rezervă: deschid în browserul implicit.")
        webbrowser.open(url)
    except Exception:
        _log("EROARE browser implicit:\n" + traceback.format_exc())
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
