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
    # --- dispozitive nesupravegheate (RustDesk) ---
    ingest_token: str = ""          # token Bearer cu care laptopurile raportează
    enc_secret: str = ""            # secret pentru criptarea parolelor RustDesk în repaus
    register_rate_limit: int = 60   # cereri /api/register per fereastră, per IP
    register_rate_window: float = 60.0
    max_body_bytes: int = 64 * 1024
    # În spatele unui reverse proxy de încredere (ex. Caddy în Docker): preia
    # IP-ul real al clientului din X-Forwarded-For. A se activa DOAR când aplicația
    # este accesibilă exclusiv prin proxy (fără port publicat către exterior).
    trust_proxy: bool = False
    forwarded_allow_ips: str = "127.0.0.1"

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
    # Generează secretele pentru dispozitivele nesupravegheate la prima rulare.
    import secrets as _secrets
    changed = False
    if not cfg.ingest_token:
        cfg.ingest_token = _secrets.token_urlsafe(32)
        changed = True
    if not cfg.enc_secret:
        cfg.enc_secret = _secrets.token_urlsafe(48)
        changed = True
    if create and (not os.path.isfile(path) or changed):
        save_config(cfg, path)
    return cfg


def save_config(cfg: Config, path: Optional[str] = None) -> None:
    path = path or DEFAULT_CONFIG_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
