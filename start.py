"""Start Wintry Piano.

Double-click this file (or run "python start.py"). If the installer was used,
the program runs with the Python environment in .venv, which has all the libraries.
Options: --demo to simulate a MIDI piano.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = ("PySide6", "mido", "rtmidi", "sounddevice", "soundfile", "numpy", "tinysoundfont")


def _venv_python() -> Path | None:
    """Python of the .venv environment. Uses pythonw.exe (no console) only if the
    base Python has it: the Python zip package does not include it."""
    venv = HERE / ".venv"
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    names = ["python.exe", "python3", "python"]
    if os.name == "nt" and _base_has_pythonw(venv):
        names.insert(0, "pythonw.exe")
    for name in names:
        p = scripts / name
        if p.exists():
            return p
    return None


def _base_has_pythonw(venv: Path) -> bool:
    try:
        for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip().lower() == "home":
                return (Path(value.strip()) / "pythonw.exe").exists()
    except OSError:
        pass
    return False


def _hide_own_console() -> None:
    """If Windows opened a console just for us (double-click), close it.
    If the program was started from a terminal, the console stays."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        procs = (ctypes.c_uint * 4)()
        if kernel32.GetConsoleWindow() and kernel32.GetConsoleProcessList(procs, 4) <= 1:
            kernel32.FreeConsole()
    except Exception:
        pass


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
            # Restart with the installer's Python, which has all the libraries.
            return subprocess.call([str(venv), str(Path(__file__).resolve()), *sys.argv[1:]])
    if not getattr(sys, "frozen", False):
        missing = _missing()
        if missing:
            _alert("Some libraries are missing (" + ", ".join(missing) + ").\n"
                   "Run install.bat in the Wintry Piano folder, then start again.")
            return 1
    _hide_own_console()
    sys.path.insert(0, str(HERE))
    from wintrypiano.app import main as app_main

    return app_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
