"""Coordonatele stațiilor: lista din geo.py + toate stațiile/haltele din România din OpenStreetMap.

InfoRU dă numele stațiilor ca text („Valea Seaca Hm”, „Pascani Gr.Triaj”, „Drobeta Tr.Severin”),
deci trebuie potrivite cu o listă de coordonate. Lista completă se descarcă o dată:

    python -m app.statii descarca      (sau Descarca-Statii.bat) → statii.json lângă aplicație

Date © contribuitorii OpenStreetMap, licență ODbL.
"""
from __future__ import annotations

import difflib
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from . import geo

FILE = Path(__file__).resolve().parent.parent / "statii.json"
OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = ('[out:json][timeout:120];area["ISO3166-1"="RO"][admin_level=2]->.ro;'
         '(node["railway"~"^(station|halt|stop)$"](area.ro);node["public_transport"="station"]["train"="yes"](area.ro););'
         'out body;')

# prescurtări CFR care nu apar în numele din OSM
SUFIXE = re.compile(r"\b(hm|h|hc|hcv|halta|hcv|gr|gara|triaj|tj|bif|ram|po|pc|cf|st|statia)\b\.?")
EXPAND = [(r"\btr\.?\s*", "turnu "), (r"\bsf\.?\s*", "sfantu "), (r"\bm\.?\s*ciuc\b", "miercurea ciuc"),
          (r"\bv\.\s*", "valea "), (r"\bpt\.?\s*", "piatra ")]


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = s.replace("-", " ").replace("_", " ")
    for pat, rep in EXPAND:
        s = re.sub(pat, rep, s)
    s = SUFIXE.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


class Statii:
    """Potrivește numele din InfoRU cu stații cunoscute; le înregistrează în geo.STATIONS."""

    def __init__(self, path: Path = FILE):
        self.by_norm: dict[str, str] = {}
        for code, (name, _, _) in list(geo.STATIONS.items()):
            if not code.startswith("@"):
                self.by_norm.setdefault(norm(name), code)
        if path.exists():
            for name, c in json.loads(path.read_text(encoding="utf-8")).items():
                self._add(name, c["lat"], c["lon"])
        self._cache: dict[str, Optional[str]] = {}
        self.negasite: set[str] = set()

    def _add(self, name: str, lat: float, lon: float) -> str:
        n = norm(name)
        code = self.by_norm.get(n) or name
        if code not in geo.STATIONS:
            geo.STATIONS[code] = (name, float(lat), float(lon))
        self.by_norm.setdefault(n, code)
        return code

    def code(self, name: str) -> Optional[str]:
        """Codul stației pentru un nume din InfoRU, sau None dacă nu o găsim."""
        if not name or not name.strip():
            return None
        if name in self._cache:
            return self._cache[name]
        n = norm(name)
        code = self.by_norm.get(n)
        if code is None and n:
            # „Moacsa hcv” → „moacsa”; „Pascani Gr.Triaj” → „pascani”: încercăm și primul cuvânt / potrivire aproximativă
            m = difflib.get_close_matches(n, self.by_norm.keys(), n=1, cutoff=0.88)
            if m:
                code = self.by_norm[m[0]]
        if code is None and " " in n:
            code = self.by_norm.get(n.split(" ")[0]) if len(n.split(" ")[0]) >= 5 else None
        if code is None:
            self.negasite.add(name.strip())
        self._cache[name] = code
        return code


def descarca(path: Path = FILE) -> int:
    print("Descarc stațiile din OpenStreetMap (poate dura 1-2 minute)...")
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(OVERPASS, data=data, headers={"User-Agent": "DispecerPersonal/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        elems = json.loads(r.read().decode("utf-8"))["elements"]
    out: dict[str, dict] = {}
    for e in elems:
        tags = e.get("tags", {})
        for key in ("name", "name:ro", "official_name", "alt_name", "old_name"):
            name = tags.get(key)
            if name and "lat" in e:
                for part in name.split(";"):
                    out.setdefault(part.strip(), {"lat": e["lat"], "lon": e["lon"]})
    path.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Salvat {len(out)} nume de stații în {path}")
    return len(out)


if __name__ == "__main__":
    if (sys.argv[1:] or ["descarca"])[0] == "descarca":
        descarca()
    else:
        s = Statii()
        for n in sys.argv[1:]:
            print(n, "→", s.code(n))
