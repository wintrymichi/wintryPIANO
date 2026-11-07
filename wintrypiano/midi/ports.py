"""USB MIDI input with mido + python-rtmidi, tolerant of plugging and unplugging."""
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
    except Exception as exc:  # pragma: no cover - depends on the installation
        raise UserError("MIDI support (python-rtmidi) is missing. Run the installer again.") from exc
    return mido


def list_inputs() -> list[str]:
    try:
        names = _mido().get_input_names()
    except UserError:
        raise
    except Exception:
        global _warned
        if not _warned:
            log.exception("listing MIDI ports failed")
            _warned = True
        return []
    # On Windows names can repeat: remove duplicates while keeping the order
    return list(dict.fromkeys(names))


def _strip_index(name: str) -> str:
    """Windows appends a number ("Piano 1") that can change between sessions."""
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


ALL = "*"    # listen to all MIDI inputs (default)
NONE = "-"   # no input


class MidiInput:
    """Open one or all MIDI inputs and forward notes/controllers to ``sink(kind, a, b)``.

    With ``ALL`` every port is listened to at once: useful with interfaces that have
    several inputs (e.g. "ESI MIDIMATE eX 0" and "MIDIIN2 (ESI MIDIMATE eX) 1"), where
    it is not known which one the piano is connected to.
    """

    def __init__(self, sink: Callable[[int, int, int], None]):
        self.sink = sink
        self.ports: dict = {}
        self.wanted = ALL      # the user's choice (even if currently unplugged)
        self.activity = 0      # messages received (for the activity light in the GUI)
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
                log.info("first MIDI message from %r: %s", port_name, msg)
            ev = from_mido(msg)
            if ev is not None:
                self.sink(*ev)
        return callback

    def _open_port(self, name: str) -> None:
        try:
            self.ports[name] = _mido().open_input(name, callback=self._make_callback(name))
            log.info("MIDI input opened: %r", name)
        except UserError:
            raise
        except Exception as exc:
            log.warning("opening MIDI %r failed: %s", name, exc)
            raise UserError(f"Cannot open the MIDI piano \"{name}\". "
                            "It may be in use by another program: close it and try again.") from exc

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
        """Check for plugged/unplugged devices. Return a status message or None."""
        if self.wanted == NONE:
            return None
        available = list_inputs()
        msg = None
        for n in [n for n in self.ports if n not in available]:
            try:
                self.ports.pop(n).close()
            except Exception:
                pass
            msg = f"MIDI piano disconnected: {n}"
        if self.wanted == ALL:
            for n in available:
                if n not in self.ports:
                    try:
                        self._open_port(n)
                        msg = f"MIDI piano connected: {n}"
                    except UserError:
                        pass
        elif not self.ports:
            found = match_port(self.wanted, available)
            if found:
                try:
                    self._open_port(found)
                    self.wanted = found
                    msg = f"MIDI piano connected: {found}"
                except UserError:
                    pass
        return msg
