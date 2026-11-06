"""Metronomo generato nella callback audio. Non finisce mai nell'export."""
from __future__ import annotations

import numpy as np


def make_click(samplerate: int, freq: float, length_s: float = 0.035) -> np.ndarray:
    n = int(samplerate * length_s)
    t = np.arange(n, dtype=np.float32) / samplerate
    env = np.exp(-t * 90.0).astype(np.float32)
    return (np.sin(2 * np.pi * freq * t) * env * 0.8).astype(np.float32)


class Metronome:
    """Genera click a tempo; accento sul primo movimento della battuta."""

    def __init__(self, samplerate: int, bpm: float = 100.0, beats_per_bar: int = 4):
        self.samplerate = samplerate
        self.beats_per_bar = beats_per_bar
        self.accent = make_click(samplerate, 1760.0)
        self.normal = make_click(samplerate, 1175.0)
        self.set_bpm(bpm)
        self.reset()

    def set_bpm(self, bpm: float) -> None:
        self.bpm = max(20.0, min(300.0, float(bpm)))
        self.beat_frames = int(round(self.samplerate * 60.0 / self.bpm))

    def reset(self) -> None:
        self.frame = 0            # posizione corrente in frame
        self._click = None        # click in corso
        self._click_pos = 0

    def beat_index(self) -> int:
        return self.frame // self.beat_frames

    def render_into(self, out: np.ndarray, frames: int, gain: float) -> None:
        """Somma i click in ``out`` (frames, 2) e avanza il tempo."""
        start = self.frame
        end = start + frames
        # coda di un click iniziato nel blocco precedente
        if self._click is not None:
            rem = self._click.shape[0] - self._click_pos
            n = min(rem, frames)
            seg = self._click[self._click_pos:self._click_pos + n]
            out[:n, 0] += seg * gain
            out[:n, 1] += seg * gain
            self._click_pos += n
            if self._click_pos >= self._click.shape[0]:
                self._click = None
        # nuovi movimenti in questo blocco
        first_beat = -(-start // self.beat_frames)  # ceil
        b = first_beat
        while b * self.beat_frames < end:
            off = b * self.beat_frames - start
            click = self.accent if b % self.beats_per_bar == 0 else self.normal
            n = min(click.shape[0], frames - off)
            out[off:off + n, 0] += click[:n] * gain
            out[off:off + n, 1] += click[:n] * gain
            if n < click.shape[0]:
                self._click = click
                self._click_pos = n
            b += 1
        self.frame = end
