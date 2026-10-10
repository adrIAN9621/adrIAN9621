"""Stare locală persistentă (ID, secret) și configurație."""
from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

APP_DIR_NAME = "CarpaticaAsistentaIT"
VERSION = "1.0.0"


def state_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def new_agent_id() -> str:
    return str(100_000_000 + secrets.randbelow(900_000_000))


def new_secret() -> str:
    return secrets.token_hex(32)


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def format_id(agent_id: str) -> str:
    s = str(agent_id)
    return " ".join(s[i:i + 3] for i in range(0, len(s), 3))


def _valid(d: dict) -> bool:
    aid, sec = d.get("agent_id"), d.get("agent_secret")
    return (isinstance(aid, str) and len(aid) == 9 and aid.isdigit()
            and isinstance(sec, str) and len(sec) == 64
            and all(c in "0123456789abcdef" for c in sec))


def load_or_create_state(directory: Optional[Path] = None) -> dict:
    directory = Path(directory) if directory else state_dir()
    path = directory / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if _valid(data):
            return data
    except (OSError, ValueError):
        pass
    data = {"agent_id": new_agent_id(), "agent_secret": new_secret()}
    directory.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return data


@dataclass
class AgentConfig:
    server_url: str = "wss://it.carpatica.local:8443/ws/agent"
    ca_file: Optional[str] = None
    verify_tls: bool = True
    allow_insecure: bool = False
    default_quality: int = 60
    default_scale: float = 1.0
    default_fps: int = 10
    base_dir: Path = field(default_factory=Path.cwd)

    def ca_path(self) -> Optional[str]:
        if not self.ca_file:
            return None
        p = Path(self.ca_file)
        if not p.is_absolute():
            p = self.base_dir / p
        return str(p)


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_config(path: Optional[Path] = None) -> AgentConfig:
    candidates = [Path(path)] if path else [app_base_dir() / "config.json", state_dir() / "config.json"]
    for p in candidates:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cfg = AgentConfig(base_dir=p.parent)
        for k in ("server_url", "ca_file", "verify_tls", "allow_insecure",
                  "default_quality", "default_scale", "default_fps"):
            if k in raw:
                setattr(cfg, k, raw[k])
        return cfg
    return AgentConfig(base_dir=app_base_dir())
