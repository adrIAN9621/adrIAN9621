"""Punct de intrare pentru varianta împachetată (.exe) a PDF Studio.

Pornește serverul local și deschide browserul. Folosit de PyInstaller.
"""
from __future__ import annotations

import os
import socket
import threading
import webbrowser

HOST = "127.0.0.1"


def _free_port(preferred: int = 8765) -> int:
    """Întoarce portul preferat dacă e liber, altfel unul liber ales de sistem."""
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((HOST, port))
                return s.getsockname()[1]
        except OSError:
            continue
    return preferred


def main() -> None:
    import uvicorn

    from app.main import app  # importat după împachetare din bundle

    port = int(os.environ.get("PDFSTUDIO_PORT") or _free_port())
    url = f"http://{HOST}:{port}"
    print(f"PDF Studio rulează la {url}  (închideți această fereastră pentru oprire)")
    if not os.environ.get("PDFSTUDIO_NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
