"""Încărcarea și validarea configurației colectorului Carpatica Feroviar.

Citește ``config.json`` din directorul colectorului (sau din calea indicată de
variabila de mediu ``COLLECTOR_CONFIG``) și expune un obiect :class:`Config`.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"


class ConfigError(RuntimeError):
    """Eroare de configurație (mesaj în limba română)."""


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8070
    certfile: str = ""
    keyfile: str = ""
    allow_insecure: bool = False
    db: str = str(BASE_DIR / "collector.db")
    ingest_token: str = ""
    enc_secret: str = ""
    session_ttl: int = 3600  # secunde
    # Limite de securitate
    max_body_bytes: int = 8192
    register_rate_limit: int = 30       # cereri
    register_rate_window: int = 60      # secunde
    login_max_fails: int = 5
    login_lockout_seconds: int = 900

    # cale absolută către fișierul de configurare folosit
    source_path: str = field(default="", repr=False)

    @property
    def tls_enabled(self) -> bool:
        return bool(self.certfile and self.keyfile)

    @property
    def db_path(self) -> Path:
        p = Path(self.db)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p

    def resolve_tls_paths(self) -> tuple[str, str]:
        """Întoarce căile absolute către certificat și cheie."""
        cert = Path(self.certfile)
        key = Path(self.keyfile)
        if not cert.is_absolute():
            cert = BASE_DIR / cert
        if not key.is_absolute():
            key = BASE_DIR / key
        return str(cert), str(key)

    def validate_for_serve(self) -> None:
        """Verifică condițiile minime înainte de pornirea serverului web.

        Refuză pornirea fără TLS, cu excepția cazului ``allow_insecure``.
        """
        if not self.ingest_token:
            raise ConfigError(
                "Lipsește 'ingest_token' din configurație. "
                "Generați unul cu: python -m collector gentoken"
            )
        if not self.enc_secret or len(self.enc_secret) < 16:
            raise ConfigError(
                "Lipsește 'enc_secret' din configurație sau este prea scurt "
                "(minim 16 caractere). Acesta protejează parolele stocate."
            )
        if not self.tls_enabled:
            if self.allow_insecure:
                return
            raise ConfigError(
                "Refuz pornirea fără TLS. Configurați 'certfile' și 'keyfile' "
                "(vezi: python -m collector gencert) sau, DOAR pentru testare "
                "locală, setați 'allow_insecure': true în config.json."
            )
        cert, key = self.resolve_tls_paths()
        if not Path(cert).exists() or not Path(key).exists():
            raise ConfigError(
                "Certificatul TLS sau cheia nu există pe disc "
                f"({cert} / {key}). Rulați: python -m collector gencert"
            )


def _config_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("COLLECTOR_CONFIG")
    if env:
        return Path(env)
    return DEFAULT_CONFIG_PATH


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Încarcă configurația din fișierul JSON; aplică valorile implicite."""
    cfg_path = _config_path(path)
    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - mesaj clar
            raise ConfigError(
                f"Fișierul de configurare {cfg_path} nu este JSON valid: {exc}"
            ) from exc
    known = {f for f in Config.__dataclass_fields__ if f != "source_path"}
    filtered = {k: v for k, v in data.items() if k in known}
    cfg = Config(**filtered)
    cfg.source_path = str(cfg_path)
    return cfg


def write_default_config(path: str | os.PathLike[str] | None = None) -> Path:
    """Scrie un ``config.json`` implicit cu token și secret generate aleator."""
    cfg_path = _config_path(path)
    template = {
        "host": "0.0.0.0",
        "port": 8070,
        "certfile": "certs/server.crt",
        "keyfile": "certs/server.key",
        "allow_insecure": False,
        "db": "collector.db",
        "ingest_token": secrets.token_urlsafe(32),
        "enc_secret": secrets.token_urlsafe(32),
        "session_ttl": 3600,
    }
    cfg_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(cfg_path, 0o600)
    except OSError:  # pragma: no cover
        pass
    return cfg_path
