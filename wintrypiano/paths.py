"""Percorsi dell'applicazione (dati utente, risorse incluse, documenti)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from wintrypiano import APP_ID


def app_data_dir() -> Path:
    override = os.environ.get("WINTRYPIANO_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    else:
        base = Path.home() / ".local" / "share" / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def resource_dir() -> Path:
    """Cartella delle risorse incluse (funziona anche dentro l'exe PyInstaller)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def bundled_soundfont_dir() -> Path:
    return resource_dir() / "assets" / "soundfonts"


def user_soundfont_dir() -> Path:
    d = app_data_dir() / "soundfonts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def documents_dir() -> Path:
    d = Path.home() / "Documents"
    if not d.exists():
        d = Path.home()
    return d / "Wintry Piano"


def log_file() -> Path:
    return app_data_dir() / "wintrypiano.log"
