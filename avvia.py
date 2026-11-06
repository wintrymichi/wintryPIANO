"""Avvia Wintry Piano.

Doppio clic su questo file (o "python avvia.py"). Se è stato usato l'installer,
il programma parte con l'ambiente Python in .venv che contiene tutte le librerie.
Opzioni: --demo per simulare un piano MIDI.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = ("PySide6", "mido", "rtmidi", "sounddevice", "soundfile", "numpy", "tinysoundfont")


def _venv_python() -> Path | None:
    scripts = HERE / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    for name in ("pythonw.exe", "python.exe", "python3", "python"):
        p = scripts / name
        if p.exists():
            return p
    return None


def _in_venv() -> bool:
    return Path(sys.prefix).resolve() == (HERE / ".venv").resolve()


def _missing() -> list[str]:
    import importlib.util

    return [m for m in REQUIRED if importlib.util.find_spec(m) is None]


def _alert(text: str) -> None:
    print(text)
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, "wintry piano", 0x30)
        except Exception:
            pass


def main() -> int:
    if not getattr(sys, "frozen", False) and not _in_venv():
        venv = _venv_python()
        if venv is not None:
            # Riavvia con il Python dell'installer, che ha tutte le librerie.
            return subprocess.call([str(venv), str(Path(__file__).resolve()), *sys.argv[1:]])
    if not getattr(sys, "frozen", False):
        missing = _missing()
        if missing:
            _alert("Mancano alcune librerie (" + ", ".join(missing) + ").\n"
                   "Esegui installa.bat nella cartella di Wintry Piano e poi riavvia.")
            return 1
    sys.path.insert(0, str(HERE))
    from wintrypiano.app import main as app_main

    return app_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
