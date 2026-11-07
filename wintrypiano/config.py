"""Impostazioni persistenti dell'utente (ultime scelte, buffer, ecc.)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from wintrypiano.paths import app_data_dir

log = logging.getLogger(__name__)

BUFFER_SIZES = (64, 128, 256, 512, 1024, 2048)


@dataclass
class Config:
    midi_input: str = "*"          # "*" = tutti gli ingressi, "-" = nessuno
    audio_input: str = ""
    audio_output: str = ""
    host_api: str = "auto"          # "auto" oppure il nome esatto (es. "ASIO")
    wasapi_exclusive: bool = False
    block_size: int = 256
    soundfont_path: str = ""
    last_project: str = ""
    voice_manual_offset_ms: float = 0.0
    metronome_volume: float = 0.6
    monitor: bool = False          # ascolto del microfono in cuffia
    recent_projects: list = field(default_factory=list)
    version: int = 2

    # ------------------------------------------------------------------
    @classmethod
    def path(cls) -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or cls.path()
        cfg = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cfg
        except (OSError, ValueError):
            log.warning("Impostazioni illeggibili, uso i valori predefiniti")
            return cfg
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(cfg, key, value)
        if int(data.get("version", 1)) < 2:
            # La versione 1 salvava da sola la prima porta MIDI trovata: passo a "tutti gli ingressi".
            cfg.midi_input = "*"
            cfg.version = 2
        if cfg.block_size not in BUFFER_SIZES:
            cfg.block_size = 256
        return cfg

    def save(self, path: Path | None = None) -> None:
        path = path or self.path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
