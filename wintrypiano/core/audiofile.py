"""Lettura di file audio da importare (MP3, WAV, FLAC, OGG…) e ricampionamento."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from wintrypiano.core.export import find_ffmpeg
from wintrypiano.errors import UserError

AUDIO_FILTER = "Audio (*.mp3 *.wav *.flac *.ogg *.aif *.aiff *.m4a *.aac *.wma)"


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Ricampiona (mono o multicanale) con interpolazione nel dominio della frequenza."""
    if src == dst or audio.shape[0] == 0:
        return audio.astype(np.float32, copy=False)
    n_out = int(round(audio.shape[0] * dst / src))
    out = []
    chans = audio[:, None] if audio.ndim == 1 else audio
    for c in range(chans.shape[1]):
        x = chans[:, c].astype(np.float64)
        spec = np.fft.rfft(x)
        n_bins = n_out // 2 + 1
        if n_bins <= spec.shape[0]:
            spec = spec[:n_bins]
        else:
            spec = np.concatenate([spec, np.zeros(n_bins - spec.shape[0], dtype=spec.dtype)])
        y = np.fft.irfft(spec, n_out) * (n_out / x.shape[0])
        out.append(y.astype(np.float32))
    res = np.stack(out, axis=1)
    return res[:, 0] if audio.ndim == 1 else res


def _read_with_ffmpeg(path: Path) -> tuple[np.ndarray, int]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise UserError(f"Non riesco a leggere «{path.name}». Prova a convertirlo in MP3 o WAV, "
                        "oppure installa ffmpeg (lo fa l'installer).")
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "import.wav"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            res = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
                                  "-vn", "-acodec", "pcm_f32le", str(wav)],
                                 capture_output=True, timeout=600, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UserError(f"Non riesco a leggere «{path.name}».") from exc
        if res.returncode != 0 or not wav.exists():
            raise UserError(f"Non riesco a leggere «{path.name}»: il file è danneggiato o in un formato non supportato.")
        data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    return data, sr


def read_audio(path: Path, samplerate: int) -> np.ndarray:
    """Legge un file audio e lo converte in stereo float32 a ``samplerate``."""
    path = Path(path)
    if not path.is_file():
        raise UserError(f"Il file «{path.name}» non esiste.")
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:  # formato non gestito da libsndfile (es. m4a): provo con ffmpeg
        data, sr = _read_with_ffmpeg(path)
    if data.shape[0] == 0:
        raise UserError(f"Il file «{path.name}» non contiene audio.")
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    data = data[:, :2]
    return resample(data, sr, samplerate)
