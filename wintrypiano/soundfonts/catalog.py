"""Soundfont di pianoforte a coda gratuiti, con licenza verificata.

Entrambi sono pubblicati su freepats.zenvoid.org con licenza Creative Commons
Attribution 3.0: si possono usare e ridistribuire (anche nel .exe) a patto di
citare l'autore. Non sono nel repository Git perché superano i limiti di
dimensione di GitHub; l'installer e il programma li scaricano in automatico.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wintrypiano.paths import bundled_soundfont_dir, user_soundfont_dir


@dataclass(frozen=True)
class SoundfontInfo:
    key: str
    title: str
    description: str
    url: str
    archive_mb: int
    license: str
    author: str
    homepage: str
    filename: str  # nome del file .sf2 salvato localmente


SALAMANDER = SoundfontInfo(
    key="salamander",
    title="Salamander Grand Piano V3 (Yamaha C5)",
    description="Pianoforte a coda campionato su 16 livelli di velocity. Il più realistico. Occupa 1,2 GB su disco e circa 2,5 GB di RAM.",
    url="https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SF2-V3+20200602.tar.xz",
    archive_mb=296,
    license="Creative Commons Attribution 3.0 (CC BY 3.0)",
    author="Alexander Holm (campioni), conversione SF2 di FreePats",
    homepage="https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html",
    filename="SalamanderGrandPiano.sf2",
)

YDP = SoundfontInfo(
    key="ydp",
    title="YDP Grand Piano (Yamaha Disklavier Pro)",
    description="Pianoforte a coda più leggero, adatto a PC con poca memoria.",
    url="https://freepats.zenvoid.org/Piano/YDP-GrandPiano/YDP-GrandPiano-SF2-20160804.tar.bz2",
    archive_mb=36,
    license="Creative Commons Attribution 3.0 (CC BY 3.0)",
    author="FreePats",
    homepage="https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html",
    filename="YDP-GrandPiano.sf2",
)

CATALOG = (SALAMANDER, YDP)
DEFAULT = SALAMANDER


def search_dirs() -> list[Path]:
    return [bundled_soundfont_dir(), user_soundfont_dir()]


def installed_path(info: SoundfontInfo) -> Path | None:
    for d in search_dirs():
        p = d / info.filename
        if p.is_file():
            return p
    return None


def find_default_soundfont(preferred: str = "") -> Path | None:
    """Sceglie il soundfont da usare: quello salvato, poi Salamander, poi YDP, poi qualsiasi .sf2."""
    if preferred and Path(preferred).is_file():
        return Path(preferred)
    for info in CATALOG:
        p = installed_path(info)
        if p:
            return p
    for d in search_dirs():
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.suffix.lower() in (".sf2", ".sf3"):
                    return p
    return None
