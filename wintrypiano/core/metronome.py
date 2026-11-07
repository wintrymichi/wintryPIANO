"""Metronome generated in the audio callback. It never ends up in the export."""
from __future__ import annotations

import numpy as np


def make_click(samplerate: int, freq: float, length_s: float = 0.035) -> np.ndarray:
    n = int(samplerate * length_s)
    t = np.arange(n, dtype=np.float32) / samplerate
    env = np.exp(-t * 90.0).astype(np.float32)
    return (np.sin(2 * np.pi * freq * t) * env * 0.8).astype(np.float32)


class Metronome:
    """Generates clicks in time, accenting the first beat of the bar."""

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
        self.frame = 0            # current position in frames
        self._click = None        # click currently sounding
        self._click_pos = 0

    def beat_index(self) -> int:
        return self.frame // self.beat_frames

    def render_into(self, out: np.ndarray, frames: int, gain: float) -> None:
        """Add the clicks into ``out`` (frames, 2) and advance time."""
        start = self.frame
        end = start + frames
        # tail of a click started in the previous block
        if self._click is not None:
            rem = self._click.shape[0] - self._click_pos
            n = min(rem, frames)
            seg = self._click[self._click_pos:self._click_pos + n]
            out[:n, 0] += seg * gain
            out[:n, 1] += seg * gain
            self._click_pos += n
            if self._click_pos >= self._click.shape[0]:
                self._click = None
        # new beats in this block
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
