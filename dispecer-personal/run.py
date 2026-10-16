"""Pornește Dispecer Personal local și deschide browserul."""
import os
import threading
import webbrowser

import uvicorn

HOST = os.environ.get("DISPECER_HOST", "127.0.0.1")
PORT = int(os.environ.get("DISPECER_PORT", "8780"))

if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    print(f"Dispecer Personal rulează la {url}  (aplicația mecanicilor: {url}/mecanic)  Ctrl+C pentru oprire")
    if not os.environ.get("DISPECER_NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:create_app", factory=True, host=HOST, port=PORT, log_level="warning")
