"""Track synchronisation tools: waveforms and automatic alignment."""
from __future__ import annotations

import numpy as np

ENV_RATE = 200  # samples per second of the envelope used for alignment


def peaks(audio: np.ndarray, samplerate: int, per_second: int = 100) -> np.ndarray:
    """Peaks (absolute maximum) at ``per_second`` values per second, to draw the waveform."""
    if audio is None or audio.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)
    mono = np.abs(audio).max(axis=1) if audio.ndim == 2 else np.abs(audio)
    n = int(np.ceil(mono.shape[0] * per_second / samplerate))
    bounds = np.round(np.arange(n) * samplerate / per_second).astype(np.int64)
    bounds = bounds[bounds < mono.shape[0]]
    return np.maximum.reduceat(mono, bounds).astype(np.float32)


def onset_envelope(audio: np.ndarray, samplerate: int, normalise: bool = True) -> np.ndarray:
    """Onset envelope (spectral flux), at ENV_RATE values per second.

    Measures how much the spectrum grows from one moment to the next: it is high
    when a note starts and stays low on held sounds, even when two close notes beat.
    """
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    mono = np.ascontiguousarray(mono, dtype=np.float32)
    hop = samplerate / ENV_RATE   # may not be an integer (44100 Hz): use exact positions
    win = 1 << int(np.ceil(np.log2(samplerate * 0.04)))   # ~40 ms
    n = int((mono.shape[0] - win) // hop) + 1
    if n < 2:
        return np.zeros(0, dtype=np.float64)
    window = np.hanning(win).astype(np.float32)
    # only the useful frequencies (30 Hz - 8 kHz): less work, less noise
    lo = max(1, int(30 * win / samplerate))
    hi = min(win // 2, int(8000 * win / samplerate))
    flux = np.zeros(n, dtype=np.float64)
    prev = None
    chunk = 2048
    for start in range(0, n, chunk):
        stop = min(n, start + chunk)
        starts = np.round(np.arange(start, stop) * hop).astype(np.int64)
        idx = starts[:, None] + np.arange(win)[None, :]
        frames = mono[idx] * window
        mag = np.log1p(100.0 * np.abs(np.fft.rfft(frames, axis=1)[:, lo:hi]))
        if prev is None:
            prev = mag[:1]
        both = np.concatenate([prev, mag], axis=0)
        flux[start:stop] = np.maximum(0.0, np.diff(both, axis=0)).sum(axis=1)
        prev = mag[-1:]
    # frame i covers [i*hop, i*hop+win), and with log compression the flux already
    # rises when the onset enters the window: correction measured on test notes
    flux = np.concatenate([np.zeros(int(round(0.82 * win / hop))), flux])
    return _normalise(flux) if normalise else flux


def auto_offset_ms(reference: np.ndarray, other: np.ndarray, samplerate: int,
                   max_shift_s: float = 30.0) -> tuple[float, float]:
    """Estimate how many ms to shift ``other`` (audio) so it plays in time with ``reference`` (audio).

    Returns (offset_ms, confidence 0..1). A positive offset means ``other`` must be delayed.
    """
    a = onset_envelope(reference, samplerate)
    b = onset_envelope(other, samplerate)
    if a.size < 4 or b.size < 4:
        return 0.0, 0.0
    lag, sc = _xcorr_best(a, b, int(max_shift_s * ENV_RATE))
    return lag * 1000.0 / ENV_RATE, float(max(0.0, min(1.0, sc)))


def _normalise(env: np.ndarray) -> np.ndarray:
    env = env - env.mean()
    std = env.std()
    return env / std if std > 0 else env


def _blur(env: np.ndarray, sigma_bins: float) -> np.ndarray:
    if sigma_bins < 0.5:
        return env
    half = int(3 * sigma_bins) + 1
    x = np.arange(-half, half + 1)
    k = np.exp(-0.5 * (x / sigma_bins) ** 2)
    return np.convolve(env, k / k.sum(), mode="same")


def _pool(env: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return env
    n = env.size // factor
    return env[:n * factor].reshape(n, factor).max(axis=1)


def midi_envelope(events, stretch: float = 1.0, rate: int = ENV_RATE) -> np.ndarray:
    """Onset envelope built from the MIDI notes (times divided by ``stretch``)."""
    times = np.array([t for t, kind, _a, b in events if kind == 0 and b > 0], dtype=np.float64)
    vels = np.array([b for t, kind, _a, b in events if kind == 0 and b > 0], dtype=np.float64)
    if times.size == 0:
        return np.zeros(0, dtype=np.float64)
    idx = (times / stretch * rate).astype(np.int64)
    env = np.zeros(int(idx.max()) + int(rate) + 2, dtype=np.float64)
    np.add.at(env, idx, 0.3 + vels / 127.0)
    return env


def _xcorr_best(a: np.ndarray, b: np.ndarray, max_lag: int) -> tuple[float, float]:
    """Delay (in envelope samples, fractional) to apply to ``b`` to align it with ``a``.

    Returns (delay, normalised correlation).
    """
    n = a.size + b.size
    size = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    # corr[k] = sum a[i+k]*b[i]: with k < 0, "b" plays after "a" and must move earlier
    lags = np.concatenate([np.arange(-min(max_lag, b.size), 0),
                           np.arange(0, min(max_lag, a.size) + 1)])
    values = corr[lags % size]
    best = int(np.argmax(values))
    frac = 0.0
    if 0 < best < values.size - 1:
        y0, y1, y2 = values[best - 1], values[best], values[best + 1]
        den = y0 - 2 * y1 + y2
        if den != 0:
            frac = float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5))
    norm = np.sqrt(np.sum(a * a) * np.sum(b * b))
    score = float(values[best] / norm) if norm > 0 else 0.0
    return lags[best] + frac, score


# (samples per second, blur in seconds): from coarse to fine
_LEVELS = ((50, 0.04), (ENV_RATE, 0.012))


def align_base_to_midi(events, base: np.ndarray, samplerate: int, find_speed: bool = False,
                       max_shift_s: float = 60.0, speed_range: tuple[float, float] = (0.8, 1.25),
                       progress=None):
    """Align imported audio to the MIDI notes of the piano.

    Returns (offset_ms of the imported audio, MIDI speed, confidence 0..1).
    A negative offset means the audio must move earlier (the music in the file starts
    after the notes). With ``find_speed`` it also searches for the MIDI speed (1.0 =
    unchanged, 1.05 = 5% faster) that best matches the audio: useful when the MIDI
    has a slightly different tempo than the recording.
    """
    full = onset_envelope(base, samplerate, normalise=False)
    if full.size < 4 or not any(e[1] == 0 for e in events):
        return 0.0, 1.0, 0.0
    duration = full.size / ENV_RATE
    refs = {}
    for rate, blur in _LEVELS:
        r = _pool(full, ENV_RATE // rate)
        refs[rate] = _normalise(_blur(r, blur * rate))

    def score(speed, rate, blur):
        env = midi_envelope(events, speed, rate)
        env = _normalise(_blur(env, blur * rate))
        return _xcorr_best(env, refs[rate], int(max_shift_s * rate))

    if find_speed:
        lo, hi = speed_range
        candidates = [None]
        window = None
        total = len(_LEVELS)
        for li, (rate, blur) in enumerate(_LEVELS):
            step = max(0.0001, 0.5 * blur / max(duration, 1.0))
            if window is None:
                grid = np.arange(lo, hi + step / 2, step)
            else:
                grid = np.unique(np.concatenate([np.arange(c - window, c + window + step / 2, step)
                                                 for c in candidates]))
            scored = sorted(((score(s, rate, blur)[1], float(s)) for s in grid), reverse=True)
            candidates = [s for _sc, s in scored[:6]]
            window = 2 * step
            if progress:
                progress((li + 1) / total)
        speed = candidates[0]
    else:
        speed = 1.0
    rate, blur = _LEVELS[-1]
    lag, sc = score(speed, rate, blur)
    confidence = float(max(0.0, min(1.0, sc * 1.6)))
    return lag * 1000.0 / rate, float(round(speed, 4)), confidence


def stretch_events(events, speed: float):
    """Change the speed of a MIDI take (speed > 1 = faster)."""
    if speed == 1.0:
        return list(events)
    return [(t / speed, kind, a, b) for t, kind, a, b in events]
