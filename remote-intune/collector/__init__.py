"""Colector RustDesk – inventar și recuperare credențiale pentru Carpatica Feroviar."""
from __future__ import annotations

from .app import create_app
from .config import Config, ConfigError, load_config

__all__ = ["create_app", "Config", "ConfigError", "load_config"]
__version__ = "1.0.0"
