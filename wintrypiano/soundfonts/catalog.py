"""Free grand piano soundfonts, with verified licenses.

Both are published on freepats.zenvoid.org under the Creative Commons
Attribution 3.0 license: they can be used and redistributed (including in the
.exe) as long as the author is credited. They are not in the Git repository
because they exceed GitHub's file size limits; the installer and the program
download them automatically.
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
    filename: str  # name of the .sf2 file saved locally


SALAMANDER = SoundfontInfo(
    key="salamander",
    title="Salamander Grand Piano V3 (Yamaha C5)",
    description="Grand piano sampled at 16 velocity layers. The most realistic. Takes 1.2 GB on disk and about 2.5 GB of RAM.",
    url="https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SF2-V3+20200602.tar.xz",
    archive_mb=296,
    license="Creative Commons Attribution 3.0 (CC BY 3.0)",
    author="Alexander Holm (samples), SF2 conversion by FreePats",
    homepage="https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html",
    filename="SalamanderGrandPiano.sf2",
)

YDP = SoundfontInfo(
    key="ydp",
    title="YDP Grand Piano (Yamaha Disklavier Pro)",
    description="A lighter grand piano, suited to PCs with little memory.",
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
    """Choose the soundfont to use: the saved one, then Salamander, then YDP, then any .sf2."""
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
