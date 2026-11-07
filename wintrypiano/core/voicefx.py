"""Voice effects, applied only on playback and export (voice.wav is never changed).

Chain: noise reduction -> low cut + EQ (less mud, more presence and air)
-> de-esser -> compressor. All offline with numpy, in chunks to limit memory use.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

N_FFT = 2048
HOP = N_FFT // 4


@dataclass(frozen=True)
class VoiceFx:
    enhance: bool = True        # EQ, de-esser and compressor
    denoise: bool = True        # background noise reduction
    denoise_amount: float = 0.6  # 0..1


# ---------------------------------------------------------------- STFT
def _window() -> np.ndarray:
    return np.sqrt(np.hanning(N_FFT + 1)[:-1]).astype(np.float32)


def _frames(x: np.ndarray):
    """Split into frames (with padding) and return (frames, original length)."""
    pad = N_FFT
    xp = np.concatenate([np.zeros(pad, np.float32), x.astype(np.float32), np.zeros(pad + HOP, np.float32)])
    n = (xp.size - N_FFT) // HOP + 1
    return xp, n


def _stft_chunks(xp: np.ndarray, n: int, chunk: int = 1024):
    win = _window()
    for start in range(0, n, chunk):
        stop = min(n, start + chunk)
        idx = (np.arange(start, stop) * HOP)[:, None] + np.arange(N_FFT)[None, :]
        yield start, np.fft.rfft(xp[idx] * win, axis=1)


def _bin_freqs(sr: int) -> np.ndarray:
    return np.fft.rfftfreq(N_FFT, 1.0 / sr)


def _eq_curve(sr: int) -> np.ndarray:
    """Linear gain per bin: 80 Hz high-pass, -2.5 dB at 300 Hz, +3 dB presence, +2 dB air."""
    f = np.maximum(_bin_freqs(sr), 1.0)
    db = np.zeros_like(f)
    # high-pass (about 12 dB/octave below 80 Hz)
    db += np.where(f < 80, 40 * np.log10(f / 80), 0.0)
    # less mud (wide bell at 300 Hz)
    db += -2.5 * np.exp(-0.5 * (np.log2(f / 300) / 0.6) ** 2)
    # presence (bell at 4 kHz)
    db += 3.0 * np.exp(-0.5 * (np.log2(f / 4000) / 0.7) ** 2)
    # air (gentle shelf above 10 kHz)
    db += 2.0 / (1 + np.exp(-(np.log2(f / 10000)) * 4))
    return (10 ** (db / 20)).astype(np.float32)


def _noise_profile(xp: np.ndarray, n: int) -> np.ndarray:
    """Noise spectrum: median of the quietest frames."""
    mags, energies = [], []
    for _start, spec in _stft_chunks(xp, n):
        m = np.abs(spec).astype(np.float32)
        mags.append(m)
        energies.append((m.astype(np.float64) ** 2).sum(axis=1))
    mag = np.concatenate(mags)
    energy = np.concatenate(energies)
    k = max(8, int(0.15 * energy.size))
    quiet = np.argsort(energy)[:k]
    profile = np.median(mag[quiet], axis=0) + 1e-9
    # Without real pauses (continuous singing) the "quiet" frames are voice:
    # in that case lower the estimate, so the voice is not eaten away.
    loud = np.percentile(energy, 90) + 1e-9
    quiet_level = np.median(energy[quiet])
    ratio_db = 10 * np.log10(loud / max(quiet_level, 1e-12))
    if ratio_db < 20:
        profile *= 10 ** ((ratio_db - 20) / 20)
    return profile


def _spectral(x: np.ndarray, sr: int, fx: VoiceFx) -> np.ndarray:
    xp, n = _frames(x)
    eq = _eq_curve(sr) if fx.enhance else None
    noise = _noise_profile(xp, n) if fx.denoise else None
    freqs = _bin_freqs(sr)
    sib = (freqs >= 5000) & (freqs <= 9500)
    total_band = freqs >= 100
    win = _window()
    out = np.zeros(xp.size + N_FFT, np.float32)
    prev_gain = None
    over = 1.0 + 3.0 * fx.denoise_amount        # how much noise to remove
    floor = 10 ** (-(6 + 18 * fx.denoise_amount) / 20)   # from -6 to -24 dB
    for start, spec in _stft_chunks(xp, n):
        mag = np.abs(spec)
        gain = np.ones_like(mag, dtype=np.float32)
        if noise is not None:
            snr_gain = 1.0 - over * (noise / np.maximum(mag, 1e-9)) ** 2
            g = np.sqrt(np.clip(snr_gain, 0.0, 1.0)).astype(np.float32)
            # smoothing across frequency (3 bins) and time (avoids "musical noise")
            g[:, 1:-1] = (g[:, :-2] + 2 * g[:, 1:-1] + g[:, 2:]) / 4
            for i in range(g.shape[0]):
                if prev_gain is not None:
                    # fast attack, slow release
                    g[i] = np.where(g[i] > prev_gain, g[i], 0.6 * prev_gain + 0.4 * g[i])
                prev_gain = g[i]
            gain *= np.maximum(g, floor)
        if eq is not None:
            gain *= eq
            # de-esser: when sibilants dominate the frame, lower them by up to 6 dB
            band = (mag[:, sib] ** 2).sum(axis=1)
            tot = (mag[:, total_band] ** 2).sum(axis=1) + 1e-12
            ratio = band / tot
            red = np.clip((ratio - 0.35) / 0.35, 0.0, 1.0) * (1 - 10 ** (-6 / 20))
            gain[:, sib] *= (1.0 - red)[:, None]
        frames = np.fft.irfft(spec * gain, N_FFT, axis=1).astype(np.float32) * win
        for i, fr in enumerate(frames):
            pos = (start + i) * HOP
            out[pos:pos + N_FFT] += fr
    out /= 2.0   # sqrt-hann windows at 75% overlap: sum = 2
    return out[N_FFT:N_FFT + x.size]


# ---------------------------------------------------------------- dynamics
def _rms_env(x: np.ndarray, sr: int, step_s: float = 0.005) -> tuple[np.ndarray, int]:
    step = max(1, int(sr * step_s))
    n = int(np.ceil(x.size / step))
    xp = np.zeros(n * step, np.float32)
    xp[:x.size] = x
    return np.sqrt((xp.reshape(n, step) ** 2).mean(axis=1) + 1e-12), step


def compress(x: np.ndarray, sr: int, ratio: float = 3.0, attack_s: float = 0.008,
             release_s: float = 0.12, knee_db: float = 6.0) -> np.ndarray:
    """Compressor with automatic threshold (12 dB below the loud level of the voice)."""
    if x.size == 0:
        return x
    env, step = _rms_env(x, sr)
    env_db = 20 * np.log10(env)
    active = env_db[env_db > env_db.max() - 40]
    if active.size == 0:
        return x
    loud = np.percentile(active, 90)
    threshold = loud - 12.0
    # static gain reduction with soft knee
    over = env_db - threshold
    red = np.where(over <= -knee_db / 2, 0.0,
                   np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                            (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    # attack / release
    a = np.exp(-step / (sr * attack_s))
    r = np.exp(-step / (sr * release_s))
    smooth = np.empty_like(red)
    g = 0.0
    for i, v in enumerate(red):
        coef = a if v > g else r
        g = coef * g + (1 - coef) * v
        smooth[i] = g
    gain = 10 ** (-smooth / 20)
    t = (np.arange(gain.size) + 0.5) * step
    per_sample = np.interp(np.arange(x.size), t, gain).astype(np.float32)
    y = x * per_sample
    # make-up gain: the loud voice returns to its previous level
    makeup = 10 ** (np.percentile(red, 90) * 0.7 / 20)
    return (y * makeup).astype(np.float32)


def process_voice(voice: np.ndarray, sr: int, fx: VoiceFx) -> np.ndarray:
    """Apply the effects to a mono float32 voice. Return a new array of the same length."""
    if voice is None or voice.size == 0 or not (fx.enhance or fx.denoise):
        return voice
    # NaN/inf or absurd values (a broken driver buffer) would overflow the spectra
    x = np.clip(np.nan_to_num(voice.astype(np.float32).reshape(-1), nan=0.0, posinf=0.0, neginf=0.0), -8.0, 8.0)
    y = _spectral(x, sr, fx)
    if fx.enhance:
        y = compress(y, sr)
    return y.astype(np.float32)
