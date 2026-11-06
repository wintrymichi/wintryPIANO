"""Scrittura progressiva delle registrazioni su disco per il recupero dopo un crash.

Durante la registrazione un thread (mai la callback audio) aggiunge gli eventi
MIDI a ``piano.jsonl`` e i campioni della voce a ``voce.raw`` (float32 mono),
svuotando il buffer su disco a ogni scrittura. Al riavvio, se questi file
esistono, la registrazione si è interrotta e si può recuperare.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

PIANO_JOURNAL = "piano.jsonl"
VOICE_JOURNAL = "voce.raw"
VOICE_META = "voce.json"


class PianoJournal:
    def __init__(self, folder: Path, bpm: float):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / PIANO_JOURNAL
        self._f = open(self.path, "w", encoding="utf-8")
        self._f.write(json.dumps({"type": "header", "bpm": bpm}) + "\n")
        self._flush()

    def append(self, events) -> None:
        if not events:
            return
        for ev in events:
            self._f.write(json.dumps([round(ev[0], 6), ev[1], ev[2], ev[3]]) + "\n")
        self._flush()

    def _flush(self) -> None:
        self._f.flush()
        try:
            os.fsync(self._f.fileno())
        except OSError:
            pass

    def close(self, delete: bool = True) -> None:
        self._f.close()
        if delete:
            self.path.unlink(missing_ok=True)


class VoiceJournal:
    def __init__(self, folder: Path, samplerate: int):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / VOICE_JOURNAL
        self.meta_path = folder / VOICE_META
        self.meta = {"samplerate": samplerate, "auto_offset_ms": 0.0}
        self._write_meta()
        self._f = open(self.path, "wb")
        self._since_sync = 0

    def _write_meta(self) -> None:
        self.meta_path.write_text(json.dumps(self.meta), encoding="utf-8")

    def set_offset(self, offset_ms: float) -> None:
        self.meta["auto_offset_ms"] = float(offset_ms)
        self._write_meta()

    def append(self, samples: np.ndarray) -> None:
        if samples.size == 0:
            return
        self._f.write(np.ascontiguousarray(samples, dtype=np.float32).tobytes())
        self._f.flush()
        self._since_sync += samples.size
        if self._since_sync > 48000:  # circa ogni secondo
            try:
                os.fsync(self._f.fileno())
            except OSError:
                pass
            self._since_sync = 0

    def close(self, delete: bool = True) -> None:
        self._f.close()
        if delete:
            self.path.unlink(missing_ok=True)
            self.meta_path.unlink(missing_ok=True)


@dataclass
class Recovered:
    piano_events: list | None = None
    piano_bpm: float = 120.0
    voice: np.ndarray | None = None
    voice_samplerate: int = 0
    voice_offset_ms: float = 0.0

    @property
    def empty(self) -> bool:
        return not self.piano_events and (self.voice is None or self.voice.size == 0)


def find_recovery(folder: Path) -> Recovered:
    """Legge tutto ciò che è recuperabile da una cartella .recovery."""
    rec = Recovered()
    folder = Path(folder)
    pj = folder / PIANO_JOURNAL
    if pj.is_file():
        events = []
        try:
            with open(pj, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        break  # ultima riga troncata dal crash
                    if isinstance(obj, dict):
                        rec.piano_bpm = float(obj.get("bpm", 120.0))
                    elif isinstance(obj, list) and len(obj) == 4:
                        events.append((float(obj[0]), int(obj[1]), int(obj[2]), int(obj[3])))
        except OSError:
            log.exception("journal piano illeggibile")
        rec.piano_events = events or None
    vj = folder / VOICE_JOURNAL
    if vj.is_file():
        try:
            raw = vj.read_bytes()
            raw = raw[: len(raw) - (len(raw) % 4)]
            audio = np.frombuffer(raw, dtype=np.float32).copy()
            meta = {}
            mp = folder / VOICE_META
            if mp.is_file():
                try:
                    meta = json.loads(mp.read_text(encoding="utf-8"))
                except ValueError:
                    meta = {}
            if audio.size:
                rec.voice = audio
                rec.voice_samplerate = int(meta.get("samplerate", 48000))
                rec.voice_offset_ms = float(meta.get("auto_offset_ms", 0.0))
        except OSError:
            log.exception("journal voce illeggibile")
    return rec


def clear_recovery(folder: Path) -> None:
    for name in (PIANO_JOURNAL, VOICE_JOURNAL, VOICE_META):
        (Path(folder) / name).unlink(missing_ok=True)
