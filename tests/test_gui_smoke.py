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

    # suona e canta nella stessa take
    if win.engine.input_name:
        win.cb_sing.setChecked(True)
        win.record_piano()
        assert win.engine.mode == REC_PIANO
        assert _wait(app, lambda: win.engine.recording_seconds() > 1.5)
        assert _wait(app, lambda: sum(1 for e in win.writer.events if e[1] == 0) >= 1)
        win.stop_all()
        assert win.project.has_piano() and win.project.has_voice(), errors
        win.cb_sing.setChecked(False)

    win.export("wav")
    assert _wait(app, lambda: out_wav.exists() and not win._busy, timeout=30)
    data, sr = sf.read(str(out_wav))
    assert sr == win.engine.samplerate and np.abs(data).max() > 0.01
    assert not errors, errors
    out_mid = tmp_path / "piano_export"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_mid), "")))
    win.export_midi()
    assert (tmp_path / "piano_export.mid").read_bytes() == win.project.piano_path.read_bytes()
    assert Project.open(win.project.folder).settings.name
    win.close()


def test_import_and_sync(tmp_path, sf2_path, monkeypatch, synth):
    """Importa un MIDI e un audio (lo stesso brano, in ritardo), allinea e ascolta."""
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

    from wintrypiano.audio.engine import PLAYING, REC_PIANO
    from wintrypiano.config import Config
    from wintrypiano.core.midifile import save_midi
    from wintrypiano.gui import main_window as mw
    from wintrypiano.gui import sync_dialog
    from wintrypiano.midi.demo import demo_events

    app = QApplication.instance() or QApplication([])
    errors = []
    monkeypatch.setattr(mw.MainWindow, "error", lambda self, exc: errors.append(exc))
    monkeypatch.setattr(mw.MainWindow, "confirm", lambda self, text: True)
    monkeypatch.setattr(mw.MainWindow, "info", lambda self, *a: None)
    monkeypatch.setattr(mw, "documents_dir", lambda: tmp_path / "docs")
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)

    events = demo_events(bpm=110, bars=6, seed=5)
    save_midi(events, tmp_path / "brano.mid", bpm=110)
    song = synth.render([(t + 0.8, k, a, b) for t, k, a, b in events])   # l'audio parte 0,8 s dopo
    sf.write(tmp_path / "brano.wav", song * (0.7 / np.abs(song).max()), 48000)

    cfg = Config(soundfont_path=str(sf2_path), block_size=256)
    win = mw.MainWindow(cfg)
    win.show()
    assert _wait(app, lambda: win.synth.font is not None and win.project is not None)
    if not win.engine.is_open:
        win.close()
        pytest.skip("il dispositivo audio di questa macchina non si apre")

    seen = {}

    def drive(dlg):
        seen["dialog"] = dlg
        assert set(dlg.lanes) == {"piano", "base"}
        assert _wait(app, lambda: all(l.peaks is not None for l in dlg.lanes.values()))
        dlg.view.resize(900, dlg.view.height())
        dlg.view.repaint()
        dlg.auto_align()
        assert _wait(app, lambda: dlg.btn_auto.isEnabled(), timeout=30)
        seen["auto"] = dlg.base_offset_ms
        # ritocco a mano e ascolto da un punto
        dlg.spins["base"].setValue(dlg.spins["base"].value() + 10)
        dlg.view.cursor_s = 1.0
        dlg.preview()
        assert _wait(app, lambda: win.engine.mode == PLAYING, timeout=30)
        assert _wait(app, lambda: (dlg.view.playhead_s or 0) > 1.05)
        dlg.stop_preview()
        return QDialog.Accepted

    monkeypatch.setattr(sync_dialog.SyncDialog, "exec", drive)
    files = iter([str(tmp_path / "brano.mid"), str(tmp_path / "brano.wav")])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (next(files), "")))

    win.import_midi()
    assert win.project.has_piano() and win.sp_bpm.value() == 110, errors
    win.import_audio()   # alla fine propone la sincronizzazione (confermata) e apre il dialogo
    assert _wait(app, lambda: "dialog" in seen and not win._busy, timeout=60), errors
    assert seen["auto"] == pytest.approx(-800, abs=20)
    assert win.project.settings.base_offset_ms == pytest.approx(seen["auto"] + 10)
    assert not win.base_row.isHidden() and win.project.has_base()

    # la base suona mentre registro il piano
    win.cb_countin.setChecked(False)
    win.record_piano()
    assert win.engine.mode == REC_PIANO and win.engine._playback is not None
    assert _wait(app, lambda: win.engine.recording_seconds() > 0.3)
    win.stop_all()

    win.remove_audio()
    assert not win.project.has_base() and win.base_row.isHidden()
    assert not errors, errors
    win.close()
