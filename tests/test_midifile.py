import mido
import pytest

from wintrypiano.core.events import CONTROL, NOTE_OFF, NOTE_ON
from wintrypiano.core.midifile import load_midi, save_midi
from wintrypiano.errors import UserError


@pytest.mark.parametrize("bpm", [60.0, 100.0, 137.0])
def test_roundtrip_keeps_timing_velocity_and_pedal(tmp_path, bpm):
    events = [
        (0.0, CONTROL, 64, 127),
        (0.01, NOTE_ON, 60, 33),
        (0.2513, NOTE_ON, 64, 127),
        (1.0, NOTE_OFF, 60, 0),
        (1.5, NOTE_OFF, 64, 0),
        (2.75, CONTROL, 64, 0),
    ]
    path = tmp_path / "piano.mid"
    save_midi(events, path, bpm=bpm)
    loaded, loaded_bpm = load_midi(path)
    assert loaded_bpm == pytest.approx(bpm, abs=0.01)
    assert len(loaded) == len(events)
    tick = 60.0 / bpm / 960
    for (t1, k1, a1, b1), (t2, k2, a2, b2) in zip(events, loaded):
        assert (k1, a1, b1) == (k2, a2, b2)
        assert t2 == pytest.approx(t1, abs=tick)


def test_file_is_standard_midi(tmp_path):
    path = tmp_path / "x.mid"
    save_midi([(0.0, NOTE_ON, 60, 90), (0.5, NOTE_OFF, 60, 0)], path, 120)
    mid = mido.MidiFile(str(path))
    types = [m.type for m in mid.tracks[0]]
    assert "note_on" in types and "note_off" in types and "set_tempo" in types


def test_corrupt_midi_raises_user_error(tmp_path):
    p = tmp_path / "broken.mid"
    p.write_bytes(b"MThd\x00\x00garbage")
    with pytest.raises(UserError):
        load_midi(p)
