"""Imports any MIDI file as the piano take."""
from __future__ import annotations

from pathlib import Path

from wintrypiano.core.events import NOTE_ON
from wintrypiano.core.midifile import load_midi
from wintrypiano.errors import UserError


def import_events(path: Path, trim_start: bool = False):
    """Read a MIDI file (all channels except drums) and return (events, bpm).

    With ``trim_start`` the silence before the first note is removed.
    """
    path = Path(path)
    if not path.is_file():
        raise UserError(f"The file \"{path.name}\" does not exist.")
    try:
        events, bpm = load_midi(path, skip_drums=True)
    except UserError:
        raise
    except Exception as exc:
        raise UserError(f"\"{path.name}\" is not a valid MIDI file.") from exc
    notes = [e[0] for e in events if e[1] == NOTE_ON]
    if not notes:
        raise UserError("The MIDI file has no notes to play on the piano "
                        "(drums are ignored).")
    if trim_start:
        first = min(notes)
        events = [(max(0.0, t - first), k, a, b) for t, k, a, b in events]
    return events, bpm
