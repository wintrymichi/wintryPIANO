import numpy as np
import pytest

from wintrypiano.core.events import CC_SUSTAIN, CONTROL, NOTE_OFF, NOTE_ON
from wintrypiano.core.synth import LoadedFont, PianoSynth
from wintrypiano.errors import UserError

SR = 48000


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def seg(a, t0, t1):
    return a[int(t0 * SR):int(t1 * SR)]


def test_render_pitch_and_length(synth):
    audio = synth.render([(0.0, NOTE_ON, 69, 100), (0.5, NOTE_OFF, 69, 0)])
    assert audio.dtype == np.float32 and audio.shape[1] == 2
    s = seg(audio, 0.1, 0.3)[:, 0]
    crossings = int(((s[:-1] < 0) & (s[1:] >= 0)).sum())
    assert crossings / 0.2 == pytest.approx(440, abs=10)
    assert audio.shape[0] < SR * 1.5  # tail cut after the release


def test_velocity_changes_loudness(synth):
    soft = synth.render([(0.0, NOTE_ON, 60, 30), (0.5, NOTE_OFF, 60, 0)])
    loud = synth.render([(0.0, NOTE_ON, 60, 120), (0.5, NOTE_OFF, 60, 0)])
    assert rms(seg(loud, 0.1, 0.4)) > rms(seg(soft, 0.1, 0.4)) * 2


def test_sustain_pedal_holds_notes(synth):
    no_pedal = synth.render([(0.0, NOTE_ON, 60, 100), (0.3, NOTE_OFF, 60, 0), (2.0, NOTE_ON, 30, 1),
                             (2.01, NOTE_OFF, 30, 0)])
    pedal = synth.render([(0.0, CONTROL, CC_SUSTAIN, 127), (0.0, NOTE_ON, 60, 100), (0.3, NOTE_OFF, 60, 0),
                          (1.5, CONTROL, CC_SUSTAIN, 0), (2.0, NOTE_ON, 30, 1), (2.01, NOTE_OFF, 30, 0)])
    assert rms(seg(no_pedal, 1.0, 1.4)) < 1e-3
    assert rms(seg(pedal, 1.0, 1.4)) > 0.05
    assert rms(seg(pedal, 1.9, 1.99)) < 1e-3  # release after the pedal


def test_render_matches_live_rendering(synth):
    """The offline render uses the same engine as the live sound: same result."""
    events = [(0.0, NOTE_ON, 60, 90), (0.25, NOTE_ON, 67, 70), (0.5, NOTE_OFF, 60, 0), (0.75, NOTE_OFF, 67, 0)]
    offline = synth.render(events, tail_s=0.5)
    # "live" simulation: events applied at block boundaries like the callback does
    block = 240  # 5 ms: the event times fall on block boundaries
    live = np.zeros_like(offline)
    synth.all_off()
    with synth.lock:
        i = 0
        for pos in range(0, offline.shape[0], block):
            while i < len(events) and int(round(events[i][0] * SR)) <= pos:
                synth.handle(*events[i][1:])
                i += 1
            n = min(block, offline.shape[0] - pos)
            live[pos:pos + n] = synth.generate(n)
    # TinySoundFont updates the envelopes per block, so small differences
    # depend only on the block size, not on the sound quality.
    assert rms(live - offline) < 0.02 * rms(offline)
    assert np.corrcoef(live[:, 0], offline[:, 0])[0, 1] > 0.999


def test_render_without_font_raises():
    with pytest.raises(UserError):
        PianoSynth(SR).render([(0.0, NOTE_ON, 60, 100)])


def test_invalid_soundfont_file(tmp_path):
    bad = tmp_path / "bad.sf2"
    bad.write_bytes(b"not a soundfont")
    with pytest.raises(UserError):
        LoadedFont(bad, SR)
    with pytest.raises(UserError):
        LoadedFont(tmp_path / "missing.sf2", SR)
