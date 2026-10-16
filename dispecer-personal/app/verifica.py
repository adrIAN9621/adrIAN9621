"""Verifică un dosar cu date reale înainte de test.

    python -m app.verifica date-reale
"""
from __future__ import annotations

import sys
import time

from .integrations.fisiere import FileSource, _read


def main(folder: str) -> int:
    from pathlib import Path
    if (Path(folder) / "inforu").is_dir():
        return main_inforu(folder)
    if (Path(folder) / "locatii").is_dir():
        return main_locatii(folder)
    try:
        src = FileSource(folder, replay=True)
    except Exception as e:
        print("EROARE:", e)
        return 1
    t0, t1 = src._snaps[0][0], src._snaps[-1][0]
    fmt = lambda t: time.strftime("%d.%m %H:%M", time.localtime(t))
    trains = src.trains(t0)
    seen = {n for _, p in src._snaps for n in (_read(p).get("pozitii") or {})}
    roles = {}
    for p in src.people():
        roles[p.role] = roles.get(p.role, 0) + 1
    print(f"Instantanee:  {len(src._snaps)}  ({fmt(t0)} → {fmt(t1)})")
    print(f"Trenuri în mers: {len(trains)}  · cu poziții InfoFer: {len(seen & {t.train for t in trains})}")
    print(f"Personal: {roles}")
    print(f"Echipaje pe tren (ultimul instantaneu): {len(src.crews(t1))}")
    fara_mers = sorted(seen - {t.train for t in trains})
    if fara_mers:
        print(f"Trenuri cu poziție dar fără mers (ignorate): {', '.join(fara_mers[:20])}")
    for w in src.warnings[:50]:
        print("ATENȚIE:", w)
    if len(src.warnings) > 50:
        print(f"... încă {len(src.warnings) - 50} avertismente")
    return 0


def main_locatii(folder: str) -> int:
    from .integrations.locatii import LocatiiSource
    try:
        src = LocatiiSource(folder, replay=True)
    except Exception as e:
        print("EROARE:", e)
        return 1
    t0, t1 = src._times[0], src._times[-1]
    fmt = lambda t: time.strftime("%d.%m %H:%M", time.localtime(t))
    print(f"Înregistrări CmdPers: {len(src._times)}  ({fmt(t0)} → {fmt(t1)})")
    print(f"Trenuri cu poziții: {len(src._tracks)}")
    state = src._state(t1)
    for n, s in sorted(state.items())[:40]:
        lv, tt = s["live"], s["tt"]
        trecut = sorted(lv.passed.items(), key=lambda kv: kv[1])
        trecut = [f"{src_name(c)} {time.strftime('%H:%M', time.localtime(t))}" for c, t in trecut if not c.startswith("@")]
        fata = [src_name(st.station) for st in tt.stops[1:-1][:3]]
        print(f"  tren {n:>7} {tt.kind:<14} {lv.status:<9} {lv.speed_kmh:>3} km/h | trecut: {', '.join(trecut[-3:]) or '–'}"
              f" | în față: {', '.join(fata) or '–'}")
    print(f"Personal: {len(src.people())} · echipaje: {len(src._crews)}")
    for w in src.warnings[:50]:
        print("ATENȚIE:", w)
    return 0


def main_inforu(folder: str) -> int:
    from .integrations.inforu_sursa import InfoRUSource
    try:
        src = InfoRUSource(folder, replay=True)
    except Exception as e:
        print("EROARE:", e)
        return 1
    t0, t1 = src._snaps[0], src._snaps[-1]
    fmt = lambda t: time.strftime("%d.%m %H:%M", time.localtime(t))
    state = src._state(t1)
    print(f"Instantanee InfoRU: {len(src._snaps)}  ({fmt(t0)} → {fmt(t1)})")
    print(f"Trenuri în parcurs: {len(src._hist)} · cu stația găsită pe hartă: {len(state)}")
    print(f"Legături între stații învățate: {sum(len(v) for v in src._edges.values()) // 2}")
    for n, s in sorted(state.items())[:40]:
        tt, lv = s["tt"], s["live"]
        fata = [src_name(st.station) for st in tt.stops[1:-1][:4]]
        print(f"  {n:>10} {lv.status:<9} +{lv.delay_min:>5.0f} min | acum: {src_name(tt.route[0])} → "
              f"{src_name(tt.route[-1])} | în față: {', '.join(fata) or '–'}")
    if src.statii.negasite:
        print(f"Stații fără coordonate ({len(src.statii.negasite)}) – rulați Descarca-Statii.bat:")
        print("  " + ", ".join(sorted(src.statii.negasite)[:60]))
    print(f"Personal: {len(src.people())} · echipaje: {len(src._crews)}")
    return 0


def src_name(code: str) -> str:
    from .geo import station_name
    return station_name(code)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "date-reale"))
