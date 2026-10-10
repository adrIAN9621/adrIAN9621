"""PDF Studio ca aplicație desktop de sine stătătoare (fereastră proprie).

Pornește serverul local în fundal și deschide aplicația într-o fereastră
nativă (fără browser), ca orice program Windows. Folosit de PyInstaller.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time

HOST = "127.0.0.1"


def _resource(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((HOST, port))
                return s.getsockname()[1]
        except OSError:
            continue
    return preferred


def _wait_ready(port: int, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((HOST, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _serve(port: int) -> None:
    import uvicorn

    from app.main import app
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def main() -> None:
    port = int(os.environ.get("PDFSTUDIO_PORT") or _free_port())
    url = f"http://{HOST}:{port}"

    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _wait_ready(port)

    # Fereastră nativă (pe Windows folosește motorul Edge WebView2).
    try:
        import webview

        icon = _resource(os.path.join("app", "static", "brand", "icon.png"))
        kwargs = {}
        if os.path.exists(icon):
            kwargs["icon"] = icon  # ignorat pe backend-urile care nu-l susțin
        webview.create_window("PDF Studio", url, width=1280, height=860,
                              min_size=(900, 600))
        try:
            webview.start(**kwargs)
        except TypeError:
            webview.start()  # versiuni fără parametrul icon
        return
    except Exception:
        # Dacă fereastra nativă nu e disponibilă, deschidem în browser ca rezervă.
        import webbrowser
        print(f"PDF Studio rulează la {url}")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
