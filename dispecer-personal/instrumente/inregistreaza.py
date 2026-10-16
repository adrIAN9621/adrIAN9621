"""Înregistrează date reale pentru testarea Dispecerului Personal – DOAR CITIRE.

Se rulează pe calculatorul TV wall, lângă scriptul care are deja acces la
InfoFer și la Comandă. La fiecare N secunde citește pozițiile trenurilor și
echipajele și le salvează ca fișier JSON în `<dosar>/instantanee/`.
Nu trimite, nu modifică și nu șterge nimic în sistemele de producție.

Ce trebuie completat: cele 4 funcții `citeste_*` de mai jos – fiecare apelează
ce face deja scriptul TV wall și întoarce datele în formatul din INTEGRARE.md.
Ca regulă de siguranță: folosiți doar cereri de citire (GET / SELECT).

    python inregistreaza.py --dosar date-reale --interval 60
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path


def citeste_pozitii() -> dict:
    """{"50421": {"lat", "lon", "intarziere_min", "viteza_kmh", "treceri": {"Brașov": ISO, ...}}, ...}

    `treceri` = ora reală la care trenul a ajuns/trecut prin fiecare stație (din InfoFer).
    """
    raise NotImplementedError("Legați aici citirea pozițiilor din scriptul TV wall (InfoFer)")


def citeste_echipaje() -> list:
    """[{"tren", "id_personal", "rol": "mecanic"|"ajutor", "inceput": ISO, "statie"}, ...]  (din Comandă)"""
    raise NotImplementedError("Legați aici citirea echipajelor din Comandă")


def citeste_mers() -> list:
    """[{"tren", "tip", "opriri": [{"statie", "sosire": ISO|null, "plecare": ISO|null, "lat"?, "lon"?}]}]"""
    raise NotImplementedError("Legați aici mersul trenurilor zilei")


def citeste_personal() -> list:
    """[{"id", "nume", "rol", "telefon", "localitate", "lat", "lon"}]  – lat/lon = domiciliul"""
    raise NotImplementedError("Legați aici lista personalului")


def scrie(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # aplicația nu vede niciodată un fișier pe jumătate scris


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dosar", default="date-reale")
    ap.add_argument("--interval", type=int, default=60, help="secunde între citiri")
    a = ap.parse_args()
    d = Path(a.dosar)
    (d / "instantanee").mkdir(parents=True, exist_ok=True)
    scrie(d / "personal.json", citeste_personal())
    mers_zi = None
    while True:
        try:
            zi = datetime.now().strftime("%Y-%m-%d")
            if zi != mers_zi:
                scrie(d / "mers.json", citeste_mers())
                mers_zi = zi
            acum = datetime.now().replace(microsecond=0)
            scrie(d / "instantanee" / f"{acum:%Y-%m-%dT%H-%M-%S}.json",
                  {"ora": acum.isoformat(), "pozitii": citeste_pozitii(), "echipaje": citeste_echipaje()})
            print(acum, "salvat")
        except NotImplementedError:
            raise
        except Exception as e:  # o citire ratată nu oprește înregistrarea
            print("eroare la citire:", e)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
