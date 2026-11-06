"""Finestra principale: tre passi (piano, voce, export) e menu dei dispositivi."""
from __future__ import annotations

import functools
import logging
import shutil
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton, QSlider, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from wintrypiano import APP_NAME, __version__
from wintrypiano.audio import devices
from wintrypiano.audio.engine import COUNT_IN, IDLE, PLAYING, REC_PIANO, REC_VOICE, AudioEngine, RecordingWriter
from wintrypiano.config import Config
from wintrypiano.core import recovery
from wintrypiano.core.events import CC_SUSTAIN, CONTROL, NOTE_OFF
from wintrypiano.core.export import find_ffmpeg, write_mp3, write_wav
from wintrypiano.core.midifile import save_midi
from wintrypiano.core.mixer import MixSettings, mix_tracks
from wintrypiano.core.project import Project, default_project_folder
from wintrypiano.core.reverb import apply_reverb_offline
from wintrypiano.core.synth import LoadedFont, PianoSynth
from wintrypiano.errors import UserError, friendly_message
from wintrypiano.gui.settings_dialog import SettingsDialog
from wintrypiano.gui.soundfont_dialog import SoundfontDialog
from wintrypiano.gui.widgets import LevelMeter, Panel, big_button, set_active
from wintrypiano.gui.workers import run_task
from wintrypiano.midi.demo import DemoPlayer
from wintrypiano.midi.ports import ALL, NONE, MidiInput, list_inputs, match_port
from wintrypiano.paths import documents_dir
from wintrypiano.soundfonts.catalog import CATALOG, find_default_soundfont

log = logging.getLogger(__name__)


def guarded(fn):
    """Mostra un messaggio chiaro invece di un traceback se lo slot fallisce."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, UserError):
                log.exception("errore in %s", fn.__name__)
            self.error(exc)
            return None

    return wrapper


def fmt_time(sec: float) -> str:
    sec = max(0.0, sec)
    return f"{int(sec // 60):02d}:{sec % 60:04.1f}"


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or audio.size == 0:
        return audio
    n = int(round(audio.shape[0] * dst / src))
    x = np.linspace(0, audio.shape[0] - 1, n)
    return np.interp(x, np.arange(audio.shape[0]), audio).astype(np.float32)


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, demo: bool = False):
        super().__init__()
        self.cfg = cfg
        self.synth = PianoSynth(48000)
        self.engine = AudioEngine(self.synth, 48000)
        self.midi = MidiInput(self.engine.note_event)
        self.demo_player: DemoPlayer | None = None
        self.project: Project | None = None
        self.writer: RecordingWriter | None = None
        self.piano_journal = None
        self.voice_journal = None
        self._piano_cache = None   # (chiave, audio)
        self._busy = 0
        self._audio_lost = False
        self._last_cb = -1
        self._clip_until = 0
        self._last_cb_errors = 0
        self._start_demo = demo

        self.setWindowTitle(APP_NAME)
        self.resize(980, 720)
        self.setMinimumSize(820, 620)
        self._build_ui()
        self._build_menus()

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(50)
        self.ui_timer.timeout.connect(self._tick)
        self.ui_timer.start()
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(2000)
        self.watch_timer.timeout.connect(self._watchdog)
        self.watch_timer.start()
        QTimer.singleShot(0, self._startup)

    # ================================================================== UI
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 18, 28, 12)
        root.setSpacing(16)

        head = QHBoxLayout()
        title = QLabel("❄  wintry piano")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.project_label = QLabel("")
        self.project_label.setObjectName("subtitle")
        head.addWidget(self.project_label)
        root.addLayout(head)

        steps = QHBoxLayout()
        self.step_group = QButtonGroup(self)
        self.step_buttons = []
        for i, text in enumerate(("1 · Suona e registra il piano", "2 · Canta", "3 · Esporta")):
            b = QPushButton(text)
            b.setObjectName("step")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.step_group.addButton(b, i)
            steps.addWidget(b)
            self.step_buttons.append(b)
        self.step_buttons[0].setChecked(True)
        self.step_group.idClicked.connect(self._go_step)
        root.addLayout(steps)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_step_piano())
        self.stack.addWidget(self._build_step_voice())
        self.stack.addWidget(self._build_step_export())
        root.addWidget(self.stack, 1)

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumHeight(8)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.hide()
        root.addWidget(self.busy_bar)
        self.setCentralWidget(central)

        self.midi_led = QLabel("● MIDI")
        self.midi_led.setToolTip("Si accende quando arrivano note dal piano")
        self.midi_led.setStyleSheet("color: #3a4a63;")
        self.statusBar().addPermanentWidget(self.midi_led)
        self.status_devices = QLabel("")
        self.statusBar().addPermanentWidget(self.status_devices)
        self._midi_seen = 0
        self._midi_led_ticks = 0

    def _slider(self, value: float, on_change) -> QSlider:
        s = QSlider(Qt.Horizontal)
        s.setRange(0, 100)
        s.setValue(int(value * 100))
        s.valueChanged.connect(lambda v: on_change(v / 100.0))
        return s

    def _build_step_piano(self) -> QWidget:
        w = Panel()
        lay = w.layout_
        self.piano_info = QLabel("Suona il piano: il suono parte subito. Premi Registra quando sei pronto.")
        self.piano_info.setObjectName("hint")
        self.piano_info.setWordWrap(True)
        lay.addWidget(self.piano_info)

        center = QHBoxLayout()
        center.addStretch(1)
        self.piano_time = QLabel("00:00.0")
        self.piano_time.setObjectName("bigTime")
        self.count_label = QLabel("")
        self.count_label.setObjectName("countIn")
        center.addWidget(self.count_label)
        center.addWidget(self.piano_time)
        center.addStretch(1)
        lay.addLayout(center)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_rec_piano = big_button("●  Registra", record=True)
        self.btn_stop_piano = big_button("■  Stop")
        self.btn_play_piano = big_button("▶  Riascolta")
        self.btn_rec_piano.clicked.connect(self.record_piano)
        self.btn_stop_piano.clicked.connect(self.stop_all)
        self.btn_play_piano.clicked.connect(self.play_piano)
        for b in (self.btn_rec_piano, self.btn_stop_piano, self.btn_play_piano):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(10)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Volume piano"))
        self.sl_piano = self._slider(0.8, self._set_piano_volume)
        opts.addWidget(self.sl_piano, 1)
        self.cb_piano_reverb = QCheckBox("Riverbero")
        self.cb_piano_reverb.toggled.connect(self._set_piano_reverb)
        opts.addWidget(self.cb_piano_reverb)
        lay.addLayout(opts)

        opts2 = QHBoxLayout()
        self.cb_metro = QCheckBox("Metronomo")
        self.cb_metro.toggled.connect(self._set_metronome)
        opts2.addWidget(self.cb_metro)
        self.sp_bpm = QSpinBox()
        self.sp_bpm.setRange(30, 260)
        self.sp_bpm.setValue(100)
        self.sp_bpm.setSuffix(" bpm")
        self.sp_bpm.valueChanged.connect(self._set_bpm)
        opts2.addWidget(self.sp_bpm)
        self.cb_countin = QCheckBox("Conto alla rovescia (4 battiti)")
        self.cb_countin.setChecked(True)
        self.cb_countin.toggled.connect(self._set_countin)
        opts2.addWidget(self.cb_countin)
        self.cb_sing = QCheckBox("Canta mentre suoni (registra anche la voce)")
        self.cb_sing.setToolTip("Piano e voce nella stessa take: il piano come MIDI, la voce come WAV")
        self.cb_sing.toggled.connect(self._set_sing_along)
        opts2.addStretch(1)
        self.latency_label = QLabel("")
        self.latency_label.setObjectName("hint")
        opts2.addWidget(self.latency_label)
        lay.addLayout(opts2)
        lay.addWidget(self.cb_sing)
        self.piano_meter = LevelMeter()
        self.piano_meter.setVisible(False)
        lay.addWidget(self.piano_meter)
        lay.addStretch(1)
        return w

    def _build_step_voice(self) -> QWidget:
        w = Panel()
        lay = w.layout_
        self.voice_info = QLabel("Metti le cuffie. Premi Registra voce: il piano riparte dall'inizio e tu canti sopra.")
        self.voice_info.setObjectName("hint")
        self.voice_info.setWordWrap(True)
        lay.addWidget(self.voice_info)
        center = QHBoxLayout()
        center.addStretch(1)
        self.voice_time = QLabel("00:00.0")
        self.voice_time.setObjectName("bigTime")
        center.addWidget(self.voice_time)
        center.addStretch(1)
        lay.addLayout(center)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_rec_voice = big_button("●  Registra voce", record=True)
        self.btn_stop_voice = big_button("■  Stop")
        self.btn_play_voice = big_button("▶  Riascolta")
        self.btn_rec_voice.clicked.connect(self.record_voice)
        self.btn_stop_voice.clicked.connect(self.stop_all)
        self.btn_play_voice.clicked.connect(self.play_mix)
        for b in (self.btn_rec_voice, self.btn_stop_voice, self.btn_play_voice):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(10)
        lay.addWidget(QLabel("Livello del microfono"))
        self.meter = LevelMeter()
        lay.addWidget(self.meter)
        self.clip_label = QLabel("")
        self.clip_label.setObjectName("warn")
        lay.addWidget(self.clip_label)
        self.cb_monitor = QCheckBox("Ascolta il microfono in cuffia (attiva solo con le cuffie, evita i fischi)")
        self.cb_monitor.setChecked(False)
        self.cb_monitor.toggled.connect(self._set_monitor)
        lay.addWidget(self.cb_monitor)
        lay.addStretch(1)
        return w

    def _build_step_export(self) -> QWidget:
        w = Panel()
        lay = w.layout_
        info = QLabel("Regola il volume di piano e voce, ascolta il mix e poi esporta.")
        info.setObjectName("hint")
        lay.addWidget(info)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Piano"))
        self.sl_mix_piano = self._slider(0.8, self._set_piano_volume)
        r1.addWidget(self.sl_mix_piano, 1)
        self.cb_mix_piano_reverb = QCheckBox("Riverbero")
        self.cb_mix_piano_reverb.toggled.connect(self._set_piano_reverb)
        r1.addWidget(self.cb_mix_piano_reverb)
        lay.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Voce "))
        self.sl_voice = self._slider(0.9, self._set_voice_volume)
        r2.addWidget(self.sl_voice, 1)
        self.cb_voice_reverb = QCheckBox("Riverbero")
        self.cb_voice_reverb.toggled.connect(self._set_voice_reverb)
        r2.addWidget(self.cb_voice_reverb)
        lay.addLayout(r2)
        lay.addSpacing(10)
        self.mix_time = QLabel("")
        self.mix_time.setObjectName("hint")
        self.mix_time.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.mix_time)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_play_mix = big_button("▶  Ascolta il mix")
        self.btn_stop_mix = big_button("■  Stop")
        self.btn_wav = big_button("⤓  Esporta WAV")
        self.btn_mp3 = big_button("⤓  Esporta MP3")
        self.btn_play_mix.clicked.connect(self.play_mix)
        self.btn_stop_mix.clicked.connect(self.stop_all)
        self.btn_wav.clicked.connect(lambda: self.export("wav"))
        self.btn_mp3.clicked.connect(lambda: self.export("mp3"))
        self.btn_midi = big_button("⤓  Esporta MIDI")
        self.btn_midi.setToolTip("Salva il piano come file .mid, da aprire in altri programmi")
        self.btn_midi.clicked.connect(self.export_midi)
        for b in (self.btn_play_mix, self.btn_stop_mix):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addStretch(1)
        for b in (self.btn_wav, self.btn_mp3, self.btn_midi):
            row2.addWidget(b)
        row2.addStretch(1)
        lay.addLayout(row2)
        self.mp3_hint = QLabel("")
        self.mp3_hint.setObjectName("hint")
        self.mp3_hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.mp3_hint)
        lay.addStretch(1)
        return w

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for text, slot, key in (("Nuovo progetto…", self.new_project, QKeySequence.New),
                                ("Apri progetto…", self.open_project, QKeySequence.Open),
                                ("Salva progetto", self.save_project, QKeySequence.Save)):
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(slot)
            m.addAction(a)
        m.addSeparator()
        a = QAction("Esci", self)
        a.triggered.connect(self.close)
        m.addAction(a)

        d = mb.addMenu("&Dispositivi")
        self.menu_midi = d.addMenu("Ingresso MIDI (piano)")
        self.menu_mic = d.addMenu("Microfono")
        self.menu_out = d.addMenu("Uscita audio (cuffie)")
        self.menu_midi.aboutToShow.connect(self._fill_midi_menu)
        self.menu_mic.aboutToShow.connect(lambda: self._fill_audio_menu(self.menu_mic, "input"))
        self.menu_out.aboutToShow.connect(lambda: self._fill_audio_menu(self.menu_out, "output"))
        d.addSeparator()
        a = QAction("Aggiorna elenco dispositivi", self)
        a.triggered.connect(self.refresh_devices)
        d.addAction(a)

        s = mb.addMenu("&Impostazioni")
        a = QAction("Impostazioni…", self)
        a.triggered.connect(self.open_settings)
        s.addAction(a)
        a = QAction("Suono del pianoforte…", self)
        a.triggered.connect(lambda: self.choose_soundfont(False))
        s.addAction(a)
        s.addSeparator()
        self.act_demo = QAction("Modalità demo (note simulate)", self)
        self.act_demo.setCheckable(True)
        self.act_demo.toggled.connect(self.set_demo)
        s.addAction(self.act_demo)

        h = mb.addMenu("&Aiuto")
        a = QAction("Informazioni e crediti", self)
        a.triggered.connect(self.about)
        h.addAction(a)

    # ============================================================= avvio
    @guarded
    def _startup(self) -> None:
        self.open_audio()
        self._open_last_midi()
        self._open_initial_project()
        sf = find_default_soundfont(self.cfg.soundfont_path)
        if sf:
            self.load_soundfont(str(sf))
        else:
            self.choose_soundfont(True)
        if self._start_demo:
            self.act_demo.setChecked(True)
        ff = find_ffmpeg()
        self.btn_mp3.setEnabled(ff is not None)
        self.mp3_hint.setText("" if ff else "Per l'MP3 installa ffmpeg (l'installer lo fa in automatico). Il WAV funziona sempre.")

    def _open_initial_project(self) -> None:
        last = self.cfg.last_project
        if last and (Path(last) / "progetto.json").is_file():
            try:
                self._set_project(Project.open(Path(last)))
                return
            except UserError as exc:
                self.error(exc)
        folder = default_project_folder(documents_dir())
        self._set_project(Project.create(folder))

    # ============================================================ audio
    def open_audio(self, rescan: bool = False, quiet: bool = False) -> bool:
        if self.engine.is_open:
            self.engine.close()
        if rescan:
            devices.rescan()
        last_exc = None
        for api in devices.candidate_hostapis(self.cfg.host_api):
            out = devices.find_device(self.cfg.audio_output, api, "output") or devices.default_device(api, "output")
            if out is None:
                continue
            inp = devices.find_device(self.cfg.audio_input, api, "input")
            if inp is None and api == "ASIO" and out.max_input > 0:
                inp = out
            inp = inp or devices.default_device(api, "input")
            if api == "ASIO" and inp is not None and inp.index != out.index:
                inp = out if out.max_input > 0 else None
            try:
                sr = self.engine.open(out, inp, self.cfg.block_size, self.cfg.wasapi_exclusive)
            except UserError as exc:
                last_exc = exc
                continue
            log.info("audio aperto: uscita %r, microfono %r, %s, %d Hz, buffer %d",
                     self.engine.output_name, self.engine.input_name, api, sr, self.cfg.block_size)
            self._apply_engine_params()
            self._audio_lost = False
            self._last_cb = -1
            if self.engine.input_error and not quiet:
                self.statusBar().showMessage(self.engine.input_error, 8000)
            if self.synth.font is not None and self.synth.font.samplerate != sr:
                self.load_soundfont(str(self.synth.font.path))
            self._update_device_status()
            return True
        self._update_device_status()
        if not quiet:
            self.error(last_exc or UserError("Non ho trovato nessuna uscita audio. Collega le cuffie o la scheda audio."))
        return False

    def _apply_engine_params(self) -> None:
        e = self.engine
        s = self.project.settings if self.project else None
        e.piano_volume = s.piano_volume if s else 0.8
        e.piano_reverb = s.piano_reverb if s else False
        e.metronome_enabled = s.metronome if s else False
        e.metronome_gain = self.cfg.metronome_volume
        e.monitor_enabled = self.cb_monitor.isChecked()

    @guarded
    def refresh_devices(self) -> None:
        if self._recording():
            raise UserError("Ferma la registrazione prima di aggiornare i dispositivi.")
        self.engine.stop()
        if self.open_audio(rescan=True):
            self.statusBar().showMessage("Elenco dispositivi aggiornato.", 4000)

    def _fill_midi_menu(self) -> None:
        m = self.menu_midi
        m.clear()
        group = QActionGroup(m)
        names = list_inputs()
        choices = [(ALL, "Tutti gli ingressi (consigliato)"), (NONE, "Nessuno")] + [(n, n) for n in names]
        for value, label in choices:
            a = QAction(label, m, checkable=True)
            a.setChecked(value == self.midi.wanted)
            a.triggered.connect(lambda _=False, v=value: self.select_midi(v))
            group.addAction(a)
            m.addAction(a)
        if not names:
            x = QAction("(nessun piano MIDI trovato: collegalo via USB)", m)
            x.setEnabled(False)
            m.addAction(x)

    def _fill_audio_menu(self, menu, kind: str) -> None:
        menu.clear()
        api = self.engine.hostapi or (devices.candidate_hostapis(self.cfg.host_api) or [""])[0]
        group = QActionGroup(menu)
        current = self.engine.input_name if kind == "input" else self.engine.output_name
        devs = devices.devices_for(api, kind) if api else []
        for d in devs:
            a = QAction(d.name, menu, checkable=True)
            a.setChecked(d.name == current)
            a.triggered.connect(lambda _=False, name=d.name: self.select_audio(kind, name))
            group.addAction(a)
            menu.addAction(a)
        if not devs:
            x = QAction("(nessun dispositivo)", menu)
            x.setEnabled(False)
            menu.addAction(x)
        menu.addSeparator()
        x = QAction(f"Driver: {api or 'nessuno'} (cambialo nelle Impostazioni)", menu)
        x.setEnabled(False)
        menu.addAction(x)

    @guarded
    def select_midi(self, name: str) -> None:
        self.midi.open(name)
        self.cfg.midi_input = name
        self.cfg.save()
        self._update_device_status()

    @guarded
    def select_audio(self, kind: str, name: str) -> None:
        if self._recording():
            raise UserError("Ferma la registrazione prima di cambiare dispositivo.")
        self.engine.stop()
        if kind == "input":
            self.cfg.audio_input = name
        else:
            self.cfg.audio_output = name
        self.cfg.save()
        self.open_audio()

    def _open_last_midi(self) -> None:
        wanted = self.cfg.midi_input or ALL
        if wanted not in (ALL, NONE):
            wanted = match_port(wanted, list_inputs()) or wanted
        try:
            self.midi.open(wanted)
        except UserError as exc:
            self.midi.wanted = wanted  # riprova quando torna disponibile
            self.statusBar().showMessage(exc.message, 8000)
        self._update_device_status()

    def _update_device_status(self) -> None:
        e = self.engine
        midi = self.midi.name or ("nessuno" if self.midi.wanted == NONE else "non collegato")
        if self.demo_player:
            midi = f"demo attiva ({midi})" if self.midi.name else "demo attiva"
        if e.is_open:
            out = f"{e.output_name} ({e.hostapi})"
            lat = f"latenza ≈ {e.estimated_latency_ms():.0f} ms"
        else:
            out, lat = "nessuna", ""
        mic = e.input_name or "nessuno"
        self.status_devices.setText(f"MIDI: {midi}   ·   Uscita: {out}   ·   Microfono: {mic}")
        self.latency_label.setText(f"Latenza stimata: {e.estimated_latency_ms():.0f} ms · buffer {e.blocksize}"
                                   if e.is_open else "Audio non attivo")

    # ======================================================== soundfont
    def choose_soundfont(self, first_run: bool) -> None:
        dlg = SoundfontDialog(self, first_run=first_run)
        dlg.chosen.connect(self.load_soundfont)
        dlg.exec()
        if first_run and self.synth.font is None:
            self.piano_info.setText("Manca il suono del pianoforte: scegline uno da Impostazioni → Suono del pianoforte.")

    def load_soundfont(self, path: str) -> None:
        self._begin_busy("Caricamento del suono del pianoforte…")
        sr = self.engine.samplerate
        run_task(LoadedFont, Path(path), sr, on_done=self._font_loaded, on_error=self._busy_failed)

    def _font_loaded(self, font: LoadedFont) -> None:
        self._end_busy()
        self.synth.samplerate = font.samplerate
        self.synth.set_font(font)
        self._piano_cache = None
        self.cfg.soundfont_path = str(font.path)
        self.cfg.save()
        if self.project:
            self.project.settings.soundfont = font.path.name
        self.piano_info.setText(f"Suono: {font.path.stem}. Suona il piano: il suono parte subito. "
                                "Premi Registra quando sei pronto.")
        self.statusBar().showMessage(f"Pianoforte pronto: {font.preset_name}", 5000)

    # ========================================================= progetto
    def _set_project(self, proj: Project) -> None:
        self.project = proj
        self._piano_cache = None
        s = proj.settings
        for widget, value in ((self.sl_piano, s.piano_volume), (self.sl_mix_piano, s.piano_volume),
                              (self.sl_voice, s.voice_volume)):
            widget.blockSignals(True)
            widget.setValue(int(value * 100))
            widget.blockSignals(False)
        for widget, value in ((self.cb_piano_reverb, s.piano_reverb), (self.cb_mix_piano_reverb, s.piano_reverb),
                              (self.cb_voice_reverb, s.voice_reverb), (self.cb_metro, s.metronome),
                              (self.cb_countin, s.count_in), (self.cb_sing, s.sing_along)):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
        self.sp_bpm.blockSignals(True)
        self.sp_bpm.setValue(int(round(s.bpm)))
        self.sp_bpm.blockSignals(False)
        self._apply_engine_params()
        self.cfg.last_project = str(proj.folder)
        self.cfg.save()
        self.project_label.setText(f"Progetto: {s.name}")
        self._check_recovery()

    @guarded
    def new_project(self) -> None:
        if self._recording():
            raise UserError("Ferma la registrazione prima di creare un nuovo progetto.")
        name, ok = QInputDialog.getText(self, "Nuovo progetto", "Nome del progetto:")
        if not ok or not name.strip():
            return
        name = "".join(c for c in name.strip() if c not in '<>:"/\\|?*')
        base = QFileDialog.getExistingDirectory(self, "Dove salvare il progetto?", str(documents_dir()))
        if not base:
            return
        self.save_project(quiet=True)
        self.engine.stop()
        self._set_project(Project.create(Path(base) / name, name))
        self._go_step(0)

    @guarded
    def open_project(self) -> None:
        if self._recording():
            raise UserError("Ferma la registrazione prima di aprire un altro progetto.")
        folder = QFileDialog.getExistingDirectory(self, "Apri la cartella del progetto", str(documents_dir()))
        if not folder:
            return
        proj = Project.open(Path(folder))
        self.save_project(quiet=True)
        self.engine.stop()
        self._set_project(proj)

    @guarded
    def save_project(self, quiet: bool = False) -> None:
        if self.project:
            self.project.save()
            if not quiet:
                self.statusBar().showMessage("Progetto salvato.", 3000)

    def _check_recovery(self) -> None:
        proj = self.project
        rec = recovery.find_recovery(proj.recovery_dir)
        if rec.empty:
            recovery.clear_recovery(proj.recovery_dir)
            return
        parts = []
        if rec.piano_events:
            parts.append("il piano")
        if rec.voice is not None:
            parts.append(f"la voce ({rec.voice.size / max(rec.voice_samplerate, 1):.0f} s)")
        box = QMessageBox(self)
        box.setWindowTitle("Registrazione interrotta")
        box.setText("L'ultima registrazione si è interrotta prima di essere salvata.\n"
                    f"Posso recuperare {' e '.join(parts)}.")
        rec_btn = box.addButton("Recupera", QMessageBox.AcceptRole)
        box.addButton("Scarta", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not rec_btn:
            recovery.clear_recovery(proj.recovery_dir)
            return
        try:
            saved = []
            if rec.piano_events:
                if not proj.has_piano() or self.confirm("Sostituire la take del piano attuale con quella recuperata?\n"
                                                        "Se scegli No la salvo come piano_recuperato.mid."):
                    proj.save_piano_take(rec.piano_events, overwrite=True)
                    saved.append("piano.mid")
                else:
                    save_midi(rec.piano_events, proj.folder / "piano_recuperato.mid", rec.piano_bpm)
                    saved.append("piano_recuperato.mid")
            if rec.voice is not None:
                if not proj.has_voice() or self.confirm("Sostituire la voce attuale con quella recuperata?\n"
                                                        "Se scegli No la salvo come voce_recuperata.wav."):
                    proj.save_voice_take(rec.voice, rec.voice_samplerate, rec.voice_offset_ms, overwrite=True)
                    saved.append("voce.wav")
                else:
                    write_wav(rec.voice, rec.voice_samplerate, proj.folder / "voce_recuperata.wav", "FLOAT")
                    saved.append("voce_recuperata.wav")
            recovery.clear_recovery(proj.recovery_dir)
            self.info("Recupero completato", "Ho salvato: " + ", ".join(saved))
        except Exception as exc:  # noqa: BLE001
            self.error(exc)

    # ===================================================== parametri
    def _set_piano_volume(self, v: float) -> None:
        for s in (self.sl_piano, self.sl_mix_piano):
            s.blockSignals(True)
            s.setValue(int(v * 100))
            s.blockSignals(False)
        self.engine.piano_volume = v
        if self.engine.mode == PLAYING and self._playing_piano_only:
            self.engine.playback_gain = v
        if self.project:
            self.project.settings.piano_volume = v

    def _set_piano_reverb(self, on: bool) -> None:
        for c in (self.cb_piano_reverb, self.cb_mix_piano_reverb):
            c.blockSignals(True)
            c.setChecked(on)
            c.blockSignals(False)
        if on and not self.engine.piano_reverb:
            self.engine.reverb.reset()
        self.engine.piano_reverb = on
        if self.project:
            self.project.settings.piano_reverb = on

    def _set_voice_volume(self, v: float) -> None:
        if self.project:
            self.project.settings.voice_volume = v

    def _set_voice_reverb(self, on: bool) -> None:
        if self.project:
            self.project.settings.voice_reverb = on

    def _set_metronome(self, on: bool) -> None:
        self.engine.metronome_enabled = on
        if self.project:
            self.project.settings.metronome = on

    def _set_bpm(self, bpm: int) -> None:
        if self.project:
            self.project.settings.bpm = float(bpm)
        if self.demo_player:
            self.demo_player.bpm = bpm

    def _set_sing_along(self, on: bool) -> None:
        self.piano_meter.setVisible(on)
        if self.project:
            self.project.settings.sing_along = on

    def _set_countin(self, on: bool) -> None:
        if self.project:
            self.project.settings.count_in = on

    def _set_monitor(self, on: bool) -> None:
        self.engine.monitor_ring.clear()
        self.engine.monitor_enabled = on

    # ===================================================== registrazione piano
    def _recording(self) -> bool:
        return self.engine.mode in (COUNT_IN, REC_PIANO, REC_VOICE)

    def _require_audio(self) -> None:
        if not self.engine.is_open:
            raise UserError("L'audio non è attivo. Controlla l'uscita audio nel menu Dispositivi.")

    @guarded
    def record_piano(self) -> None:
        if self._recording() or self._busy:
            return
        self._require_audio()
        if self.synth.font is None:
            raise UserError("Manca il suono del pianoforte: sceglilo da Impostazioni → Suono del pianoforte.")
        proj = self.project
        sing = self.cb_sing.isChecked()
        if sing and not self.engine.input_name:
            raise UserError(self.engine.input_error or
                            "Per cantare mentre suoni scegli il microfono da Dispositivi → Microfono.")
        if proj.has_piano() or (sing and proj.has_voice()):
            if sing:
                what = " e della voce" if proj.has_voice() else ""
                msg = f"Esiste già una take del piano{what}. Vuoi sovrascriverla?"
                if proj.has_voice() and not proj.has_piano():
                    msg = "Esiste già una registrazione della voce. Vuoi sovrascriverla?"
            else:
                msg = "Esiste già una take del piano. Vuoi sovrascriverla?"
                if proj.has_voice():
                    msg += "\n\nAttenzione: la voce già registrata resterà, ma non sarà più a tempo col nuovo piano."
            if not self.confirm(msg):
                return
        self.engine.stop()
        bpm = float(self.sp_bpm.value())
        proj.settings.bpm = bpm
        self.piano_journal = recovery.PianoJournal(proj.recovery_dir, bpm)
        self.voice_journal = recovery.VoiceJournal(proj.recovery_dir, self.engine.samplerate) if sing else None
        self.writer = RecordingWriter(self.engine, piano_journal=self.piano_journal,
                                      voice_journal=self.voice_journal)
        self.writer.start()
        self.engine.metronome_gain = self.cfg.metronome_volume
        self.engine.metronome_enabled = self.cb_metro.isChecked()
        self.engine.start_piano_recording(bpm, 4 if self.cb_countin.isChecked() else 0, with_voice=sing)
        set_active(self.btn_rec_piano, True)

    def _finish_piano_recording(self) -> None:
        end_t = self.engine.recording_seconds()
        held = [k for k in range(128) if self.synth._held[k]]  # noqa: SLF001
        sustain = self.synth.sustain
        offset = self.engine.voice_offset_ms()
        self.engine.stop()
        writer, journal, vjournal = self.writer, self.piano_journal, self.voice_journal
        self.writer = self.piano_journal = self.voice_journal = None
        writer.finish()
        events = list(writer.events)
        set_active(self.btn_rec_piano, False)
        if events:
            for k in held:
                events.append((end_t, NOTE_OFF, k, 0))
            if sustain:
                events.append((end_t, CONTROL, CC_SUSTAIN, 0))
        if writer.error:
            journal.close(delete=False)
            if vjournal:
                vjournal.close(delete=False)
            raise UserError("Errore durante la scrittura della registrazione su disco. "
                            "Al prossimo avvio proverò a recuperarla.")
        saved = []
        if any(e[1] == 0 for e in events):
            try:
                self.project.save_piano_take(events, overwrite=True)  # conferma già chiesta prima di registrare
            except Exception:
                journal.close(delete=False)
                if vjournal:
                    vjournal.close(delete=False)
                raise
            self._piano_cache = None
            saved.append(f"piano ({end_t:.1f} s)")
        journal.close(delete=True)
        if vjournal is not None:
            audio = writer.voice_audio()
            if audio.size >= self.engine.samplerate * 0.2:
                try:
                    self.project.save_voice_take(audio, self.engine.samplerate, offset, overwrite=True)
                except Exception:
                    vjournal.close(delete=False)
                    raise
                saved.append(f"voce ({audio.size / self.engine.samplerate:.1f} s)")
            vjournal.close(delete=True)
        if saved:
            self.statusBar().showMessage("Salvato: " + ", ".join(saved) + ".", 6000)
        else:
            self.statusBar().showMessage("Nessuna nota registrata.", 5000)

    # ===================================================== registrazione voce
    @guarded
    def record_voice(self) -> None:
        if self._recording() or self._busy:
            return
        self._require_audio()
        proj = self.project
        if not proj.has_piano():
            raise UserError("Prima registra il piano al passo 1.")
        if not self.engine.input_name:
            raise UserError(self.engine.input_error or "Nessun microfono selezionato. Sceglilo dal menu Dispositivi → Microfono.")
        if self.synth.font is None:
            raise UserError("Manca il suono del pianoforte.")
        if proj.has_voice() and not self.confirm("Esiste già una registrazione della voce. Vuoi rifarla?\n"
                                                 "Il piano non verrà toccato."):
            return
        self.engine.stop()
        self._begin_busy("Preparo il piano…")
        run_task(self._prepare_piano_playback, on_done=self._start_voice, on_error=self._busy_failed)

    def _start_voice(self, piano: np.ndarray) -> None:
        self._end_busy()
        proj = self.project
        self.voice_journal = recovery.VoiceJournal(proj.recovery_dir, self.engine.samplerate)
        self.writer = RecordingWriter(self.engine, voice_journal=self.voice_journal)
        self.writer.start()
        self.engine.playback_gain = 1.0
        self.engine.metronome_enabled = self.cb_metro.isChecked()
        self.engine.start_voice_recording(piano * np.float32(proj.settings.piano_volume), proj.settings.bpm)
        set_active(self.btn_rec_voice, True)

    def _finish_voice_recording(self) -> None:
        offset = self.engine.voice_offset_ms()
        self.engine.stop()
        writer, journal = self.writer, self.voice_journal
        self.writer = self.voice_journal = None
        writer.finish()
        set_active(self.btn_rec_voice, False)
        if writer.error:
            journal.close(delete=False)
            raise UserError("Errore durante la scrittura della voce su disco. Al prossimo avvio proverò a recuperarla.")
        audio = writer.voice_audio()
        if audio.size < self.engine.samplerate * 0.2:
            journal.close(delete=True)
            self.statusBar().showMessage("Registrazione della voce troppo corta: non salvata.", 5000)
            return
        if self.engine.voice_ring.overflows:
            log.warning("ring buffer voce: %d overflow", self.engine.voice_ring.overflows)
            self.engine.voice_ring.overflows = 0
        sr = self.engine.samplerate
        self._begin_busy("Salvo la voce…")

        def save():
            self.project.save_voice_take(audio, sr, offset, overwrite=True)
            return audio.size / sr

        def done(sec):
            self._end_busy()
            journal.close(delete=True)
            self.statusBar().showMessage(f"Voce salvata ({sec:.1f} s). Compensazione latenza: {offset:.1f} ms.", 6000)

        def failed(exc):
            journal.close(delete=False)
            self._busy_failed(exc)

        run_task(save, on_done=done, on_error=failed)

    # ===================================================== riproduzione e mix
    def _render_piano(self) -> np.ndarray:
        """Render del piano (senza volume), con cache. Gira in un thread di lavoro."""
        proj = self.project
        key = (str(proj.piano_path), proj.piano_path.stat().st_mtime_ns if proj.has_piano() else 0,
               str(self.synth.path), self.synth.samplerate)
        cache = self._piano_cache
        if cache is not None and cache[0] == key:
            return cache[1]
        events = proj.load_piano_take()
        audio = self.synth.render(events)
        self._piano_cache = (key, audio)
        return audio

    def _prepare_piano_playback(self) -> np.ndarray:
        audio = self._render_piano()
        if self.project.settings.piano_reverb:
            audio = apply_reverb_offline(audio, self.synth.samplerate)
        return audio

    @guarded
    def play_piano(self) -> None:
        if self._recording() or self._busy:
            return
        self._require_audio()
        if not self.project.has_piano():
            raise UserError("Non c'è ancora una take del piano da riascoltare.")
        if self.synth.font is None:
            raise UserError("Manca il suono del pianoforte.")
        self.engine.stop()
        self._begin_busy("Preparo il riascolto…")

        def go(audio):
            self._end_busy()
            self._playing_piano_only = True
            self.engine.playback_gain = self.project.settings.piano_volume
            self.engine.play(audio, self.project.settings.bpm)

        run_task(self._prepare_piano_playback, on_done=go, on_error=self._busy_failed)

    def _build_mix(self) -> np.ndarray:
        proj = self.project
        sr = self.synth.samplerate
        piano = self._render_piano() if proj.has_piano() else None
        voice, vsr = proj.load_voice_take()
        if voice is not None:
            voice = resample(voice, vsr, sr)
        mix, _gain = mix_tracks(piano, voice, sr, proj.mix_settings(self.cfg.voice_manual_offset_ms))
        return mix

    @guarded
    def play_mix(self) -> None:
        if self._recording() or self._busy:
            return
        self._require_audio()
        if not (self.project.has_piano() or self.project.has_voice()):
            raise UserError("Non c'è ancora niente da ascoltare: registra prima il piano.")
        if self.project.has_piano() and self.synth.font is None:
            raise UserError("Manca il suono del pianoforte.")
        self.engine.stop()
        self._begin_busy("Preparo il mix…")

        def go(mix):
            self._end_busy()
            self._playing_piano_only = False
            self.engine.playback_gain = 1.0
            self.engine.play(mix)

        run_task(self._build_mix, on_done=go, on_error=self._busy_failed)

    @guarded
    def export(self, fmt: str) -> None:
        if self._recording() or self._busy:
            return
        if not (self.project.has_piano() or self.project.has_voice()):
            raise UserError("Non c'è niente da esportare: registra prima il piano.")
        if self.project.has_piano() and self.synth.font is None:
            raise UserError("Manca il suono del pianoforte.")
        default = self.project.folder / f"{self.project.settings.name}.{fmt}"
        filt = "WAV (*.wav)" if fmt == "wav" else "MP3 (*.mp3)"
        path, _ = QFileDialog.getSaveFileName(self, "Esporta il mix", str(default), filt)
        if not path:
            return
        self.engine.stop()
        sr = self.synth.samplerate
        self._begin_busy("Esportazione in corso…")

        def work():
            mix = self._build_mix()
            if fmt == "wav":
                return write_wav(mix, sr, Path(path))
            return write_mp3(mix, sr, Path(path))

        def done(p):
            self._end_busy()
            self.info("Export completato", f"File salvato:\n{p}")

        run_task(work, on_done=done, on_error=self._busy_failed)

    @guarded
    def export_midi(self) -> None:
        if self._recording() or self._busy:
            return
        if not self.project.has_piano():
            raise UserError("Non c'è ancora una take del piano da esportare.")
        default = self.project.folder / f"{self.project.settings.name}.mid"
        path, _ = QFileDialog.getSaveFileName(self, "Esporta il piano in MIDI", str(default), "MIDI (*.mid)")
        if not path:
            return
        out = Path(path)
        if out.suffix.lower() not in (".mid", ".midi"):
            out = out.with_suffix(".mid")
        if out.resolve() != self.project.piano_path.resolve():
            try:
                shutil.copyfile(self.project.piano_path, out)
            except OSError as exc:
                raise UserError(f"Non riesco a salvare il file «{out.name}».") from exc
        self.info("Export completato", f"File MIDI salvato:\n{out}")

    @guarded
    def stop_all(self) -> None:
        mode = self.engine.mode
        if mode in (COUNT_IN, REC_PIANO):
            self._finish_piano_recording()
        elif mode == REC_VOICE:
            self._finish_voice_recording()
        else:
            self.engine.stop()

    # ===================================================== demo
    def set_demo(self, on: bool) -> None:
        if on and self.demo_player is None:
            self.demo_player = DemoPlayer(self.engine.note_event, bpm=self.sp_bpm.value())
            self.demo_player.start()
            self.statusBar().showMessage("Modalità demo attiva: un piano virtuale sta suonando.", 5000)
        elif not on and self.demo_player is not None:
            self.demo_player.stop()
            self.demo_player = None
        self._update_device_status()

    # ===================================================== timer
    def _tick(self) -> None:
        e = self.engine
        if self.midi.activity != self._midi_seen:
            self._midi_seen = self.midi.activity
            if self._midi_led_ticks == 0:
                self.midi_led.setStyleSheet("color: #6fe3b0; font-weight: 600;")
            self._midi_led_ticks = 6
        elif self._midi_led_ticks:
            self._midi_led_ticks -= 1
            if self._midi_led_ticks == 0:
                self.midi_led.setStyleSheet("color: #3a4a63;")
        mode = e.mode
        if mode == COUNT_IN:
            self.count_label.setText(str(e.count_in_remaining()))
            self.piano_time.setText("")
        else:
            self.count_label.setText("")
            if mode == REC_PIANO:
                self.piano_time.setText("● " + fmt_time(e.recording_seconds()))
            elif mode == PLAYING and self.stack.currentIndex() == 0:
                self.piano_time.setText("▶ " + fmt_time(e.playback_position()[0]))
            elif not self.piano_time.text() or mode == IDLE:
                self.piano_time.setText("00:00.0")
        if mode == REC_VOICE:
            self.voice_time.setText("● " + fmt_time(e.recording_seconds()))
        elif mode == PLAYING and self.stack.currentIndex() == 1:
            self.voice_time.setText("▶ " + fmt_time(e.playback_position()[0]))
        elif mode == IDLE:
            self.voice_time.setText("00:00.0")
        if mode == PLAYING:
            pos, total = e.playback_position()
            self.mix_time.setText(f"▶ {fmt_time(pos)} / {fmt_time(total)}")
        else:
            self.mix_time.setText("")
        peak, clip = e.take_mic_level()
        self.meter.set_level(peak, clip)
        if self.piano_meter.isVisible():
            self.piano_meter.set_level(peak, clip)
        if clip:
            self._clip_until = 40  # ~2 s
            self.clip_label.setText("⚠ Il microfono satura: abbassa il guadagno o allontanati un po'.")
            if self.piano_meter.isVisible():
                self.statusBar().showMessage("⚠ Il microfono satura: abbassa il guadagno.", 2000)
        elif self._clip_until > 0:
            self._clip_until -= 1
            if self._clip_until == 0:
                self.clip_label.setText("")
                self.meter.reset_clip()
                self.piano_meter.reset_clip()
        rec = mode in (COUNT_IN, REC_PIANO, REC_VOICE)
        busy = self._busy > 0
        self.btn_rec_piano.setEnabled(not rec and not busy)
        self.btn_rec_voice.setEnabled(not rec and not busy)
        for b in (self.btn_play_piano, self.btn_play_voice, self.btn_play_mix, self.btn_wav, self.btn_midi):
            b.setEnabled(not rec and not busy)
        self.btn_mp3.setEnabled(not rec and not busy and self.mp3_hint.text() == "")
        for b in self.step_buttons:
            b.setEnabled(not rec)

    def _watchdog(self) -> None:
        try:
            msg = self.midi.poll()
        except UserError as exc:
            msg = exc.message
        if msg:
            self.statusBar().showMessage(msg, 6000)
            self._update_device_status()
        e = self.engine
        if e.callback_errors != self._last_cb_errors:
            self._last_cb_errors = e.callback_errors
            log.error("errori nella callback audio: %d (ultimo: %r)", e.callback_errors, e.last_error)
        if self.writer is not None and self.writer.error is not None:
            self.stop_all()
        if e.is_open:
            stalled = e.callback_count == self._last_cb
            self._last_cb = e.callback_count
            if e.stream_finished or stalled:
                log.warning("dispositivo audio perso (finished=%s stalled=%s)", e.stream_finished, stalled)
                was_recording = self._recording()
                if was_recording:
                    self.stop_all()  # salva quello che c'è
                e.close()
                self._audio_lost = True
                self._update_device_status()
                self.statusBar().showMessage("Dispositivo audio scollegato. Riprovo in automatico…", 6000)
        elif self._audio_lost and not self._busy:
            self._last_cb = -1
            if self.open_audio(rescan=True, quiet=True):
                self.statusBar().showMessage("Audio ripristinato.", 5000)

    # ===================================================== stato occupato
    def _begin_busy(self, msg: str) -> None:
        self._busy += 1
        self.busy_bar.show()
        self.statusBar().showMessage(msg)

    def _end_busy(self) -> None:
        self._busy = max(0, self._busy - 1)
        if not self._busy:
            self.busy_bar.hide()
            self.statusBar().clearMessage()

    def _busy_failed(self, exc) -> None:
        self._end_busy()
        self.error(exc)

    # ===================================================== varie
    def _go_step(self, i: int) -> None:
        if self._recording():
            self.step_buttons[self.stack.currentIndex()].setChecked(True)
            return
        self.stack.setCurrentIndex(i)
        self.step_buttons[i].setChecked(True)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, devices.sorted_hostapis(), self.engine.samplerate,
                             self.engine.estimated_latency_ms(), self)
        if dlg.exec():
            reopen = dlg.apply_to(self.cfg)
            self.cfg.save()
            self.engine.metronome_gain = self.cfg.metronome_volume
            if reopen:
                if self._recording():
                    self.error(UserError("Le nuove impostazioni audio verranno applicate dopo la registrazione."))
                else:
                    self.engine.stop()
                    self.open_audio()

    def about(self) -> None:
        credits = "<br>".join(f"<b>{i.title}</b>: {i.author}, licenza {i.license}" for i in CATALOG)
        QMessageBox.about(self, APP_NAME,
                          f"<h3>wintry piano {__version__}</h3>"
                          "Suona il piano MIDI, registralo, cantaci sopra ed esporta.<br><br>"
                          f"Suoni di pianoforte:<br>{credits}<br><br>"
                          "Librerie: PySide6 (LGPL), mido e python-rtmidi (MIT), sounddevice (MIT) "
                          "con PortAudio, soundfile (BSD) con libsndfile (LGPL), tinysoundfont (MIT).")

    def confirm(self, text: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText(text)
        yes = box.addButton("Sì", QMessageBox.YesRole)
        box.addButton("No", QMessageBox.NoRole)
        box.exec()
        return box.clickedButton() is yes

    def info(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def error(self, exc) -> None:
        msg = friendly_message(exc) if isinstance(exc, BaseException) else str(exc)
        QMessageBox.warning(self, APP_NAME, msg)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._recording():
            if not self.confirm("Stai registrando. Vuoi fermare, salvare e uscire?"):
                event.ignore()
                return
            self.stop_all()
        try:
            self.save_project(quiet=True)
            self.cfg.save()
        except Exception:  # noqa: BLE001
            log.exception("salvataggio in chiusura")
        self.set_demo(False)
        self.midi.close()
        self.engine.close()
        event.accept()

    _playing_piano_only = False
