"""Importă lista de personal exportată din Comandă (DatePersonal_*.xls) → date-reale/personal.json.

    python -m app.personal_xls                     cel mai nou DatePersonal_*.xls(x) din Downloads
    python -m app.personal_xls C:\\cale\\fisier.xls

Din fiecare om păstrează: numele, funcția (mecanic / ajutor), localitatea de domiciliu și telefonul.
Localitatea se transformă în coordonate cu lista de stații (statii.json – aproape fiecare localitate
are o gară cu același nume), fără niciun serviciu extern. Totul rămâne pe calculator.

Fișierul .xls poate fi: o pagină HTML salvată ca .xls (exporturile web), un .xlsx sau un .xls vechi –
acesta din urmă e convertit cu Excel-ul instalat (sau cu pachetul xlrd, dacă există).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from . import geo
from .comenzi_xlsx import _norm, foi, gaseste_antet, id_persoana, nume_afisat, tip
from .statii import Statii

COLOANE = {
    "nume": ["nume si prenume", "nume prenume", "numele", "nume", "personal", "angajat", "salariat"],
    "prenume": ["prenume"],
    "functie": ["functie", "functia", "calificare", "meserie", "post", "categorie", "tip personal"],
    "localitate": ["statie apropiata", "statia apropiata", "localitate domiciliu", "domiciliu", "localitate",
                   "oras", "resedinta", "adresa", "statie"],
    "judet": ["judet"],
    "telefon": ["telefon", "mobil", "tel"],
    "marca": ["marca", "matricol", "cod angajat"],
    "depou": ["depou", "remiza", "punct de lucru", "baza"],
    "concediu": ["concediu", "absent"],
    "incheiere": ["data incheiere", "data plecare", "data incetare"],
}


# ------------------------------------------------------------------ citire fișier
def _randuri_html(text: str) -> list[list[str]]:
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.rows, self.row, self.cell = [], None, None

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                self.cell = ""

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.cell is not None and self.row is not None:
                self.row.append(" ".join(self.cell.split()))
                self.cell = None
            elif tag == "tr" and self.row is not None:
                if any(self.row):
                    self.rows.append(self.row)
                self.row = None

        def handle_data(self, data):
            if self.cell is not None:
                self.cell += data

    p = P()
    p.feed(text)
    return p.rows


def citeste_tabel(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    if raw[:2] == b"PK":                                   # .xlsx
        return max((r for _, r in foi(path)), key=len, default=[])
    head = raw[:2048].lstrip().lower()
    if head.startswith(b"<") or b"<table" in raw[:20000].lower():   # HTML salvat ca .xls
        for enc in ("utf-8", "cp1250", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return _randuri_html(text)
    if raw[:4] == b"\xd0\xcf\x11\xe0":                     # .xls vechi (BIFF)
        try:
            import xlrd  # type: ignore
            sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
            return [[str(c.value).strip() for c in sh.row(i)] for i in range(sh.nrows)]
        except ImportError:
            return citeste_tabel(_converteste_cu_excel(path))
    if b"\t" in raw[:2000]:                                # text separat cu tab
        return [line.split("\t") for line in raw.decode("utf-8", "replace").splitlines() if line.strip()]
    raise ValueError("Format de fișier necunoscut")


def _converteste_cu_excel(path: Path) -> Path:
    out = Path(tempfile.gettempdir()) / (path.stem + "_convertit.xlsx")
    ps = (f"$e=New-Object -ComObject Excel.Application; $e.DisplayAlerts=$false; "
          f"$w=$e.Workbooks.Open('{path.resolve()}'); $w.SaveAs('{out}', 51); $w.Close($false); $e.Quit()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=120)
    return out


# ------------------------------------------------------------------ interpretare
def potriveste(header: list[str]) -> dict[str, int]:
    hn = [_norm(h) for h in header]
    found: dict[str, int] = {}
    for camp, cuvinte in COLOANE.items():
        for w in cuvinte:
            i = next((i for i, h in enumerate(hn) if i not in found.values()
                      and (h == w or (len(w) > 3 and w in h))), None)
            if i is not None:
                found[camp] = i
                break
    return found


def rol_din_functie(f: str) -> Optional[str]:
    n = _norm(f)
    if not n:
        return "mecanic"
    if re.search(r"electro|instruct|revizor|sef|inspector|dispecer", n):
        return None  # electromecanic, mecanic instructor, șef… – nu conduc trenul
    if re.search(r"ajut|asist|aj\b|\bam\b", n):
        return "ajutor"
    if re.search(r"mecanic|mec\b|conduc|loc\b|locomotiv", n):
        return "mecanic"
    return None  # altă funcție (sef, revizor…) – nu e personal de locomotivă


PREFIX = re.compile(r"^(str|strada|nr|bl|sc|ap|et|com|comuna|sat|satul|oras|orasul|mun|municipiul|jud|judetul|"
                    r"loc|localitatea|sector)\b\.?\s*", re.I)


def localizeaza(statii: Statii, localitate: str, judet: str = "") -> Optional[tuple[str, float, float]]:
    """Localitatea (sau adresa „Com. X, Sat Y, Str. Z nr. 3”) → (stația folosită, lat, lon)."""
    parti = [localitate] + [p.strip() for p in re.split(r"[,;/()]", localitate) if p.strip()]
    for t in parti:
        t = PREFIX.sub("", t).strip()
        if not t or re.search(r"\d", t):
            continue  # nr. de stradă / bloc
        code = statii.code(t)
        if code and code in geo.STATIONS:
            _, lat, lon = geo.STATIONS[code]
            return code, lat, lon
    return None


def importa(path: Path, folder: Path) -> dict:
    rows = citeste_tabel(path)
    h = gaseste_antet(rows)
    header, data = rows[h], [r for r in rows[h + 1:] if any(c.strip() for c in r)]
    cols = potriveste(header)
    get = lambda r, k: (r[cols[k]].strip() if k in cols and cols[k] < len(r) else "")
    statii = Statii()
    oameni, fara_loc, alta_functie = [], [], 0
    from collections import Counter
    functii: Counter = Counter()
    plecati = 0
    for r in data:
        nume = get(r, "nume")
        if get(r, "prenume") and get(r, "prenume") not in nume:
            nume = f"{nume} {get(r, 'prenume')}"
        if not nume:
            continue
        rol = rol_din_functie(get(r, "functie"))
        functii[(get(r, "functie") or "(goală)", rol or "–")] += 1
        if get(r, "incheiere"):
            plecati += 1
            continue
        if rol is None:
            alta_functie += 1
            continue
        loc_text = get(r, "localitate") or get(r, "depou")
        loc = localizeaza(statii, loc_text, get(r, "judet")) if loc_text else None
        if not loc:
            fara_loc.append(loc_text or "(fără localitate)")
            continue
        oameni.append({"id": id_persoana(nume), "nume": nume_afisat(nume), "rol": rol, "telefon": get(r, "telefon"),
                       "localitate": loc_text, "lat": loc[1], "lon": loc[2], "statie_domiciliu": loc[0],
                       "marca": get(r, "marca"), "concediu": bool(get(r, "concediu"))})
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "personal.json").write_text(json.dumps(oameni, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"antet": header, "rand_antet": h + 1, "coloane": cols, "randuri": len(data), "oameni": len(oameni),
            "fara_loc": fara_loc, "alta_functie": alta_functie, "functii": functii.most_common(),
            "plecati": plecati, "concediu": sum(1 for o in oameni if o["concediu"]), "tipuri": [tip(v) for v in data[0]] if data else []}


def cel_mai_nou() -> Optional[Path]:
    d = Path.home() / "Downloads"
    files = sorted(list(d.glob("DatePersonal_*.xls")) + list(d.glob("DatePersonal_*.xlsx")),
                   key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else cel_mai_nou()
    if not path or not path.exists():
        print("Nu găsesc DatePersonal_*.xls în Downloads (exportați lista de personal din Comandă).")
        return 1
    folder = Path(argv[1]) if len(argv) > 1 else Path("date-reale")
    r = importa(path, folder)
    print(f"Fișier: {path}")
    print(f"Antetul e pe rândul {r['rand_antet']}. Coloane (tipul valorilor din primul rând, fără valori):")
    for i, hd in enumerate(r["antet"]):
        print(f"  {i + 1:>2}. {hd or '(fără nume)'}  [{r['tipuri'][i] if i < len(r['tipuri']) else '–'}]")
    print("Cum le-am înțeles:")
    for camp in COLOANE:
        i = r["coloane"].get(camp)
        print(f"  {camp:<11} → {r['antet'][i] if i is not None else '(negăsit)'}")
    print("Funcții găsite → cum le folosesc (mecanic / ajutor / – = nu e personal de tren):")
    for (f, rol), n in r["functii"][:25]:
        print(f"  {n:>4} × {f}  → {rol}")
    print(f"Rânduri: {r['randuri']} · personal de locomotivă cu stație găsită: {r['oameni']} "
          f"(din care în concediu: {r['concediu']}) · altă funcție: {r['alta_functie']} · "
          f"plecați (dată încheiere): {r['plecati']} · stație negăsită: {len(r['fara_loc'])}")
    if r["fara_loc"]:
        from collections import Counter
        top = Counter(r["fara_loc"]).most_common(25)
        print("Stații / localități negăsite (cele mai dese):", ", ".join(f"{k} ({v})" for k, v in top))
    print(f"Scris {folder / 'personal.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
