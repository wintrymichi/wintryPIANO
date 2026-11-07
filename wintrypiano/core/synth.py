"""Piano synthesizer based on TinySoundFont (.sf2 / .sf3).

The same object is used for the live sound (in the audio callback) and for
the offline render of the MIDI, so the quality is identical. The sustain
pedal (CC64) is handled here, because TinySoundFont does not handle it.
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
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise UserError("The tinysoundfont library is missing. Run the installer again.") from exc
    return tinysoundfont


class LoadedFont:
    """A loaded soundfont with the selected piano preset."""

    def __init__(self, path: Path, samplerate: int):
        tsf = _import_tsf()
        path = Path(path)
        if not path.is_file():
            raise UserError(f"The soundfont \"{path.name}\" no longer exists.")
        self.path = path
        self.samplerate = samplerate
        self.synth = tsf.Synth(samplerate=samplerate)
        try:
            sfid = self.synth.sfload(str(path), max_voices=MAX_VOICES)
        except Exception as exc:  # tinysoundfont raises SoundFontException
            raise UserError(f"The file \"{path.name}\" is not a valid soundfont (.sf2 or .sf3).") from exc
        self.preset_name = self._select_piano(sfid)

    def _select_piano(self, sfid: int) -> str:
        # Prefer bank 0 preset 0 (Acoustic Grand Piano), otherwise the first available one.
        candidates = [(0, 0), (0, 1), (0, 2)]
        candidates += [(b, p) for b in (0, 1, 8, 16, 128) for p in range(128)]
        for bank, preset in candidates:
            name = self.synth.sfpreset_name(sfid, bank, preset)
            if name is not None:
                self.synth.program_select(0, sfid, bank, preset)
                return name
        raise UserError("The soundfont contains no usable instruments.")


class PianoSynth:
    """Thread-safe wrapper: ``lock`` protects the synthesizer state."""

    def __init__(self, samplerate: int = 48000, max_block: int = 4096):
        self.samplerate = samplerate
        self.lock = threading.Lock()
        self.font: LoadedFont | None = None
        self._buf = bytearray(max_block * 2 * 4)
        self._mv = memoryview(self._buf)
        self._arr = np.frombuffer(self._buf, dtype=np.float32).reshape(-1, 2)
        self.max_block = max_block
        self._reset_state()

    # ---------------------------------------------------------------- state
    def _reset_state(self) -> None:
        self.sustain = False
        self._held = [False] * 128       # keys physically held down
        self._sustained = [False] * 128  # notes held by the pedal

    @property
    def loaded(self) -> bool:
        return self.font is not None

    @property
    def path(self) -> Path | None:
        return self.font.path if self.font else None

    def set_font(self, font: LoadedFont | None) -> None:
        """Replace the soundfont (loaded elsewhere, outside the callback)."""
        with self.lock:
            self.font = font
            self._reset_state()

    # --------------------------------------------------------------- events
    def handle(self, kind: int, a: int, b: int) -> None:
        """Apply an event. Must be called while holding ``lock``."""
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
        """Generate ``frames`` stereo samples into the internal buffer (hold ``lock``).

        Returns a (frames, 2) view that stays valid until the next call.
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
        """Offline render of a list of ``(t, kind, a, b)`` events.

        Uses the same soundfont as the live sound. While rendering, the live
        sound is silent (the lock is held).
        """
        if self.font is None:
            raise UserError("No piano sound is loaded.")
        sr = self.samplerate
        evs = sorted(events, key=lambda e: e[0])
        last = evs[-1][0] if evs else 0.0
        total = int((last + tail_s) * sr) + 1
        out = np.zeros((total, 2), dtype=np.float32)
        with self.lock:
            self.font.synth.sounds_off()
            self._reset_state()
            # Discard leftover audio from the live sound.
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
    """Trim trailing silence after ``keep_from``, keeping a 100 ms margin."""
    if audio.shape[0] == 0:
        return audio
    loud = np.nonzero(np.abs(audio[keep_from:]).max(axis=1) > threshold)[0]
    end = keep_from + (loud[-1] + 1 if loud.size else 0)
    end = min(audio.shape[0], end + int(0.1 * samplerate))
    return audio[:max(end, 1)]
