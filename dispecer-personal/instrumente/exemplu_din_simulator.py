"""Creează un dosar de exemplu în formatul „date reale” pornind de la simulator.

Arată exact ce trebuie să producă înregistrarea de pe TV wall:
    python instrumente/exemplu_din_simulator.py date-exemplu
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.geo import STATIONS  # noqa: E402
from app.integrations.simulator import Simulator  # noqa: E402


def iso(t):
    return datetime.fromtimestamp(t).replace(microsecond=0).isoformat() if t else None


def export(folder: str | Path, start: float | None = None, hours: float = 12, step_min: int = 5) -> Path:
    d = Path(folder)
    (d / "instantanee").mkdir(parents=True, exist_ok=True)
    start = start or time.time()
    sim = Simulator(start)
    name = lambda c: STATIONS[c][0]  # datele reale folosesc numele stațiilor, nu codurile noastre
    (d / "statii.json").write_text(json.dumps({v[0]: {"lat": v[1], "lon": v[2]} for v in STATIONS.values()},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "personal.json").write_text(json.dumps([
        {"id": p.id, "nume": p.name, "rol": p.role, "telefon": p.phone, "localitate": p.home_city,
         "lat": p.lat, "lon": p.lon} for p in sim.people()], ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "mers.json").write_text(json.dumps([
        {"tren": t.train, "tip": t.kind, "opriri": [
            {"statie": name(s.station), "sosire": iso(s.arr), "plecare": iso(s.dep)} for s in t.stops]}
        for t in sim.trains(start)], ensure_ascii=False, indent=1), encoding="utf-8")
    t = start
    while t <= start + hours * 3600:
        poz = {}
        for tt in sim.trains(t):
            lv = sim.live(tt.train, t)
            if lv and lv.status != "neplecat":
                poz[tt.train] = {"lat": round(lv.lat, 5), "lon": round(lv.lon, 5),
                                 "intarziere_min": round(lv.delay_min), "viteza_kmh": lv.speed_kmh,
                                 "treceri": {name(c): iso(v) for c, v in lv.passed.items()}}
        echipaje = [{"tren": c.train, "id_personal": c.person_id, "rol": c.role, "inceput": iso(c.start),
                     "statie": name(c.station)} for c in sim.crews(t)]
        (d / "instantanee" / f"{datetime.fromtimestamp(t):%Y-%m-%dT%H-%M-%S}.json").write_text(
            json.dumps({"ora": iso(t), "pozitii": poz, "echipaje": echipaje}, ensure_ascii=False), encoding="utf-8")
        t += step_min * 60
    return d


if __name__ == "__main__":
    print("Creat:", export(sys.argv[1] if len(sys.argv) > 1 else "date-exemplu"))
