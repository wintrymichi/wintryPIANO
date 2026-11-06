"""Import di MIDI e audio, base nel mix e allineamento automatico."""
import mido
import numpy as np
import pytest
import soundfile as sf

from wintrypiano.core import align
from wintrypiano.core.audiofile import read_audio, resample
from wintrypiano.core.events import NOTE_ON
from wintrypiano.core.midi_import import import_events
from wintrypiano.core.midifile import load_midi
from wintrypiano.core.mixer import MixSettings, combine, mix_tracks
from wintrypiano.core.project import Project
from wintrypiano.errors import TakeExistsError, UserError
from wintrypiano.midi.demo import demo_events

SR = 48000


def _song(seed=3, bars=8, bpm=100):
    return demo_events(bpm=bpm, bars=bars, seed=seed)


# ------------------------------------------------------------------ file audio
def test_read_wav_mono_resampled_to_stereo(tmp_path):
    t = np.arange(44100) / 44100
    sf.write(tmp_path / "a.wav", 0.5 * np.sin(2 * np.pi * 440 * t), 44100)
    audio = read_audio(tmp_path / "a.wav", SR)
    assert audio.shape == (SR, 2) and audio.dtype == np.float32
    # la frequenza resta 440 Hz dopo il ricampionamento
    spec = np.abs(np.fft.rfft(audio[:, 0]))
    assert abs(np.argmax(spec) * SR / audio.shape[0] - 440) < 2


def test_read_mp3(tmp_path):
    t = np.arange(SR * 2) / SR
    data = 0.4 * np.sin(2 * np.pi * 330 * t)
    try:
        sf.write(tmp_path / "a.mp3", np.stack([data, data], 1), SR, format="MP3")
    except Exception:  # libsndfile senza encoder MP3
        pytest.skip("libsndfile senza supporto MP3")
    audio = read_audio(tmp_path / "a.mp3", SR)
    assert audio.shape[1] == 2 and abs(audio.shape[0] - SR * 2) < SR * 0.1
    assert 0.3 < np.max(np.abs(audio)) < 0.5


def test_read_bad_file_is_friendly(tmp_path):
    p = tmp_path / "rotto.mp3"
    p.write_bytes(b"non sono un mp3")
    with pytest.raises(UserError):
        read_audio(p, SR)
    with pytest.raises(UserError):
        read_audio(tmp_path / "manca.wav", SR)


def test_resample_length():
    x = np.random.default_rng(0).standard_normal((44100, 2)).astype(np.float32)
    assert resample(x, 44100, 48000).shape == (48000, 2)
    assert resample(x, 48000, 48000) is not None


# ------------------------------------------------------------------ import MIDI
def _write_midi(path, with_drums=True, bpm=90, lead_s=0.0):
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    first = int(mido.second2tick(lead_s, 480, mido.bpm2tempo(bpm)))
    tr.append(mido.Message("program_change", program=40, channel=1, time=first))
    for i in range(8):
        tr.append(mido.Message("note_on", note=60 + i, velocity=90, channel=1, time=0 if i == 0 else 240))
        if with_drums:
            tr.append(mido.Message("note_on", note=36, velocity=100, channel=9, time=0))
            tr.append(mido.Message("note_off", note=36, velocity=0, channel=9, time=10))
        tr.append(mido.Message("note_off", note=60 + i, velocity=0, channel=1, time=200))
    mid.save(path)


def test_import_midi_skips_drums_and_takes_bpm(tmp_path):
    _write_midi(tmp_path / "canzone.mid", bpm=90)
    proj = Project.create(tmp_path / "p", "p")
    n = proj.import_midi(tmp_path / "canzone.mid")
    assert n == 8
    events, bpm = load_midi(proj.piano_path)
    assert {e[2] for e in events if e[1] == NOTE_ON} == set(range(60, 68))
    assert round(bpm) == 90 and proj.settings.bpm == 90
    with pytest.raises(TakeExistsError):
        proj.import_midi(tmp_path / "canzone.mid")
    assert proj.import_midi(tmp_path / "canzone.mid", overwrite=True) == 8


def test_import_midi_without_notes(tmp_path):
    mid = mido.MidiFile()
    mid.tracks.append(mido.MidiTrack([mido.Message("note_on", note=36, velocity=100, channel=9)]))
    mid.save(tmp_path / "batteria.mid")
    proj = Project.create(tmp_path / "p", "p")
    with pytest.raises(UserError):
        proj.import_midi(tmp_path / "batteria.mid")
    assert not proj.has_piano()


def test_import_events_keeps_leading_silence_option(tmp_path):
    _write_midi(tmp_path / "c.mid", with_drums=False, lead_s=2.0)
    events, _bpm = import_events(tmp_path / "c.mid", trim_start=False)
    assert min(e[0] for e in events if e[1] == NOTE_ON) == pytest.approx(2.0, abs=0.01)
    events, _bpm = import_events(tmp_path / "c.mid", trim_start=True)
    assert min(e[0] for e in events if e[1] == NOTE_ON) == pytest.approx(0.0, abs=0.001)


# ------------------------------------------------------------------ base nel progetto
def test_base_saved_and_reloaded(tmp_path):
    proj = Project.create(tmp_path / "p", "p")
    audio = (np.random.default_rng(1).standard_normal((SR, 2)) * 0.1).astype(np.float32)
    proj.save_base(audio, SR, "canzone.mp3")
    assert proj.has_base() and proj.settings.base_name == "canzone.mp3"
    with pytest.raises(TakeExistsError):
        proj.save_base(audio, SR, "altra.mp3")
    proj.settings.base_offset_ms = 123.0
    proj.save()
    again = Project.open(proj.folder)
    back, sr = again.load_base()
    assert sr == SR and np.allclose(back, audio, atol=1e-4)
    assert again.mix_settings().base_offset_ms == 123.0
    again.remove_base()
    assert not again.has_base() and again.settings.base_name == ""


def test_mix_with_base_offsets():
    piano = np.zeros((SR, 2), np.float32)
    piano[0] = 0.5
    base = np.zeros((SR, 2), np.float32)
    base[0] = 0.25
    s = MixSettings(piano_volume=1, base_volume=1, base_offset_ms=100)
    out, lead = combine(piano, None, SR, s, base)
    assert lead == 0 and out[0, 0] == 0.5 and out[4800, 0] == 0.25
    # base che parte prima del piano: niente viene tagliato, tutto slitta in avanti
    s.base_offset_ms = -100
    out, lead = combine(piano, None, SR, s, base)
    assert lead == 4800 and out[0, 0] == 0.25 and out[4800, 0] == 0.5
    # la voce resta agganciata al piano
    voice = np.zeros(SR, np.float32)
    voice[0] = 0.125
    s.voice_offset_ms = 0
    s.voice_volume = 1
    out, lead = combine(piano, voice, SR, s, base)
    assert out[4800, 0] == pytest.approx(0.625)
    mix, gain = mix_tracks(piano, voice, SR, s, base)
    assert np.max(np.abs(mix)) <= 10 ** (-1 / 20) + 1e-6


# ------------------------------------------------------------------ allineamento
def test_auto_align_finds_shift(synth):
    events = _song()
    piano = synth.render(events)
    for shift_ms in (350.0, -620.0):
        n = int(round(abs(shift_ms) * SR / 1000))
        if shift_ms > 0:
            base = np.concatenate([np.zeros((n, 2), np.float32), piano])
        else:
            base = piano[n:]
        base = base + np.random.default_rng(2).standard_normal(base.shape).astype(np.float32) * 0.003
        off, conf = align.auto_offset_ms(piano, base, SR)
        assert off == pytest.approx(-shift_ms, abs=8), off
        off, speed, conf = align.align_base_to_midi(events, base, SR)
        assert off == pytest.approx(-shift_ms, abs=15), off
        assert speed == 1.0 and conf > 0.3


def test_auto_align_finds_speed(synth):
    events = _song(bars=12)
    # la base è la stessa musica suonata il 4% più lenta e con 1,5 s di introduzione
    slow = align.stretch_events(events, 1 / 1.04)
    base = synth.render([(t + 1.5, k, a, b) for t, k, a, b in slow])
    off, speed, conf = align.align_base_to_midi(events, base, SR, find_speed=True)
    # il MIDI va rallentato del 4% (velocità 0.96…) e la base anticipata di 1,5 s
    assert speed == pytest.approx(1 / 1.04, abs=0.004)
    assert off == pytest.approx(-1500, abs=25)


def test_peaks_resolution():
    audio = np.zeros((SR * 2, 2), np.float32)
    audio[SR] = 1.0
    p = align.peaks(audio, SR, per_second=100)
    assert p.shape[0] == 200 and int(np.argmax(p)) == 100
