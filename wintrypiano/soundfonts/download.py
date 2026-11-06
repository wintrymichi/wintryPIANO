"""Download ed estrazione dei soundfont (usato dall'installer e dal programma).

Si può eseguire anche da riga di comando:
    python -m wintrypiano.soundfonts.download            (scarica tutti)
    python -m wintrypiano.soundfonts.download salamander
    python -m wintrypiano.soundfonts.download --dest assets/soundfonts
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from wintrypiano.errors import UserError
from wintrypiano.soundfonts.catalog import CATALOG, SoundfontInfo
from wintrypiano.paths import user_soundfont_dir

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]


class Cancelled(Exception):
    pass


def _download(url: str, dest: Path, progress: Progress | None, cancel=None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "WintryPiano/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancel is not None and cancel():
                    raise Cancelled()
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    frac = done / total if total else 0.0
                    progress(frac * 0.9, f"Scaricati {done / 1e6:.0f} MB" + (f" di {total / 1e6:.0f} MB" if total else ""))
    except Cancelled:
        raise
    except OSError as exc:
        raise UserError("Download non riuscito. Controlla la connessione a internet e riprova.") from exc


def _extract_sf2(archive: Path, info: SoundfontInfo, dest_dir: Path, progress: Progress | None) -> Path:
    if progress:
        progress(0.92, "Estrazione in corso…")
    try:
        with tarfile.open(archive) as tar:
            members = [m for m in tar.getmembers()
                       if m.isfile() and m.name.lower().endswith((".sf2", ".sf3"))]
            if not members:
                raise UserError("L'archivio scaricato non contiene un soundfont.")
            member = max(members, key=lambda m: m.size)
            src = tar.extractfile(member)
            target = dest_dir / info.filename
            tmp = target.with_suffix(".part")
            with open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            tmp.replace(target)
            # Salvo anche i file di licenza/readme per l'attribuzione.
            for m in tar.getmembers():
                low = Path(m.name).name.lower()
                if m.isfile() and (low.startswith(("readme", "license", "copying", "licence")) or low.endswith(".txt")):
                    f = tar.extractfile(m)
                    if f is not None and m.size < 1_000_000:
                        (dest_dir / f"{Path(info.filename).stem}-{Path(m.name).name}").write_bytes(f.read())
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise UserError("L'archivio scaricato è danneggiato. Riprova il download.") from exc
    _write_attribution(info, dest_dir)
    return target


def _write_attribution(info: SoundfontInfo, dest_dir: Path) -> None:
    text = (f"{info.title}\nAutore: {info.author}\nLicenza: {info.license}\n"
            f"Fonte: {info.homepage}\nFile originale: {info.url}\n")
    (dest_dir / f"{Path(info.filename).stem}-CREDITS.txt").write_text(text, encoding="utf-8")


def install(info: SoundfontInfo, dest_dir: Path | None = None, progress: Progress | None = None,
            cancel=None) -> Path:
    dest_dir = Path(dest_dir or user_soundfont_dir())
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / info.filename
    if target.is_file():
        if progress:
            progress(1.0, "Già installato")
        return target
    with tempfile.TemporaryDirectory(dir=dest_dir) as td:
        archive = Path(td) / Path(info.url).name
        _download(info.url, archive, progress, cancel)
        path = _extract_sf2(archive, info, dest_dir, progress)
    if progress:
        progress(1.0, "Fatto")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Scarica i soundfont di pianoforte per Wintry Piano")
    ap.add_argument("which", nargs="*", help="salamander, ydp (predefinito: tutti)")
    ap.add_argument("--dest", default=None, help="cartella di destinazione")
    args = ap.parse_args(argv)
    chosen = [i for i in CATALOG if not args.which or i.key in args.which]
    ok = True
    for info in chosen:
        print(f"\n{info.title} - {info.archive_mb} MB - {info.license}")
        last = [-1]

        def prog(frac, msg):
            pct = int(frac * 100)
            if pct != last[0]:
                last[0] = pct
                print(f"\r  {pct:3d}%  {msg}        ", end="", flush=True)

        try:
            path = install(info, Path(args.dest) if args.dest else None, prog)
            print(f"\n  Salvato in {path}")
        except UserError as exc:
            ok = False
            print(f"\n  ERRORE: {exc.message}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
