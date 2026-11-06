import numpy as np

from wintrypiano.core.events import NOTE_OFF, NOTE_ON
from wintrypiano.core.recovery import PianoJournal, VoiceJournal, clear_recovery, find_recovery


def test_recover_piano_and_voice_after_crash(tmp_path):
    folder = tmp_path / ".recovery"
    pj = PianoJournal(folder, bpm=90)
    pj.append([(0.0, NOTE_ON, 60, 80), (0.5, NOTE_OFF, 60, 0)])
    vj = VoiceJournal(folder, 48000)
    vj.append(np.ones(1000, np.float32) * 0.25)
    vj.set_offset(-15.0)
    # simulazione crash: file non chiusi, ultima riga troncata
    pj._f.write('[0.9, 0, 6')
    pj._f.flush()
    vj._f.write(b"\x00\x01")  # campione a metà
    vj._f.flush()
    rec = find_recovery(folder)
    assert rec.piano_bpm == 90
    assert rec.piano_events == [(0.0, NOTE_ON, 60, 80), (0.5, NOTE_OFF, 60, 0)]
    assert rec.voice.size == 1000 and rec.voice_samplerate == 48000 and rec.voice_offset_ms == -15.0
    pj._f.close()
    vj._f.close()
    clear_recovery(folder)
    assert find_recovery(folder).empty


def test_clean_close_leaves_nothing(tmp_path):
    folder = tmp_path / ".recovery"
    pj = PianoJournal(folder, 100)
    pj.append([(0.0, NOTE_ON, 60, 80)])
    pj.close(delete=True)
    vj = VoiceJournal(folder, 48000)
    vj.close(delete=True)
    assert find_recovery(folder).empty
