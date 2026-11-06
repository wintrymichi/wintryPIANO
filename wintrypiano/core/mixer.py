"""Mix offline di piano e voce, con protezione dal clipping."""
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
    voice_offset_ms: float = 0.0  # >0 ritarda la voce, <0 la anticipa


def shift(audio: np.ndarray, frames: int) -> np.ndarray:
    """Sposta l'audio di ``frames`` (positivo = ritardo)."""
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
    """Abbassa il volume se il picco supera ``target``. Ritorna (audio, guadagno)."""
    if mix.size == 0:
        return mix, 1.0
    peak = float(np.max(np.abs(mix)))
    gain = 1.0
    if peak > target:
        gain = target / peak
        mix = mix * gain
    np.clip(mix, -1.0, 1.0, out=mix)
    return mix.astype(np.float32, copy=False), gain


def mix_tracks(piano: np.ndarray | None, voice: np.ndarray | None, samplerate: int,
               settings: MixSettings) -> tuple[np.ndarray, float]:
    """Mixa piano (stereo, già renderizzato e senza effetti) e voce (mono)."""
    parts = []
    if piano is not None and piano.shape[0]:
        p = to_stereo(piano)
        if settings.piano_reverb:
            p = apply_reverb_offline(p, samplerate)
        parts.append(p * np.float32(settings.piano_volume))
    if voice is not None and voice.shape[0]:
        v = to_stereo(voice)
        v = shift(v, int(round(settings.voice_offset_ms * samplerate / 1000.0)))
        if settings.voice_reverb:
            v = apply_reverb_offline(v, samplerate, wet=0.18)
        parts.append(v * np.float32(settings.voice_volume))
    if not parts:
        return np.zeros((0, 2), dtype=np.float32), 1.0
    length = max(p.shape[0] for p in parts)
    out = np.zeros((length, 2), dtype=np.float32)
    for p in parts:
        out[:p.shape[0]] += p
    return prevent_clipping(out)
