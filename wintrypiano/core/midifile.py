"""Saves and loads the piano take as a standard MIDI file."""
from __future__ import annotations

from pathlib import Path

import mido

from wintrypiano.core.events import CONTROL, NOTE_OFF, NOTE_ON
from wintrypiano.errors import UserError

TICKS_PER_BEAT = 960


def save_midi(events, path: Path, bpm: float = 120.0) -> None:
    """Write ``(t, kind, a, b)`` events to a type 0 MIDI file."""
    tempo = mido.bpm2tempo(bpm)
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    track.append(mido.MetaMessage("track_name", name="Piano", time=0))
    track.append(mido.Message("program_change", program=0, channel=0, time=0))
    last_tick = 0
    for t, kind, a, b in sorted(events, key=lambda e: e[0]):
        tick = int(round(mido.second2tick(max(0.0, t), TICKS_PER_BEAT, tempo)))
        delta = max(0, tick - last_tick)
        last_tick += delta
        if kind == NOTE_ON:
            msg = mido.Message("note_on", note=a, velocity=max(1, min(127, b)), time=delta)
        elif kind == NOTE_OFF:
            msg = mido.Message("note_off", note=a, velocity=0, time=delta)
        elif kind == CONTROL:
            msg = mido.Message("control_change", control=a, value=b, time=delta)
        else:
            continue
        track.append(msg)
    track.append(mido.MetaMessage("end_of_track", time=0))
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    mid.save(str(tmp))
    tmp.replace(path)


def load_midi(path: Path, skip_drums: bool = False):
    """Read a MIDI file and return (events, bpm).

    With ``skip_drums`` channel 10 (drums) is ignored, since played on a piano it
    would give wrong notes. All other channels are played on the piano.
    """
    from wintrypiano.core.events import from_mido

    try:
        mid = mido.MidiFile(str(path))
    except (OSError, EOFError, ValueError, KeyError) as exc:
        raise UserError(f"The MIDI file \"{Path(path).name}\" is damaged or unreadable.") from exc
    bpm = 120.0
    events = []
    t = 0.0
    tempo_found = False
    for msg in mid:  # iterating already converts deltas to seconds
        t += msg.time
        if msg.is_meta:
            if msg.type == "set_tempo" and not tempo_found:
                bpm = mido.tempo2bpm(msg.tempo)
                tempo_found = True
            continue
        if skip_drums and getattr(msg, "channel", None) == 9:
            continue
        ev = from_mido(msg)
        if ev is not None:
            events.append((t, *ev))
    return events, round(bpm, 3)
