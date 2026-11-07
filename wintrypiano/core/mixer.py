"""Offline mix of piano, voice and imported audio, with clipping protection."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wintrypiano.core.reverb import apply_reverb_offline

TARGET_PEAK = 10 ** (-1.0 / 20)  # -1 dBFS


@dataclass
class MixSettings:
    piano_volume: float = 0.8
    piano_reverb: bool = False
    voice_volume: float = 0.9
    voice_reverb: bool = False
    voice_offset_ms: float = 0.0  # >0 delays the voice, <0 moves it earlier
    base_volume: float = 0.8
    base_offset_ms: float = 0.0   # >0 the imported audio starts after the piano, <0 before


def shift(audio: np.ndarray, frames: int) -> np.ndarray:
    """Shift the audio by ``frames`` (positive = delay)."""
    if frames > 0:
        pad = np.zeros((frames,) + audio.shape[1:], dtype=audio.dtype)
        return np.concatenate([pad, audio])
    if frames < 0:
        return audio[-frames:]
    return audio


def to_stereo(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.shape[1] == 1:
        return np.repeat(audio, 2, axis=1).astype(np.float32)
    return audio[:, :2].astype(np.float32)


def prevent_clipping(mix: np.ndarray, target: float = TARGET_PEAK) -> tuple[np.ndarray, float]:
    """Lower the volume if the peak exceeds ``target``. Return (audio, gain)."""
    if mix.size == 0:
        return mix, 1.0
    peak = float(np.max(np.abs(mix)))
    gain = 1.0
    if peak > target:
        gain = target / peak
        mix = mix * gain
    np.clip(mix, -1.0, 1.0, out=mix)
    return mix.astype(np.float32, copy=False), gain


def ms_to_frames(ms: float, samplerate: int) -> int:
    return int(round(ms * samplerate / 1000.0))


def lead_frames(settings: MixSettings, samplerate: int, has_base: bool) -> int:
    """Silence needed before the piano so that imported audio starting earlier is not cut."""
    if not has_base:
        return 0
    return max(0, -ms_to_frames(settings.base_offset_ms, samplerate))


def combine(piano: np.ndarray | None, voice: np.ndarray | None, samplerate: int,
            settings: MixSettings, base: np.ndarray | None = None) -> tuple[np.ndarray, int]:
    """Sum the tracks on the common timeline, without normalising.

    Time 0 is the start of the piano. If the imported audio starts earlier (negative
    offset) everything is moved forward by ``lead`` samples, which is returned.
    """
    has_base = base is not None and base.shape[0] > 0
    lead = lead_frames(settings, samplerate, has_base)
    parts = []
    if has_base:
        b = shift(to_stereo(base), ms_to_frames(settings.base_offset_ms, samplerate) + lead)
        parts.append(b * np.float32(settings.base_volume))
    if piano is not None and piano.shape[0]:
        p = to_stereo(piano)
        if settings.piano_reverb:
            p = apply_reverb_offline(p, samplerate)
        parts.append(shift(p * np.float32(settings.piano_volume), lead))
    if voice is not None and voice.shape[0]:
        v = to_stereo(voice)
        v = shift(v, ms_to_frames(settings.voice_offset_ms, samplerate) + lead)
        if settings.voice_reverb:
            v = apply_reverb_offline(v, samplerate, wet=0.18)
        parts.append(v * np.float32(settings.voice_volume))
    parts = [p for p in parts if p.shape[0]]
    if not parts:
        return np.zeros((0, 2), dtype=np.float32), lead
    length = max(p.shape[0] for p in parts)
    out = np.zeros((length, 2), dtype=np.float32)
    for p in parts:
        out[:p.shape[0]] += p
    return out, lead


def mix_tracks(piano: np.ndarray | None, voice: np.ndarray | None, samplerate: int,
               settings: MixSettings, base: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """Mix piano (stereo, already rendered, no effects), voice (mono) and imported audio
    (stereo), lowering the volume when needed to avoid clipping."""
    out, _lead = combine(piano, voice, samplerate, settings, base)
    if out.shape[0] == 0:
        return out, 1.0
    return prevent_clipping(out)
