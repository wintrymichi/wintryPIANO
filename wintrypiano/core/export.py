"""Exports the mix to WAV and, if ffmpeg is available, to MP3."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from wintrypiano.errors import UserError


def find_ffmpeg() -> str | None:
    """Look for ffmpeg in PATH or next to the program."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import os

    here = Path(sys.executable).resolve().parent
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    candidates = [here / "ffmpeg.exe", here / "ffmpeg" / "bin" / "ffmpeg.exe",
                  Path(__file__).resolve().parents[2] / "ffmpeg" / "bin" / "ffmpeg.exe",
                  local / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"]
    packages = local / "Microsoft" / "WinGet" / "Packages"
    if packages.is_dir():  # ffmpeg installed with winget before the session was reopened
        candidates += sorted(packages.glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe"))
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def write_wav(audio: np.ndarray, samplerate: int, path: Path, subtype: str = "PCM_24") -> Path:
    path = Path(path)
    if path.suffix.lower() != ".wav":
        path = path.with_suffix(".wav")
    tmp = path.with_name(path.name + ".tmp")
    try:
        sf.write(str(tmp), audio, samplerate, subtype=subtype, format="WAV")
        tmp.replace(path)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise UserError(f"Cannot write the file \"{path.name}\".") from exc
    return path


def write_mp3(audio: np.ndarray, samplerate: int, path: Path, bitrate: str = "320k",
              ffmpeg: str | None = None) -> Path:
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        raise UserError("MP3 export needs ffmpeg, which is not installed. You can still export to WAV.")
    path = Path(path)
    if path.suffix.lower() != ".mp3":
        path = path.with_suffix(".mp3")
    with tempfile.TemporaryDirectory() as td:
        tmp_wav = Path(td) / "mix.wav"
        sf.write(str(tmp_wav), audio, samplerate, subtype="PCM_16")
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_wav),
               "-codec:a", "libmp3lame", "-b:a", bitrate, str(path)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=600, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UserError("ffmpeg could not create the MP3.") from exc
        if res.returncode != 0 or not path.exists():
            raise UserError("ffmpeg could not create the MP3.",
                            detail=res.stderr.decode("utf-8", "replace"))
    return path
