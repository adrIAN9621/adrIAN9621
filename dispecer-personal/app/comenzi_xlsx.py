"""Importă comenzile active exportate din Comandă Personal (ComenziActive_*.xlsx).

    python -m app.comenzi_xlsx                 cel mai nou ComenziActive_*.xlsx din Downloads
    python -m app.comenzi_xlsx C:\\cale\\fisier.xlsx

Afișează coloanele găsite și cum le-a înțeles, salvează rândurile în date-reale/comenzi/ și,
dacă găsește tren + persoană + ora de început, scrie date-reale/echipaje.json pentru aplicație.
Citește fișierul cu biblioteca standard Python (fără Excel / openpyxl). Nimic nu pleacă de pe calculator.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

# coloana din aplicație → cuvinte căutate în antetul din Excel (fără diacritice, litere mici)
CAMPURI = {
    "tren": ["nr tren", "numar tren", "tren", "train"],
    "persoana": ["mecanic", "nume", "personal", "angajat", "salariat", "conducator"],
    "marca": ["marca", "matricol", "cod angajat", "id angajat", "cnp"],
    "rol": ["functie", "functia", "rol", "post", "calitate"],
    "inceput": ["prezentare", "inceput", "luare in primire", "ora comanda", "data comanda", "start", "de la"],
    "statie": ["statie", "statia", "loc prezentare", "loc", "punct"],
    "locomotiva": ["locomotiva", "loc.", "loco"],
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9. ]", " ", s).split())


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def citeste_xlsx(path: Path) -> list[list[str]]:
    """Primul sheet ca listă de rânduri (text). Datele Excel rămân numere – vezi _ora()."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        first = wb.find("m:sheets/m:sheet", NS).get(REL)
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == first)
        sheet = ET.fromstring(z.read("xl/" + target.lstrip("/").removeprefix("xl/")))
    rows = []
    for r in sheet.iter("{%s}row" % NS["m"]):
        row: dict[int, str] = {}
        for c in r.findall("m:c", NS):
            t, v = c.get("t"), c.find("m:v", NS)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
            else:
                val = v.text if v is not None else ""
            row[_col_index(c.get("r"))] = (val or "").strip()
        if row:
            rows.append([row.get(i, "") for i in range(max(row) + 1)])
    return rows


def _ora(v: str) -> Optional[datetime]:
    v = (v or "").strip()
    if not v:
        return None
    try:  # număr de serie Excel (zile de la 1899-12-30)
        f = float(v)
        if 20000 < f < 80000:
            return datetime(1899, 12, 30) + timedelta(days=f)
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    return None


def potriveste_coloane(header: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    hn = [_norm(h) for h in header]
    for camp, cuvinte in CAMPURI.items():
        for w in cuvinte:  # cuvintele mai precise primele
            for i, h in enumerate(hn):
                if i in found.values():
                    continue
                if h == w or (len(w) > 3 and w in h):
                    found[camp] = i
                    break
            if camp in found:
                break
    return found


def importa(path: Path, folder: Path) -> dict:
    rows = citeste_xlsx(path)
    hdr_i = next((i for i, r in enumerate(rows[:15]) if sum(1 for c in r if c) >= 3
                  and any("tren" in _norm(c) for c in r)), 0)
    header, data = rows[hdr_i], [r for r in rows[hdr_i + 1:] if any(r)]
    cols = potriveste_coloane(header)
    records = [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in data]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "comenzi").mkdir(exist_ok=True)
    (folder / "comenzi" / (path.stem + ".json")).write_text(
        json.dumps({"fisier": path.name, "coloane": header, "comenzi": records}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    echipaje, sarite = [], 0
    if {"tren", "persoana", "inceput"} <= cols.keys():
        for r in data:
            get = lambda k: (r[cols[k]] if k in cols and cols[k] < len(r) else "").strip()
            start = _ora(get("inceput"))
            tren = re.sub(r"\D", "", get("tren"))
            if not (tren and get("persoana") and start):
                sarite += 1
                continue
            rol = "ajutor" if re.search(r"ajut|asist|aj\.", _norm(get("rol"))) else "mecanic"
            echipaje.append({"tren": tren, "id_personal": get("marca") or get("persoana"), "nume": get("persoana"),
                             "rol": rol, "inceput": start.isoformat(), "statie": get("statie"),
                             "locomotiva": get("locomotiva")})
        (folder / "echipaje.json").write_text(json.dumps(echipaje, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"antet": header, "coloane": cols, "randuri": len(data), "echipaje": len(echipaje), "sarite": sarite}


def cel_mai_nou() -> Optional[Path]:
    files = sorted((Path.home() / "Downloads").glob("ComenziActive_*.xlsx"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else cel_mai_nou()
    if not path or not path.exists():
        print("Nu găsesc fișierul ComenziActive_*.xlsx (exportați-l din Comandă → Comenzi active).")
        return 1
    folder = Path(argv[1]) if len(argv) > 1 else Path("date-reale")
    r = importa(path, folder)
    print(f"Fișier: {path}")
    print(f"Rânduri (comenzi): {r['randuri']}")
    print("Coloane din Excel:", " | ".join(r["antet"]))
    print("Cum le-am înțeles:")
    for camp in CAMPURI:
        i = r["coloane"].get(camp)
        print(f"  {camp:<11} → {r['antet'][i] if i is not None else '(negăsit)'}")
    if r["echipaje"]:
        print(f"Scris {folder / 'echipaje.json'}: {r['echipaje']} echipaje ({r['sarite']} rânduri sărite)")
    else:
        print("NU am scris echipaje.json – lipsesc coloane (tren / persoană / ora de început). Trimiteți lista de coloane.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
