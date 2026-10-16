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
    "tren": ["nr tren", "numar tren", "nr. tren", "tren", "train", "circulatie", "nr circ"],
    "persoana": ["mecanic", "nume", "personal", "angajat", "salariat", "conducator"],
    "marca": ["marca", "matricol", "cod angajat", "id angajat", "cnp"],
    "rol": ["functie", "functia", "rol", "post", "calitate"],
    "inceput": ["prezentare", "inceput", "luare in primire", "ora comanda", "data comanda", "start", "de la",
                "data ora", "ora", "data"],
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


def foi(path: Path) -> list[tuple[str, list[list[str]]]]:
    """Toate foile: [(nume, rânduri)]."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        out = []
        for sh in wb.findall("m:sheets/m:sheet", NS):
            target = rels.get(sh.get(REL), "")
            name = "xl/" + target.lstrip("/").removeprefix("xl/")
            if name in z.namelist():
                out.append((sh.get("name", ""), _randuri(ET.fromstring(z.read(name)), shared)))
    return out


def citeste_xlsx(path: Path) -> list[list[str]]:
    """Foaia cu cele mai multe celule completate, ca listă de rânduri (text)."""
    return max((r for _, r in foi(path)), key=lambda rows: sum(1 for r in rows for c in r if c), default=[])


def _randuri(sheet, shared: list[str]) -> list[list[str]]:
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
            ref = c.get("r")
            row[_col_index(ref) if ref else len(row)] = (val or "").strip()
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


def _e_numar(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


def gaseste_antet(rows: list[list[str]]) -> int:
    """Rândul cu antetul: primul (din primele 20) cu ≥2 celule de text, urmat de un rând cu date.
    Titlul de deasupra („Comenzi Active (…)”) are o singură celulă, deci e sărit."""
    for i, r in enumerate(rows[:20]):
        cells = [c for c in r if c]
        if len(cells) >= 2 and all(not _e_numar(c) for c in cells) and i + 1 < len(rows) \
                and sum(1 for c in rows[i + 1] if c) >= 2:
            return i
    return 0


# ------------------------------------------------ formatul real CmdPers „Comenzi Active”
# Locomotiva | Personal Locomotiva, unde a doua celulă are una sau mai multe comenzi lipite:
# 202610_07721 - Comanda in Derulare | 16/10/2026 18:45 | 68420015, L88491816 | NUME1, NUME2
COMANDA = re.compile(r"(\d{6}_\d{3,6})\s*-\s*([^|]+?)\s*\|\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})(.*?)(?=\d{6}_\d{3,6}\s*-|$)", re.S)
TREN = re.compile(r"^[A-Za-z]?\d{6,8}[A-Za-z]?$")


def tren_cheie(t: str) -> Optional[str]:
    """68420015 → 684200/15 (tren + ziua, ca în InfoRU); L88491816 → 884918/16; 65719216A → 657192/16."""
    d = re.sub(r"\D", "", t)
    return f"{d[:-2]}/{d[-2:]}" if len(d) >= 7 else (d or None)


def parse_comenzi(cell: str) -> list[dict]:
    out = []
    for m in COMANDA.finditer(cell or ""):
        cod, stare, ora, rest = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
        trenuri, persoane = [], []
        for seg in (s.strip() for s in rest.split("|")):
            if not seg:
                continue
            items = [x.strip() for x in seg.split(",") if x.strip()]
            if items and all(TREN.match(x) for x in items):
                trenuri += items
            else:
                persoane += items
        out.append({"cod": cod, "stare": stare, "in_derulare": "derulare" in _norm(stare),
                    "ora": datetime.strptime(" ".join(ora.split()), "%d/%m/%Y %H:%M"),
                    "trenuri": trenuri, "persoane": persoane})
    return out


def id_persoana(nume: str) -> str:
    """Aceeași cheie pentru „POPESCU MARIAN - COSMIN”, „Popescu Marian-Cosmin”, „Popescu Marian-Cosmin ”."""
    s = unicodedata.normalize("NFKD", str(nume)).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"\s*-\s*", "-", s)
    return " ".join(re.sub(r"[^A-Z0-9 .-]", " ", s).split())


def nume_afisat(nume: str) -> str:
    return " ".join(w.capitalize() for w in re.sub(r"\s*-\s*", "-", str(nume)).split())


def echipaje_din_comenzi(data: list[list[str]], header: list[str]) -> tuple[list[dict], dict]:
    """Comenzile „in Derulare” → echipaje: primul nume = mecanic, al doilea = ajutor."""
    hn = [_norm(h) for h in header]
    ci = next((i for i, h in enumerate(hn) if "personal" in h), len(header) - 1)
    li = next((i for i, h in enumerate(hn) if h.startswith("locomotiv")), 0)
    echipaje, stat = [], {"comenzi": 0, "in_derulare": 0, "create": 0, "fara_tren": 0, "fara_personal": 0}
    for r in data:
        loco = r[li] if li < len(r) else ""
        for c in parse_comenzi(r[ci] if ci < len(r) else ""):
            stat["comenzi"] += 1
            if not c["in_derulare"]:
                stat["create"] += 1
                continue
            stat["in_derulare"] += 1
            trenuri = list(dict.fromkeys(k for k in (tren_cheie(t) for t in c["trenuri"])
                                         if k and not k.startswith("99999")))
            if not trenuri:
                stat["fara_tren"] += 1
            if not c["persoane"]:
                stat["fara_personal"] += 1
                continue
            for idx, nume in enumerate(c["persoane"][:2]):
                echipaje.append({"tren": "|".join(trenuri) or "?", "id_personal": id_persoana(nume),
                                 "nume": nume_afisat(nume),
                                 "rol": "mecanic" if idx == 0 else "ajutor", "inceput": c["ora"].isoformat(),
                                 "statie": "", "locomotiva": loco, "comanda": c["cod"]})
    return echipaje, stat


def tip(v: str) -> str:
    """Tipul unei valori, fără valoarea însăși (pentru afișare fără nume)."""
    if not v:
        return "gol"
    if _ora(v):
        return "dată/oră"
    if _e_numar(v):
        return "număr"
    return "text"


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
    hdr_i = gaseste_antet(rows)
    header, data = rows[hdr_i], [r for r in rows[hdr_i + 1:] if any(r)]
    cols = potriveste_coloane(header)
    records = [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in data]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "comenzi").mkdir(exist_ok=True)
    (folder / "comenzi" / (path.stem + ".json")).write_text(
        json.dumps({"fisier": path.name, "coloane": header, "comenzi": records}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    echipaje, sarite = [], 0
    format_cmdpers = any("personal" in _norm(h) for h in header) or any(
        COMANDA.search(c) for r in data[:5] for c in r)
    if format_cmdpers:
        echipaje, stat = echipaje_din_comenzi(data, header)
        (folder / "echipaje.json").write_text(json.dumps(echipaje, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"antet": header, "coloane": cols, "randuri": len(data), "echipaje": len(echipaje), "sarite": 0,
                "rand_antet": hdr_i + 1, "tipuri": [tip(v) for v in data[0]] if data else [], "cmdpers": stat}
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
    exemplu = [tip(v) for v in data[0]] if data else []
    return {"antet": header, "coloane": cols, "randuri": len(data), "echipaje": len(echipaje), "sarite": sarite,
            "rand_antet": hdr_i + 1, "tipuri": exemplu}


def cel_mai_nou() -> Optional[Path]:
    files = sorted((Path.home() / "Downloads").glob("ComenziActive_*.xlsx"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else cel_mai_nou()
    if not path or not path.exists():
        print("Nu găsesc fișierul ComenziActive_*.xlsx (exportați-l din Comandă → Comenzi active).")
        return 1
    folder = Path(argv[1]) if len(argv) > 1 else Path("date-reale")
    print("Structura fișierului (rândurile 1-2 cu text, restul doar tipul valorilor):")
    for name, rows in foi(path):
        filled = sum(1 for r in rows for c in r if c)
        print(f"  foaia „{name}”: {len(rows)} rânduri, {filled} celule completate")
        for i, r in enumerate(rows[:6]):
            cells = [(j, c) for j, c in enumerate(r) if c]
            shown = [f"{chr(65 + j) if j < 26 else j}={c[:30]}" if i < 2 else f"{chr(65 + j) if j < 26 else j}:{tip(c)}"
                     for j, c in cells]
            print(f"    rând {i + 1}: " + (", ".join(shown) or "(gol)"))
    r = importa(path, folder)
    print(f"Fișier: {path}")
    print(f"Rânduri (comenzi): {r['randuri']}")
    print(f"Antetul e pe rândul {r['rand_antet']}. Coloane (tipul valorilor din primul rând, fără valori):")
    for i, h in enumerate(r["antet"]):
        print(f"  {i + 1:>2}. {h or '(fără nume)'}  [{r['tipuri'][i] if i < len(r['tipuri']) else '–'}]")
    if "cmdpers" in r:
        s = r["cmdpers"]
        print(f"Format „Comenzi Active” din Comandă: {s['comenzi']} comenzi – {s['in_derulare']} în derulare, "
              f"{s['create']} create (încă neîncepute); {s['fara_tren']} în derulare fără tren, "
              f"{s['fara_personal']} fără personal")
        print(f"Scris {folder / 'echipaje.json'}: {r['echipaje']} oameni pe trenuri "
              f"(primul nume din comandă = mecanic, al doilea = ajutor)")
        return 0
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
