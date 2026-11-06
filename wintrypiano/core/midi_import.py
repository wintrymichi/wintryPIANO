"""Import di un file MIDI qualsiasi come take del pianoforte."""
from __future__ import annotations

from pathlib import Path

from wintrypiano.core.events import NOTE_ON
from wintrypiano.core.midifile import load_midi
from wintrypiano.errors import UserError


def import_events(path: Path, trim_start: bool = False):
    """Legge un MIDI (tutti i canali tranne la batteria) e ritorna (eventi, bpm).

    Con ``trim_start`` toglie il silenzio prima della prima nota.
    """
    path = Path(path)
    if not path.is_file():
        raise UserError(f"Il file «{path.name}» non esiste.")
    try:
        events, bpm = load_midi(path, skip_drums=True)
    except UserError:
        raise
    except Exception as exc:
        raise UserError(f"«{path.name}» non è un file MIDI valido.") from exc
    notes = [e[0] for e in events if e[1] == NOTE_ON]
    if not notes:
        raise UserError("Il file MIDI non contiene note da suonare col pianoforte "
                        "(la batteria viene ignorata).")
    if trim_start:
        first = min(notes)
        events = [(max(0.0, t - first), k, a, b) for t, k, a, b in events]
    return events, bpm
