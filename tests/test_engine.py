"""Test del motore audio senza hardware: si chiamano direttamente le callback."""
from types import SimpleNamespace

import numpy as np

from wintrypiano.audio.engine import COUNT_IN, IDLE, PLAYING, REC_PIANO, REC_VOICE, AudioEngine, RecordingWriter
from wintrypiano.core.events import CC_SUSTAIN, CONTROL, NOTE_OFF, NOTE_ON
from wintrypiano.core.metronome import Metronome
from wintrypiano.core.recovery import PianoJournal, VoiceJournal, find_recovery
from wintrypiano.core.ringbuffer import RingBuffer
from wintrypiano.midi.demo import demo_events

SR = 48000
B = 256


def run_out(engine, blocks):
    out = np.zeros((B, 2), np.float32)
    chunks = []
    for i in range(blocks):
        engine._process_output(out, B, 1.0 + i * B / SR)
        chunks.append(out.copy())
    return np.concatenate(chunks)


def test_live_note_sounds_immediately(synth):
    e = AudioEngine(synth, SR)
    e.note_event(NOTE_ON, 69, 110)
    audio = run_out(e, 4)
    assert np.abs(audio[:B]).max() > 0.01  # già nel primo blocco dopo il tasto


def test_count_in_then_recording_timestamps(synth):
    e = AudioEngine(synth, SR)
    e.start_piano_recording(bpm=120, count_in_beats=4)  # 2 s di conto alla rovescia
    assert e.mode == COUNT_IN
    clicks = run_out(e, 10)
    assert np.abs(clicks).max() > 0.1  # il click del conto si sente
    assert e.count_in_remaining() == 4
    blocks_to_rec = int(np.ceil(2 * SR / B)) - 10
    run_out(e, blocks_to_rec + 1)
    assert e.mode == REC_PIANO
    e.note_event(NOTE_ON, 60, 100)
    run_out(e, 1)
    t_on = e.rec_queue[-1][0]
    run_out(e, 188)  # ~1 s
    e.note_event(NOTE_OFF, 60, 0)
    run_out(e, 1)
    t_off = e.rec_queue[-1][0]
    assert 0 <= t_on < 0.02
    assert abs((t_off - t_on) - 189 * B / SR) < 1e-6


def test_note_played_just_before_downbeat_is_kept(synth):
    e = AudioEngine(synth, SR)
    e.start_piano_recording(bpm=120, count_in_beats=4)  # 96000 frame di conto
    run_out(e, 96000 // B - 20)  # ~100 ms prima dell'inizio
    e.note_event(NOTE_ON, 60, 100)
    run_out(e, 1)
    assert list(e.rec_queue) == [(0.0, NOTE_ON, 60, 100)]
    # una nota suonata a metà conto non viene registrata
    e2 = AudioEngine(synth, SR)
    e2.start_piano_recording(bpm=120, count_in_beats=4)
    run_out(e2, 100)
    e2.note_event(NOTE_ON, 60, 100)
    run_out(e2, 1)
    assert len(e2.rec_queue) == 0


def test_metronome_is_not_recorded(synth):
    e = AudioEngine(synth, SR)
    e.metronome_enabled = True
    e.start_piano_recording(bpm=100, count_in_beats=0)
    run_out(e, 400)
    assert len(e.rec_queue) == 0  # solo i tasti finiscono nella take


def test_sustain_held_at_start_is_recorded(synth):
    e = AudioEngine(synth, SR)
    e.note_event(CONTROL, CC_SUSTAIN, 127)
    run_out(e, 1)
    e.start_piano_recording(100, 0)
    assert list(e.rec_queue)[0][1:] == (CONTROL, CC_SUSTAIN, 127)


def test_playback_stops_at_end(synth):
    e = AudioEngine(synth, SR)
    e.play(np.full((B * 3, 2), 0.25, np.float32))
    audio = run_out(e, 5)
    assert np.allclose(audio[:B * 3], 0.25)
    assert e.mode == IDLE


def test_voice_recording_latency_compensation(synth):
    e = AudioEngine(synth, SR)
    e.start_voice_recording(np.zeros((SR, 2), np.float32), bpm=100)
    out = np.zeros((B, 2), np.float32)
    mic = np.full((B, 1), 0.1, np.float32)
    e._process_output(out, B, 10.050)   # il piano arriva alle cuffie a 10.050 s
    e._process_input(mic, B, 10.020)    # il primo campione della voce è stato catturato a 10.020 s
    assert e.mode == REC_VOICE
    assert abs(e.voice_offset_ms() - (-30.0)) < 1e-6
    assert e.voice_ring.available() == B


def test_mic_level_and_clip_warning(synth):
    e = AudioEngine(synth, SR)
    e._process_input(np.full((B, 1), 0.3, np.float32), B, 0)
    peak, clip = e.take_mic_level()
    assert abs(peak - 0.3) < 1e-6 and not clip
    e._process_input(np.full((B, 1), 1.0, np.float32), B, 0)
    assert e.take_mic_level()[1] is True


def test_monitor_off_by_default(synth):
    e = AudioEngine(synth, SR)
    assert e.monitor_enabled is False
    e._process_input(np.full((B, 1), 0.5, np.float32), B, 0)
    assert np.abs(run_out(e, 1)).max() == 0.0
    e.monitor_enabled = True
    e._process_input(np.full((B, 1), 0.5, np.float32), B, 0)
    assert np.abs(run_out(e, 1)).max() > 0.4


def test_output_never_clips(synth):
    e = AudioEngine(synth, SR)
    e.play(np.full((B * 2, 2), 3.0, np.float32))
    assert np.abs(run_out(e, 2)).max() <= 1.0


def test_writer_journals_and_collects(tmp_path, synth):
    e = AudioEngine(synth, SR)
    pj = PianoJournal(tmp_path / "r", 100)
    vj = VoiceJournal(tmp_path / "r", SR)
    w = RecordingWriter(e, piano_journal=pj, voice_journal=vj)
    w.start()
    e.rec_queue.append((0.0, NOTE_ON, 60, 100))
    e.voice_ring.write(np.ones((1000, 1), np.float32))
    w.finish()
    assert w.events == [(0.0, NOTE_ON, 60, 100)]
    assert w.voice_audio().size == 1000
    rec = find_recovery(tmp_path / "r")  # ciò che è finito su disco
    assert rec.piano_events and rec.voice.size == 1000
    pj.close()
    vj.close()


def test_demo_mode_full_take(synth):
    """Il flusso completo con le note simulate: registrazione, take, render."""
    e = AudioEngine(synth, SR)
    e.start_piano_recording(bpm=120, count_in_beats=0)
    evs = demo_events(bpm=120, bars=2)
    pos = 0
    out = np.zeros((B, 2), np.float32)
    for t, kind, a, b in evs:
        while pos / SR < t:
            e._process_output(out, B, 0)
            pos += B
        e.note_event(kind, a, b)
    e._process_output(out, B, 0)
    take = list(e.rec_queue)
    assert len(take) == len(evs)
    assert sum(1 for x in take if x[1] == NOTE_ON) == sum(1 for x in evs if x[1] == NOTE_ON)
    audio = synth.render(take)
    assert audio.shape[0] > 3.5 * SR and np.abs(audio).max() > 0.05


def test_ringbuffer_wraps():
    r = RingBuffer(10, 1)
    r.write(np.arange(7, dtype=np.float32)[:, None])
    out = np.zeros((5, 1), np.float32)
    r.read_into(out)
    r.write(np.arange(7, 14, dtype=np.float32)[:, None])
    assert r.read_all()[:, 0].tolist() == list(range(5, 14))
    assert r.write(np.zeros((20, 1), np.float32)) == 10 and r.overflows == 1


def test_metronome_click_positions():
    m = Metronome(SR, bpm=120)  # un battito ogni 24000 campioni
    out = np.zeros((SR * 2, 2), np.float32)
    for i in range(0, SR * 2, B):
        n = min(B, SR * 2 - i)
        m.render_into(out[i:i + n], n, 1.0)
    for k in range(4):
        start = k * 24000
        assert np.abs(out[start + 1:start + 200, 0]).max() > 0.1
        if k:
            assert not out[start - 2000:start, 0].any()
    # accento sul primo battito della battuta
    assert out[1:200, 0].max() != out[24001:24200, 0].max()


def test_play_and_sing_in_one_take(synth):
    """Suona e canta: la voce parte con la take del piano ed è allineata a essa."""
    e = AudioEngine(synth, SR)
    e.start_piano_recording(bpm=120, count_in_beats=1, with_voice=True)  # 24000 frame di conto
    out = np.zeros((B, 2), np.float32)
    mic = np.full((B, 1), 0.2, np.float32)
    t = 5.0
    # durante il conto alla rovescia il microfono non viene registrato
    while e.mode == COUNT_IN or (e.mode == REC_PIANO and not e._capture):
        e._process_input(mic, B, t - 0.010)
        e._process_output(out, B, t + 0.020)
        t += B / SR
    assert e.voice_ring.available() == 0
    assert e.mode == REC_PIANO and e._capture
    dac = e._dac_time
    e.note_event(NOTE_ON, 64, 100)
    for _ in range(10):
        e._process_input(mic, B, t - 0.010)
        e._process_output(out, B, t + 0.020)
        t += B / SR
    assert e.voice_ring.available() == 10 * B
    assert e.rec_queue[0][1:] == (NOTE_ON, 64, 100)
    # primo campione della voce catturato 30 ms prima che il primo blocco della take arrivi alle cuffie
    assert abs(e.voice_offset_ms() - ((e._adc_time - dac) * 1000)) < 1e-9
    assert -31 < e.voice_offset_ms() < -29 + 1000 * B / SR
    e.stop()
    assert e._with_voice is False


def test_piano_only_recording_does_not_capture_voice(synth):
    e = AudioEngine(synth, SR)
    e.start_piano_recording(bpm=120, count_in_beats=0)
    out = np.zeros((B, 2), np.float32)
    for _ in range(5):
        e._process_input(np.full((B, 1), 0.2, np.float32), B, 0)
        e._process_output(out, B, 0)
    assert e.voice_ring.available() == 0
