"""Sintetizzatore di pianoforte basato su TinySoundFont (.sf2 / .sf3).

Lo stesso oggetto serve sia per il suono dal vivo (nella callback audio)
sia per il render offline del MIDI, così la qualità è identica.
Il pedale del sustain (CC64) è gestito qui, perché TinySoundFont non lo fa.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from wintrypiano.core.events import CC_ALL_NOTES_OFF, CC_SUSTAIN, CONTROL, NOTE_OFF, NOTE_ON
from wintrypiano.errors import UserError

log = logging.getLogger(__name__)

MAX_VOICES = 256


def _import_tsf():
    try:
        import tinysoundfont  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - dipende dall'installazione
        raise UserError("Manca la libreria tinysoundfont. Esegui di nuovo l'installer.") from exc
    return tinysoundfont


class LoadedFont:
    """Un soundfont caricato con il preset di pianoforte selezionato."""

    def __init__(self, path: Path, samplerate: int):
        tsf = _import_tsf()
        path = Path(path)
        if not path.is_file():
            raise UserError(f"Il soundfont «{path.name}» non esiste più.")
        self.path = path
        self.samplerate = samplerate
        self.synth = tsf.Synth(samplerate=samplerate)
        try:
            sfid = self.synth.sfload(str(path), max_voices=MAX_VOICES)
        except Exception as exc:  # tinysoundfont solleva SoundFontException
            raise UserError(f"Il file «{path.name}» non è un soundfont valido (.sf2 o .sf3).") from exc
        self.preset_name = self._select_piano(sfid)

    def _select_piano(self, sfid: int) -> str:
        # Preferisce bank 0 preset 0 (Acoustic Grand Piano), altrimenti il primo disponibile.
        candidates = [(0, 0), (0, 1), (0, 2)]
        candidates += [(b, p) for b in (0, 1, 8, 16, 128) for p in range(128)]
        for bank, preset in candidates:
            name = self.synth.sfpreset_name(sfid, bank, preset)
            if name is not None:
                self.synth.program_select(0, sfid, bank, preset)
                return name
        raise UserError("Il soundfont non contiene strumenti utilizzabili.")


class PianoSynth:
    """Wrapper thread-safe: ``lock`` protegge lo stato del sintetizzatore."""

    def __init__(self, samplerate: int = 48000, max_block: int = 4096):
        self.samplerate = samplerate
        self.lock = threading.Lock()
        self.font: LoadedFont | None = None
        self._buf = bytearray(max_block * 2 * 4)
        self._mv = memoryview(self._buf)
        self._arr = np.frombuffer(self._buf, dtype=np.float32).reshape(-1, 2)
        self.max_block = max_block
        self._reset_state()

    # ---------------------------------------------------------------- stato
    def _reset_state(self) -> None:
        self.sustain = False
        self._held = [False] * 128       # tasti fisicamente premuti
        self._sustained = [False] * 128  # note tenute dal pedale

    @property
    def loaded(self) -> bool:
        return self.font is not None

    @property
    def path(self) -> Path | None:
        return self.font.path if self.font else None

    def set_font(self, font: LoadedFont | None) -> None:
        """Sostituisce il soundfont (caricato altrove, fuori dalla callback)."""
        with self.lock:
            self.font = font
            self._reset_state()

    # --------------------------------------------------------------- eventi
    def handle(self, kind: int, a: int, b: int) -> None:
        """Applica un evento. Va chiamato tenendo ``lock``."""
        font = self.font
        if font is None:
            return
        s = font.synth
        if kind == NOTE_ON:
            if self._sustained[a]:
                s.noteoff(0, a)
                self._sustained[a] = False
            s.noteon(0, a, max(1, min(127, b)))
            self._held[a] = True
        elif kind == NOTE_OFF:
            self._held[a] = False
            if self.sustain:
                self._sustained[a] = True
            else:
                s.noteoff(0, a)
        elif kind == CONTROL:
            if a == CC_SUSTAIN:
                down = b >= 64
                if self.sustain and not down:
                    for key in range(128):
                        if self._sustained[key] and not self._held[key]:
                            s.noteoff(0, key)
                        self._sustained[key] = False
                self.sustain = down
            elif a == CC_ALL_NOTES_OFF or a == 120:
                self._reset_state()
                s.notes_off()
            elif a in (7, 11, 10):  # volume, expression, pan
                s.control_change(0, a, b)

    def all_off(self) -> None:
        with self.lock:
            self._reset_state()
            if self.font:
                self.font.synth.sounds_off()

    def generate(self, frames: int) -> np.ndarray:
        """Genera ``frames`` campioni stereo nel buffer interno (tenere ``lock``).

        Ritorna una vista (frames, 2) valida fino alla prossima chiamata.
        """
        if frames > self.max_block:
            frames = self.max_block
        out = self._arr[:frames]
        if self.font is None:
            out.fill(0.0)
            return out
        self.font.synth.generate_simple(frames, buffer=self._mv[:frames * 8])
        return out

    # --------------------------------------------------------------- render
    def render(self, events, tail_s: float = 3.0, progress=None) -> np.ndarray:
        """Render offline di una lista di eventi ``(t, tipo, a, b)``.

        Usa lo stesso soundfont del suono dal vivo. Durante il render il suono
        dal vivo resta in silenzio (il lock è occupato).
        """
        if self.font is None:
            raise UserError("Nessun suono di pianoforte caricato.")
        sr = self.samplerate
        evs = sorted(events, key=lambda e: e[0])
        last = evs[-1][0] if evs else 0.0
        total = int((last + tail_s) * sr) + 1
        out = np.zeros((total, 2), dtype=np.float32)
        with self.lock:
            self.font.synth.sounds_off()
            self._reset_state()
            # Scarta l'audio residuo del suono dal vivo.
            self.generate(min(self.max_block, 2048))
            pos = 0
            i = 0
            n_ev = len(evs)
            while pos < total:
                target = total
                if i < n_ev:
                    target = min(total, max(pos, int(round(evs[i][0] * sr))))
                while pos < target:
                    n = min(self.max_block, target - pos)
                    out[pos:pos + n] = self.generate(n)
                    pos += n
                    if progress is not None:
                        progress(pos / total)
                while i < n_ev and int(round(evs[i][0] * sr)) <= pos:
                    _, kind, a, b = evs[i]
                    self.handle(kind, a, b)
                    i += 1
                if i >= n_ev and pos >= total:
                    break
            self.font.synth.sounds_off()
            self._reset_state()
        return trim_silence(out, sr, keep_from=int(last * sr))


def trim_silence(audio: np.ndarray, samplerate: int, keep_from: int = 0,
                 threshold: float = 1e-4) -> np.ndarray:
    """Taglia il silenzio finale dopo ``keep_from`` lasciando 100 ms di margine."""
    if audio.shape[0] == 0:
        return audio
    loud = np.nonzero(np.abs(audio[keep_from:]).max(axis=1) > threshold)[0]
    end = keep_from + (loud[-1] + 1 if loud.size else 0)
    end = min(audio.shape[0], end + int(0.1 * samplerate))
    return audio[:max(end, 1)]
