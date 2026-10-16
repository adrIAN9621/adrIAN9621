"""Cere pe rând datele de logare pentru Comandă Personal și InfoRU și le salvează local.

    python -m app.configurare

Scrie `cmdpers.json` și `inforu.json` lângă aplicație. Ambele sunt în .gitignore,
deci parolele rămân doar pe acest calculator. Enter fără nimic = păstrează valoarea veche.
"""
from __future__ import annotations

import getpass
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMDPERS = ROOT / "cmdpers.json"
INFORU = ROOT / "inforu.json"


def _load(path: Path, default: dict) -> dict:
    data = dict(default)
    if path.exists():
        data.update(json.loads(path.read_text(encoding="utf-8")))
    return data


def _ask(label: str, current: str) -> str:
    shown = f" [{current}]" if current else ""
    return input(f"  {label}{shown}: ").strip() or current


def _ask_secret(label: str, current: str) -> str:
    hint = " (Enter = păstrează parola salvată)" if current else ""
    return getpass.getpass(f"  {label}{hint} – nu se vede când scrii: ") or current


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Salvat în {path}\n")


def main() -> int:
    print("\n=== 1/2  Comandă Personal (CmdPers) ===")
    cp = _load(CMDPERS, {"servere": ["http://10.0.0.11", "http://10.40.0.1"],
                         "utilizator": "", "parola": "", "timeout_sec": 30})
    cp["utilizator"] = _ask("Utilizator Comandă", cp["utilizator"])
    cp["parola"] = _ask_secret("Parolă Comandă", cp["parola"])
    _save(CMDPERS, cp)

    print("=== 2/2  InfoRU ===")
    from .inforu import ADRESA, POARTA
    ir = _load(INFORU, {"adresa": "", "poarta": "", "utilizator": "", "parola": ""})
    ir["adresa"] = ir["adresa"] or ADRESA
    ir["poarta"] = ir["poarta"] or POARTA
    print(f"  Pagina cu trenurile: {ir['adresa']}")
    ir["utilizator"] = _ask("Utilizator InfoRU", ir["utilizator"])
    ir["parola"] = _ask_secret("Parolă InfoRU", ir["parola"])
    _save(INFORU, ir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
