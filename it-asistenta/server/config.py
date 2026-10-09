"""Configurație server (fișier `config.json` lângă pachetul `server/`)."""
from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, field, fields
from typing import Optional

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(PACKAGE_DIR, "config.json")


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8443
    hostname: str = field(default_factory=lambda: socket.getfqdn() or "localhost")
    certfile: str = "certs/server.crt"
    keyfile: str = "certs/server.key"
    allow_insecure: bool = False
    db_path: str = "data/asistenta.db"
    session_ttl: int = 8 * 3600            # secunde, sesiune web tehnician
    consent_timeout: float = 60.0          # secunde până la refuz automat
    max_message_size: int = 8 * 1024 * 1024
    login_max_failures: int = 5
    login_lockout_seconds: int = 300
    code_max_failures: int = 5
    code_window_seconds: int = 600
    hello_timeout: float = 15.0

    # căi absolute rezolvate față de folderul pachetului
    def resolve(self, p: str) -> str:
        if not p:
            return p
        return p if os.path.isabs(p) else os.path.join(PACKAGE_DIR, p)

    @property
    def db_file(self) -> str:
        return self.resolve(self.db_path)

    @property
    def cert_file(self) -> str:
        return self.resolve(self.certfile)

    @property
    def key_file(self) -> str:
        return self.resolve(self.keyfile)

    @property
    def tls_available(self) -> bool:
        return bool(self.certfile and self.keyfile
                    and os.path.isfile(self.cert_file) and os.path.isfile(self.key_file))

    @property
    def use_tls(self) -> bool:
        return self.tls_available

    def to_dict(self) -> dict:
        return asdict(self)


def load_config(path: Optional[str] = None, create: bool = True) -> Config:
    path = path or os.environ.get("ASISTENTA_CONFIG") or DEFAULT_CONFIG_PATH
    data: dict = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    known = {f.name for f in fields(Config)}
    cfg = Config(**{k: v for k, v in data.items() if k in known})
    if create and not os.path.isfile(path):
        save_config(cfg, path)
    return cfg


def save_config(cfg: Config, path: Optional[str] = None) -> None:
    path = path or DEFAULT_CONFIG_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
