import shutil

import numpy as np
import pytest
import soundfile as sf

from wintrypiano.core.events import NOTE_OFF, NOTE_ON
from wintrypiano.core.export import find_ffmpeg, write_mp3, write_wav
from wintrypiano.core.mixer import TARGET_PEAK, MixSettings, mix_tracks, prevent_clipping, shift
from wintrypiano.core.project import Project
from wintrypiano.errors import UserError

SR = 48000


def test_shift():
    a = np.arange(10, dtype=np.float32)
    assert shift(a, 3)[:3].tolist() == [0, 0, 0] and shift(a, 3).shape[0] == 13
    assert shift(a, -2)[0] == 2


def test_voice_offset_aligns_voice():
    piano = np.zeros((SR, 2), np.float32)
    voice = np.zeros(SR, np.float32)
    voice[1000] = 0.5  # impulso
    s = MixSettings(piano_volume=1, voice_volume=1, voice_offset_ms=-10)  # anticipa di 480 campioni
    mix, _ = mix_tracks(piano, voice, SR, s)
    assert int(np.argmax(np.abs(mix[:, 0]))) == 1000 - 480


def test_volumes_are_independent():
    piano = np.full((SR, 2), 0.1, np.float32)
    voice = np.full(SR, 0.1, np.float32)
    only_piano, _ = mix_tracks(piano, voice, SR, MixSettings(piano_volume=1, voice_volume=0))
    assert np.allclose(only_piano, 0.1)
    only_voice, _ = mix_tracks(piano, voice, SR, MixSettings(piano_volume=0, voice_volume=0.5))
    assert np.allclose(only_voice, 0.05)


def test_no_clipping_in_final_mix():
    piano = np.full((SR, 2), 0.9, np.float32)
    voice = np.full(SR, 0.9, np.float32)
    mix, gain = mix_tracks(piano, voice, SR, MixSettings(piano_volume=1, voice_volume=1))
    assert gain < 1
    assert np.max(np.abs(mix)) <= TARGET_PEAK + 1e-6


def test_quiet_mix_is_not_changed():
    a = np.full((100, 2), 0.2, np.float32)
    out, gain = prevent_clipping(a.copy())
    assert gain == 1.0 and np.allclose(out, a)


def test_voice_reverb_adds_tail():
    voice = np.zeros(SR // 2, np.float32)
    voice[0] = 0.8
    dry, _ = mix_tracks(None, voice, SR, MixSettings(voice_reverb=False))
    wet, _ = mix_tracks(None, voice, SR, MixSettings(voice_reverb=True))
    assert wet.shape[0] > dry.shape[0]
    assert np.abs(wet[SR // 10:SR // 2]).max() > 1e-3


def test_render_and_export_full_project(tmp_path, synth):
    proj = Project.create(tmp_path / "song")
    proj.save_piano_take([(0.0, NOTE_ON, 60, 120), (0.0, NOTE_ON, 64, 120), (0.0, NOTE_ON, 67, 127),
                          (1.0, NOTE_OFF, 60, 0), (1.0, NOTE_OFF, 64, 0), (1.0, NOTE_OFF, 67, 0)])
    voice = (np.sin(2 * np.pi * 220 * np.arange(SR) / SR) * 0.99).astype(np.float32)
    proj.save_voice_take(voice, SR, -5.0)
    piano = synth.render(proj.load_piano_take())
    v, vsr = proj.load_voice_take()
    proj.settings.piano_volume = 1.0
    proj.settings.voice_volume = 1.0
    mix, _ = mix_tracks(piano, v, SR, proj.mix_settings())
    out = write_wav(mix, SR, tmp_path / "mix.wav")
    data, sr = sf.read(str(out))
    assert sr == SR and data.shape[1] == 2
    assert np.max(np.abs(data)) <= TARGET_PEAK + 1e-3
    assert data.shape[0] >= SR


def test_mp3_without_ffmpeg_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr("wintrypiano.core.export.find_ffmpeg", lambda: None)
    with pytest.raises(UserError) as e:
        write_mp3(np.zeros((100, 2), np.float32), SR, tmp_path / "x.mp3")
    assert "ffmpeg" in e.value.message


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg non installato")
def test_mp3_export(tmp_path):
    a = (np.sin(np.arange(SR) / 20) * 0.5).astype(np.float32)
    out = write_mp3(np.stack([a, a], 1), SR, tmp_path / "x.mp3")
    assert out.stat().st_size > 1000
