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


ALL = "*"    # ascolta tutti gli ingressi MIDI (predefinito)
NONE = "-"   # nessun ingresso


class MidiInput:
    """Apre uno o tutti gli ingressi MIDI e inoltra note/controlli a ``sink(tipo, a, b)``.

    Con ``ALL`` ascolta tutte le porte insieme: utile con interfacce che hanno più
    ingressi (es. "ESI MIDIMATE eX 0" e "MIDIIN2 (ESI MIDIMATE eX) 1"), dove non si
    sa a quale è collegato il piano.
    """

    def __init__(self, sink: Callable[[int, int, int], None]):
        self.sink = sink
        self.ports: dict = {}
        self.wanted = ALL      # scelta dell'utente (anche se ora scollegata)
        self.activity = 0      # messaggi ricevuti (per la spia nella GUI)
        self._seen: set = set()

    @property
    def connected(self) -> bool:
        return bool(self.ports)

    @property
    def name(self) -> str:
        return ", ".join(self.ports)

    def _make_callback(self, port_name: str):
        def callback(msg) -> None:
            self.activity += 1
            if port_name not in self._seen:
                self._seen.add(port_name)
                log.info("primo messaggio MIDI da %r: %s", port_name, msg)
            ev = from_mido(msg)
            if ev is not None:
                self.sink(*ev)
        return callback

    def _open_port(self, name: str) -> None:
        try:
            self.ports[name] = _mido().open_input(name, callback=self._make_callback(name))
            log.info("ingresso MIDI aperto: %r", name)
        except UserError:
            raise
        except Exception as exc:
            log.warning("apertura MIDI %r fallita: %s", name, exc)
            raise UserError(f"Non riesco ad aprire il piano MIDI «{name}». "
                            "Forse è usato da un altro programma: chiudilo e riprova.") from exc

    def open(self, name: str) -> None:
        self.close()
        self.wanted = name or NONE
        if self.wanted == NONE:
            return
        if self.wanted == ALL:
            errors = []
            names = list_inputs()
            for n in names:
                try:
                    self._open_port(n)
                except UserError as exc:
                    errors.append(exc)
            if names and not self.ports and errors:
                raise errors[0]
            return
        self._open_port(self.wanted)

    def close(self) -> None:
        for port in self.ports.values():
            try:
                port.close()
            except Exception:
                pass
        self.ports = {}

    def poll(self) -> str | None:
        """Controlla collegamenti/scollegamenti. Ritorna un messaggio di stato o None."""
        if self.wanted == NONE:
            return None
        available = list_inputs()
        msg = None
        for n in [n for n in self.ports if n not in available]:
            try:
                self.ports.pop(n).close()
            except Exception:
                pass
            msg = f"Piano MIDI scollegato: {n}"
        if self.wanted == ALL:
            for n in available:
                if n not in self.ports:
                    try:
                        self._open_port(n)
                        msg = f"Piano MIDI collegato: {n}"
                    except UserError:
                        pass
        elif not self.ports:
            found = match_port(self.wanted, available)
            if found:
                try:
                    self._open_port(found)
                    self.wanted = found
                    msg = f"Piano MIDI collegato: {found}"
                except UserError:
                    pass
        return msg
