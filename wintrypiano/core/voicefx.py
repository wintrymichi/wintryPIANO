"""Effetti per la voce, applicati solo in riascolto ed export (voce.wav resta com'è).

Catena: riduzione del rumore → filtro dei bassi + EQ (meno «fango», più presenza e aria)
→ de-esser → compressore. Tutto offline con numpy, in blocchi per non usare troppa memoria.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

N_FFT = 2048
HOP = N_FFT // 4


@dataclass(frozen=True)
class VoiceFx:
    enhance: bool = True        # EQ, de-esser e compressore
    denoise: bool = True        # riduzione del rumore di fondo
    denoise_amount: float = 0.6  # 0..1


# ---------------------------------------------------------------- STFT
def _window() -> np.ndarray:
    return np.sqrt(np.hanning(N_FFT + 1)[:-1]).astype(np.float32)


def _frames(x: np.ndarray):
    """Divide in frame (con padding) e ritorna (frames, lunghezza originale)."""
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
    """Guadagno lineare per bin: passa-alto 80 Hz, -2,5 dB a 300 Hz, +3 dB presenza, +2 dB aria."""
    f = np.maximum(_bin_freqs(sr), 1.0)
    db = np.zeros_like(f)
    # passa-alto (circa 12 dB/ottava sotto gli 80 Hz)
    db += np.where(f < 80, 40 * np.log10(f / 80), 0.0)
    # meno «fango» (campana larga a 300 Hz)
    db += -2.5 * np.exp(-0.5 * (np.log2(f / 300) / 0.6) ** 2)
    # presenza (campana a 4 kHz)
    db += 3.0 * np.exp(-0.5 * (np.log2(f / 4000) / 0.7) ** 2)
    # aria (shelf dolce sopra i 10 kHz)
    db += 2.0 / (1 + np.exp(-(np.log2(f / 10000)) * 4))
    return (10 ** (db / 20)).astype(np.float32)


def _noise_profile(xp: np.ndarray, n: int) -> np.ndarray:
    """Spettro del rumore: mediana dei frame più silenziosi."""
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
    # Se non ci sono vere pause (canto continuo) i frame «silenziosi» sono voce:
    # in quel caso abbasso la stima, così non mangio la voce.
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
    over = 1.0 + 3.0 * fx.denoise_amount        # quanto rumore togliere
    floor = 10 ** (-(6 + 18 * fx.denoise_amount) / 20)   # da -6 a -24 dB
    for start, spec in _stft_chunks(xp, n):
        mag = np.abs(spec)
        gain = np.ones_like(mag, dtype=np.float32)
        if noise is not None:
            snr_gain = 1.0 - over * (noise / np.maximum(mag, 1e-9)) ** 2
            g = np.sqrt(np.clip(snr_gain, 0.0, 1.0)).astype(np.float32)
            # lisciatura in frequenza (3 bin) e nel tempo (evita il «rumore musicale»)
            g[:, 1:-1] = (g[:, :-2] + 2 * g[:, 1:-1] + g[:, 2:]) / 4
            for i in range(g.shape[0]):
                if prev_gain is not None:
                    # attacco veloce, rilascio lento
                    g[i] = np.where(g[i] > prev_gain, g[i], 0.6 * prev_gain + 0.4 * g[i])
                prev_gain = g[i]
            gain *= np.maximum(g, floor)
        if eq is not None:
            gain *= eq
            # de-esser: se le sibilanti dominano il frame, le abbasso fino a 6 dB
            band = (mag[:, sib] ** 2).sum(axis=1)
            tot = (mag[:, total_band] ** 2).sum(axis=1) + 1e-12
            ratio = band / tot
            red = np.clip((ratio - 0.35) / 0.35, 0.0, 1.0) * (1 - 10 ** (-6 / 20))
            gain[:, sib] *= (1.0 - red)[:, None]
        frames = np.fft.irfft(spec * gain, N_FFT, axis=1).astype(np.float32) * win
        for i, fr in enumerate(frames):
            pos = (start + i) * HOP
            out[pos:pos + N_FFT] += fr
    out /= 2.0   # finestre sqrt-hann al 75% di sovrapposizione: somma = 2
    return out[N_FFT:N_FFT + x.size]


# ---------------------------------------------------------------- dinamica
def _rms_env(x: np.ndarray, sr: int, step_s: float = 0.005) -> tuple[np.ndarray, int]:
    step = max(1, int(sr * step_s))
    n = int(np.ceil(x.size / step))
    xp = np.zeros(n * step, np.float32)
    xp[:x.size] = x
    return np.sqrt((xp.reshape(n, step) ** 2).mean(axis=1) + 1e-12), step


def compress(x: np.ndarray, sr: int, ratio: float = 3.0, attack_s: float = 0.008,
             release_s: float = 0.12, knee_db: float = 6.0) -> np.ndarray:
    """Compressore con soglia automatica (12 dB sotto il livello forte della voce)."""
    if x.size == 0:
        return x
    env, step = _rms_env(x, sr)
    env_db = 20 * np.log10(env)
    active = env_db[env_db > env_db.max() - 40]
    if active.size == 0:
        return x
    loud = np.percentile(active, 90)
    threshold = loud - 12.0
    # riduzione statica con ginocchio morbido
    over = env_db - threshold
    red = np.where(over <= -knee_db / 2, 0.0,
                   np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                            (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    # attacco / rilascio
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
    # recupero del volume: la voce forte torna al livello di prima
    makeup = 10 ** (np.percentile(red, 90) * 0.7 / 20)
    return (y * makeup).astype(np.float32)


def process_voice(voice: np.ndarray, sr: int, fx: VoiceFx) -> np.ndarray:
    """Applica gli effetti a una voce mono float32. Ritorna un nuovo array della stessa lunghezza."""
    if voice is None or voice.size == 0 or not (fx.enhance or fx.denoise):
        return voice
    x = np.nan_to_num(voice.astype(np.float32).reshape(-1))
    y = _spectral(x, sr, fx)
    if fx.enhance:
        y = compress(y, sr)
    return y.astype(np.float32)
