"""Gestione del progetto: una cartella con MIDI, WAV della voce e JSON.

    <cartella progetto>/
        progetto.json   impostazioni del progetto
        piano.mid       take del piano
        voce.wav        take della voce (mono, non processata)
        .recovery/      file temporanei scritti durante la registrazione
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np
import soundfile as sf

from wintrypiano.core.midifile import load_midi, save_midi
from wintrypiano.core.mixer import MixSettings
from wintrypiano.errors import TakeExistsError, UserError

log = logging.getLogger(__name__)

PROJECT_FILE = "progetto.json"
PIANO_FILE = "piano.mid"
VOICE_FILE = "voce.wav"
RECOVERY_DIR = ".recovery"
FORMAT_VERSION = 1


@dataclass
class ProjectSettings:
    name: str = "Senza titolo"
    bpm: float = 100.0
    metronome: bool = False
    count_in: bool = True
    piano_volume: float = 0.8
    piano_reverb: bool = False
    voice_volume: float = 0.9
    voice_reverb: bool = False
    voice_auto_offset_ms: float = 0.0
    sample_rate: int = 48000
    soundfont: str = ""
    created: str = ""
    modified: str = ""


class Project:
    def __init__(self, folder: Path, settings: ProjectSettings | None = None):
        self.folder = Path(folder)
        self.settings = settings or ProjectSettings(name=self.folder.name)
        self.dirty = False

    # --------------------------------------------------------------- percorsi
    @property
    def json_path(self) -> Path:
        return self.folder / PROJECT_FILE

    @property
    def piano_path(self) -> Path:
        return self.folder / PIANO_FILE

    @property
    def voice_path(self) -> Path:
        return self.folder / VOICE_FILE

    @property
    def recovery_dir(self) -> Path:
        return self.folder / RECOVERY_DIR

    def has_piano(self) -> bool:
        return self.piano_path.is_file()

    def has_voice(self) -> bool:
        return self.voice_path.is_file()

    # ------------------------------------------------------------- creazione
    @classmethod
    def create(cls, folder: Path, name: str | None = None) -> "Project":
        folder = Path(folder)
        if (folder / PROJECT_FILE).exists():
            raise UserError("In questa cartella c'è già un progetto. Usa «Apri» oppure scegli un'altra cartella.")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise UserError("Non riesco a creare la cartella del progetto.") from exc
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        proj = cls(folder, ProjectSettings(name=name or folder.name, created=now, modified=now))
        proj.save()
        return proj

    @classmethod
    def open(cls, folder: Path) -> "Project":
        folder = Path(folder)
        if folder.is_file():
            folder = folder.parent
        path = folder / PROJECT_FILE
        if not path.is_file():
            raise UserError("Questa cartella non contiene un progetto di Wintry Piano (manca progetto.json).")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UserError("Il file progetto.json è danneggiato.") from exc
        known = {f.name for f in fields(ProjectSettings)}
        settings = ProjectSettings(**{k: v for k, v in data.get("settings", {}).items() if k in known})
        return cls(folder, settings)

    def save(self) -> None:
        self.settings.modified = time.strftime("%Y-%m-%d %H:%M:%S")
        data = {"app": "wintry piano", "version": FORMAT_VERSION, "settings": asdict(self.settings)}
        tmp = self.json_path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.json_path)
        except OSError as exc:
            raise UserError("Non riesco a salvare il progetto. Controlla che la cartella sia scrivibile.") from exc
        self.dirty = False

    # ------------------------------------------------------------------ take
    def save_piano_take(self, events, overwrite: bool = False) -> Path:
        if self.has_piano() and not overwrite:
            raise TakeExistsError("piano")
        save_midi(events, self.piano_path, bpm=self.settings.bpm)
        self.save()
        return self.piano_path

    def load_piano_take(self):
        if not self.has_piano():
            return []
        events, _bpm = load_midi(self.piano_path)
        return events

    def save_voice_take(self, audio: np.ndarray, samplerate: int, auto_offset_ms: float,
                        overwrite: bool = False) -> Path:
        if self.has_voice() and not overwrite:
            raise TakeExistsError("voce")
        tmp = self.voice_path.with_name(VOICE_FILE + ".tmp")
        try:
            sf.write(str(tmp), audio, samplerate, subtype="FLOAT", format="WAV")
            tmp.replace(self.voice_path)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise UserError("Non riesco a salvare la registrazione della voce.") from exc
        self.settings.voice_auto_offset_ms = float(auto_offset_ms)
        self.save()
        return self.voice_path

    def load_voice_take(self):
        """Ritorna (audio mono float32, samplerate) oppure (None, 0)."""
        if not self.has_voice():
            return None, 0
        try:
            audio, sr = sf.read(str(self.voice_path), dtype="float32", always_2d=True)
        except Exception as exc:
            raise UserError("Il file della voce è danneggiato o non leggibile.") from exc
        return audio[:, 0].copy(), sr

    def mix_settings(self, manual_offset_ms: float = 0.0) -> MixSettings:
        s = self.settings
        return MixSettings(piano_volume=s.piano_volume, piano_reverb=s.piano_reverb,
                           voice_volume=s.voice_volume, voice_reverb=s.voice_reverb,
                           voice_offset_ms=s.voice_auto_offset_ms + manual_offset_ms)


def default_project_folder(base: Path) -> Path:
    """Prima cartella libera «Progetto N» dentro ``base``."""
    base = Path(base)
    i = 1
    while True:
        cand = base / f"Progetto {i}"
        if not (cand / PROJECT_FILE).exists() and not (cand.exists() and any(cand.iterdir())):
            return cand
        i += 1
