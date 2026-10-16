"""Înregistrează pozițiile locomotivelor din CmdPers – DOAR CITIRE.

Citește `/api/locations` de la laptop_proxy.py (care oricum le aduce din CmdPers
la fiecare 60 s) și le salvează în `<dosar>/locatii/`. Face doar cereri GET către
laptop_proxy, deci nu adaugă nicio cerere în CmdPers și nu modifică nimic acolo.
Folosește numai biblioteca standard Python – nu trebuie instalat nimic.

    python inregistreaza_cmdpers.py
    python inregistreaza_cmdpers.py --url http://192.168.2.108:8765/api/locations --dosar date-reale --interval 60
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path


def citeste(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8765/api/locations")
    ap.add_argument("--dosar", default="date-reale")
    ap.add_argument("--interval", type=int, default=60, help="secunde între citiri (laptop_proxy reîmprospătează la 60 s)")
    a = ap.parse_args()
    if not a.url.rstrip("/").endswith("/api/locations"):
        raise SystemExit("Din motive de siguranță se citește doar /api/locations de la laptop_proxy.")
    d = Path(a.dosar) / "locatii"
    d.mkdir(parents=True, exist_ok=True)
    print(f"Înregistrez {a.url} → {d.resolve()}  (Ctrl+C pentru oprire)")
    last = None
    while True:
        try:
            raw = citeste(a.url, 20)
            data = json.loads(raw) if raw.strip() else []
            h = hashlib.sha1(raw.encode()).hexdigest()
            acum = datetime.now().replace(microsecond=0)
            if h == last:
                print(acum, "neschimbat")
            elif not data:
                print(acum, "răspuns gol – laptop_proxy e logat în CmdPers?")
            else:
                n = len(data) if isinstance(data, list) else len(data.get("data") or [])
                path = d / f"{acum:%Y-%m-%dT%H-%M-%S}.json"
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"ora": acum.isoformat(), "sursa": a.url, "date": data},
                                          ensure_ascii=False), encoding="utf-8")
                tmp.replace(path)
                last = h
                print(acum, f"salvat {n} locomotive")
        except Exception as e:  # o citire ratată nu oprește înregistrarea
            print(datetime.now().replace(microsecond=0), "eroare:", e)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
