"""Configurare: valorile implicite pot fi suprascrise din config.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    # sursa datelor: "simulator" (demo), "cmdpers" (poziții locomotive înregistrate din CmdPers),
    # "fisiere" (date reale în formatul complet) sau "http" (sistemele reale)
    sursa: str = "simulator"
    # NU trimite nimic spre sistemele externe (comenzi, pontaj) – doar citește
    doar_citire: bool = True
    # reguli program
    program_max_ore: float = 12.0          # durata maximă a programului mecanic/ajutor
    alerta_inainte_ore: float = 3.0        # când începe căutarea înlocuitorului
    odihna_ore: float = 12.0               # odihnă după terminarea programului
    marja_predare_min: float = 15.0        # schimbul în stație cel târziu cu X min înainte de final
    # deplasarea personalului la tren
    viteza_deplasare_kmh: float = 60.0
    pregatire_min: float = 30.0            # timp de pregătire + prezentare
    raza_max_km: float = 250.0             # nu se caută mai departe de atât
    # ofertă tip Uber
    oferta_expira_sec: float = 90.0        # secunde reale pentru acceptare
    # ceas: 1 = timp real; 60 = un minut simulat pe secundă (doar în simulator)
    viteza_ceas: float = 60.0
    # autentificare
    parola_dispecer: str = "dispecer"
    # date reale din fișiere (sursa = "fisiere")
    fisiere: dict = field(default_factory=lambda: {"dosar": "date-reale", "reluare": True})
    # adaptoare HTTP (folosite când sursa = "http")
    http: dict = field(default_factory=lambda: {
        "mers_trenuri_url": "",
        "inforu_url": "",
        "personal_url": "",
        "token": "",
        "timeout_sec": 10,
    })

    @property
    def test(self) -> bool:
        """Mod test: ceas reglabil, baza de date în memorie, oamenii „răspund” automat."""
        return self.sursa in ("simulator", "fisiere", "cmdpers")

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        cfg = cls()
        p = Path(path or os.environ.get("DISPECER_CONFIG", Path(__file__).resolve().parent.parent / "config.json"))
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            names = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in names:
                    setattr(cfg, k, v)
        return cfg
