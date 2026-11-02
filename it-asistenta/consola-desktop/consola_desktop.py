#!/usr/bin/env python3
"""
Carpatica Asistență IT — launcher desktop pentru consola tehnicienilor.

Deschide consola (pagina web a serverului) într-o fereastră proprie, în mod
„aplicație" (fără bara de adrese), ca o aplicație desktop normală. Rulează ca
utilizator obișnuit — autentificarea se face din consolă (butonul sus-dreapta).

URL-ul serverului se citește din `config.json` de lângă executabil (cheia
`console_url`); implicit producția Carpatica.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback

DEFAULT_URL = "https://asistenta.carpaticaferoviar.ro"
APP_DIR_NAME = "CarpaticaConsola"


def _app_base_dir() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _console_url() -> str:
    for p in (os.path.join(_app_base_dir(), "config.json"),
              os.path.join(_data_dir(), "config.json")):
        try:
            with open(p, encoding="utf-8") as f:
                url = (json.load(f) or {}).get("console_url")
            if url:
                return str(url).rstrip("/")
        except (OSError, ValueError):
            continue
    return DEFAULT_URL


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
    for rel in rels:
        for base in (pf, pfx, local):
            if base:
                p = os.path.join(base, rel)
                if os.path.exists(p):
                    return p
    for exe in ("msedge", "chrome", "brave", "vivaldi"):
        found = shutil.which(exe)
        if found:
            return found
    try:
        import winreg
        for exe in ("msedge.exe", "chrome.exe", "brave.exe"):
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(
                        root,
                        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}")
                    val, _ = winreg.QueryValueEx(key, None)
                    winreg.CloseKey(key)
                    if val and os.path.exists(val):
                        return val
                except OSError:
                    continue
    except Exception:
        pass
    return None


def _seed_profile(profile: str) -> None:
    """Presetează profilul ca să nu apară pop-up-uri (sync/sign-in/traducere)."""
    try:
        default_dir = os.path.join(profile, "Default")
        os.makedirs(default_dir, exist_ok=True)
        prefs = {
            "translate": {"enabled": False},
            "translate_blocked_languages": ["ro", "en"],
            "signin": {"allowed": False, "allowed_on_next_startup": False},
            "browser": {"has_seen_welcome_page": True},
            "sync": {"requested": False},
        }
        with open(os.path.join(default_dir, "Preferences"), "w", encoding="utf-8") as f:
            json.dump(prefs, f)
    except Exception:
        pass


def _open_app_window(url: str) -> bool:
    browser = _find_browser()
    if not browser:
        return False
    # Profil stabil (păstrează sesiunea de login între porniri).
    profile = os.path.join(_data_dir(), "win")
    _seed_profile(profile)
    disable = ",".join([
        "Translate", "TranslateUI",
        "msImplicitSignin", "msEdgeIdentityFre", "msEdgeWelcomePage",
        "ShowSyncPromo", "SyncPromoAfterSignin", "msSync",
    ])
    args = [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-translate",
        f"--disable-features={disable}",
    ]
    try:
        subprocess.Popen(args)
        return True
    except Exception:
        return False


def main() -> int:
    url = _console_url()
    if not _open_app_window(url):
        # Fără browser Chromium: deschide în browserul implicit, ca rezervă.
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            sys.stderr.write("Nu am putut deschide consola. URL: " + url + "\n")
            sys.stderr.write(traceback.format_exc())
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
