"""Prova del flusso completo nella GUI (modalità demo) con un dispositivo audio qualsiasi.

Viene saltato se non c'è un dispositivo audio o se Qt non è disponibile.
"""
import os
import time

import numpy as np
import pytest
import soundfile as sf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _have_audio():
    try:
        from wintrypiano.audio import devices
        return any(d.max_output > 0 for d in devices.all_devices())
    except Exception:
        return False


qt = pytest.importorskip("PySide6.QtWidgets")
pytestmark = pytest.mark.skipif(not _have_audio(), reason="nessun dispositivo audio")


def _wait(app, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_full_flow_in_demo_mode(tmp_path, sf2_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from wintrypiano.audio.engine import IDLE, REC_PIANO, REC_VOICE
    from wintrypiano.config import Config
    from wintrypiano.core.project import Project
    from wintrypiano.gui import main_window as mw

    app = QApplication.instance() or QApplication([])
    errors = []
    monkeypatch.setattr(mw.MainWindow, "error", lambda self, exc: errors.append(exc))
    monkeypatch.setattr(mw.MainWindow, "confirm", lambda self, text: True)
    monkeypatch.setattr(mw.MainWindow, "info", lambda self, *a: None)
    monkeypatch.setattr(mw, "documents_dir", lambda: tmp_path / "docs")
    out_wav = tmp_path / "mix.wav"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_wav), "")))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)

    cfg = Config(soundfont_path=str(sf2_path), block_size=256)
    win = mw.MainWindow(cfg, demo=True)
    win.show()
    assert _wait(app, lambda: win.synth.font is not None and win.project is not None)
    if not win.engine.is_open:
        win.close()
        pytest.skip("il dispositivo audio di questa macchina non si apre")

    win.cb_countin.setChecked(False)
    win.record_piano()
    assert win.engine.mode == REC_PIANO
    assert _wait(app, lambda: win.engine.recording_seconds() > 2.5)
    # il dispositivo di prova può girare più veloce del tempo reale: aspetto anche
    # che il piano demo (che suona in tempo reale) abbia suonato almeno due note
    assert _wait(app, lambda: sum(1 for e in win.writer.events if e[1] == 0) >= 2)
    win.stop_all()
    assert win.project.has_piano(), errors
    events = win.project.load_piano_take()
    assert any(e[1] == 0 for e in events)

    # la voce: con il dispositivo di prova l'ingresso è silenzioso ma il flusso è lo stesso
    if win.engine.input_name:
        win.record_voice()
        assert _wait(app, lambda: win.engine.mode == REC_VOICE)
        assert _wait(app, lambda: win.engine.recording_seconds() > 1.0)
        win.stop_all()
        assert _wait(app, lambda: win.project.has_voice() and not win._busy)

    win.export("wav")
    assert _wait(app, lambda: out_wav.exists() and not win._busy, timeout=30)
    data, sr = sf.read(str(out_wav))
    assert sr == win.engine.samplerate and np.abs(data).max() > 0.01
    assert not errors, errors
    assert Project.open(win.project.folder).settings.name
    win.close()
