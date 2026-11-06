"""Ingresso MIDI USB con mido + python-rtmidi, tollerante a collega/scollega."""
from __future__ import annotations

import logging
from typing import Callable

from wintrypiano.core.events import from_mido
from wintrypiano.errors import UserError

log = logging.getLogger(__name__)
_warned = False


def _mido():
    import mido  # noqa: WPS433

    try:
        mido.set_backend("mido.backends.rtmidi", load=True)
    except Exception as exc:  # pragma: no cover - dipende dall'installazione
        raise UserError("Manca il supporto MIDI (python-rtmidi). Esegui di nuovo l'installer.") from exc
    return mido


def list_inputs() -> list[str]:
    try:
        names = _mido().get_input_names()
    except UserError:
        raise
    except Exception:
        global _warned
        if not _warned:
            log.exception("elenco porte MIDI fallito")
            _warned = True
        return []
    # Su Windows i nomi possono ripetersi: rimuovo i duplicati mantenendo l'ordine
    return list(dict.fromkeys(names))


def _strip_index(name: str) -> str:
    """Windows aggiunge un numero finale ("Piano 1") che cambia tra una sessione e l'altra."""
    parts = name.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return name


def match_port(wanted: str, available: list[str]) -> str | None:
    if not wanted:
        return None
    if wanted in available:
        return wanted
    base = _strip_index(wanted)
    for name in available:
        if _strip_index(name) == base:
            return name
    return None


class MidiInput:
    """Apre una porta MIDI e inoltra note/controlli a ``sink(tipo, a, b)``."""

    def __init__(self, sink: Callable[[int, int, int], None]):
        self.sink = sink
        self.port = None
        self.name = ""
        self.wanted = ""   # porta scelta dall'utente (anche se ora scollegata)

    @property
    def connected(self) -> bool:
        return self.port is not None

    def _callback(self, msg) -> None:
        ev = from_mido(msg)
        if ev is not None:
            self.sink(*ev)

    def open(self, name: str) -> None:
        self.close()
        self.wanted = name
        if not name:
            return
        try:
            self.port = _mido().open_input(name, callback=self._callback)
            self.name = name
        except UserError:
            raise
        except Exception as exc:
            self.port = None
            raise UserError(f"Non riesco ad aprire il piano MIDI «{name}». "
                            "Forse è usato da un altro programma.") from exc

    def close(self) -> None:
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.name = ""

    def poll(self) -> str | None:
        """Controlla collegamenti/scollegamenti. Ritorna un messaggio di stato o None."""
        available = list_inputs()
        if self.port is not None and self.name not in available:
            self.close()
            return f"Piano MIDI scollegato: {self.wanted}"
        if self.port is None and self.wanted:
            found = match_port(self.wanted, available)
            if found:
                try:
                    self.open(found)
                    self.wanted = found
                    return f"Piano MIDI collegato: {found}"
                except UserError:
                    return None
        return None
