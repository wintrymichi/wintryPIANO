"""Ingressi MIDI senza hardware: mido viene sostituito da un finto backend."""
import mido
import pytest

from wintrypiano.core.events import CONTROL, NOTE_OFF, NOTE_ON
from wintrypiano.errors import UserError
from wintrypiano.midi import ports


class FakePort:
    def __init__(self, name, callback):
        self.name, self.callback, self.closed = name, callback, False

    def close(self):
        self.closed = True


class FakeMido:
    def __init__(self, names, busy=()):
        self.names = list(names)
        self.busy = set(busy)
        self.opened = {}

    def get_input_names(self):
        return list(self.names)

    def open_input(self, name, callback):
        if name in self.busy:
            raise OSError("in uso")
        port = FakePort(name, callback)
        self.opened[name] = port
        return port


@pytest.fixture
def fake(monkeypatch):
    f = FakeMido(["ESI MIDIMATE eX 0", "MIDIIN2 (ESI MIDIMATE eX) 1"])
    monkeypatch.setattr(ports, "_mido", lambda: f)
    return f


def test_all_inputs_receive_notes_from_any_port(fake):
    got = []
    m = ports.MidiInput(lambda *ev: got.append(ev))
    m.open(ports.ALL)
    assert set(m.ports) == set(fake.names)
    fake.opened["MIDIIN2 (ESI MIDIMATE eX) 1"].callback(mido.Message("note_on", note=60, velocity=90))
    fake.opened["ESI MIDIMATE eX 0"].callback(mido.Message("note_on", note=60, velocity=0))
    fake.opened["ESI MIDIMATE eX 0"].callback(mido.Message("control_change", control=64, value=127, channel=5))
    assert got == [(NOTE_ON, 60, 90), (NOTE_OFF, 60, 0), (CONTROL, 64, 127)]
    assert m.activity == 3


def test_hotplug_with_all_inputs(fake):
    m = ports.MidiInput(lambda *ev: None)
    m.open(ports.ALL)
    fake.names.remove("ESI MIDIMATE eX 0")
    assert "scollegato" in m.poll()
    assert list(m.ports) == ["MIDIIN2 (ESI MIDIMATE eX) 1"]
    fake.names.append("ESI MIDIMATE eX 0")
    assert "collegato" in m.poll()
    assert len(m.ports) == 2


def test_single_port_reconnects_with_new_index(fake):
    m = ports.MidiInput(lambda *ev: None)
    m.open("ESI MIDIMATE eX 0")
    fake.names = ["MIDIIN2 (ESI MIDIMATE eX) 0"]
    m.poll()
    assert not m.ports
    fake.names = ["MIDIIN2 (ESI MIDIMATE eX) 0", "ESI MIDIMATE eX 1"]
    m.poll()
    assert list(m.ports) == ["ESI MIDIMATE eX 1"]


def test_busy_port_gives_clear_error(fake):
    fake.busy.add("ESI MIDIMATE eX 0")
    m = ports.MidiInput(lambda *ev: None)
    with pytest.raises(UserError) as e:
        m.open("ESI MIDIMATE eX 0")
    assert "altro programma" in e.value.message
    m.open(ports.ALL)  # con "tutti" la porta libera si apre comunque
    assert list(m.ports) == ["MIDIIN2 (ESI MIDIMATE eX) 1"]


def test_none_opens_nothing(fake):
    m = ports.MidiInput(lambda *ev: None)
    m.open(ports.NONE)
    assert not m.ports and m.poll() is None


def test_old_settings_switch_to_all_midi_inputs(tmp_path):
    import json

    from wintrypiano.config import Config

    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"midi_input": "ESI MIDIMATE eX 0"}), encoding="utf-8")
    assert Config.load(p).midi_input == ports.ALL
    cfg = Config(midi_input="ESI MIDIMATE eX 0")
    cfg.save(p)
    assert Config.load(p).midi_input == "ESI MIDIMATE eX 0"  # scelta esplicita nella nuova versione
