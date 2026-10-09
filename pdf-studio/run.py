"""Pornește PDF Studio local și deschide browserul."""
import os
import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = int(os.environ.get("PDFSTUDIO_PORT", "8765"))

if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}"
    print(f"PDF Studio rulează la {url}  (Ctrl+C pentru oprire)")
    if not os.environ.get("PDFSTUDIO_NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")
