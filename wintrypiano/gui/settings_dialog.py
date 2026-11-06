"""Impostazioni avanzate: host API, buffer, correzione latenza, metronomo."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QSlider, QVBoxLayout)
from PySide6.QtCore import Qt

from wintrypiano.audio.devices import HOSTAPI_LABELS
from wintrypiano.config import BUFFER_SIZES, Config


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, hostapis: list[str], samplerate: int, current_latency_ms: float,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(520)
        self.samplerate = samplerate
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        self.api = QComboBox()
        self.api.addItem("Automatico (ASIO se presente, altrimenti WASAPI)", "auto")
        for name in hostapis:
            self.api.addItem(HOSTAPI_LABELS.get(name, name), name)
        idx = self.api.findData(cfg.host_api)
        self.api.setCurrentIndex(max(0, idx))
        form.addRow("Driver audio", self.api)

        self.exclusive = QCheckBox("WASAPI in modalità esclusiva (latenza minore, blocca gli altri suoni)")
        self.exclusive.setChecked(cfg.wasapi_exclusive)
        form.addRow("", self.exclusive)

        self.buffer = QComboBox()
        for b in BUFFER_SIZES:
            self.buffer.addItem(f"{b} campioni", b)
        self.buffer.setCurrentIndex(max(0, self.buffer.findData(cfg.block_size)))
        self.buffer.currentIndexChanged.connect(self._update_latency)
        form.addRow("Buffer audio", self.buffer)
        self.latency = QLabel()
        self.latency.setObjectName("hint")
        form.addRow("", self.latency)
        self._current = current_latency_ms

        self.offset = QDoubleSpinBox()
        self.offset.setRange(-500, 500)
        self.offset.setDecimals(1)
        self.offset.setSuffix(" ms")
        self.offset.setValue(cfg.voice_manual_offset_ms)
        self.offset.setToolTip("Positivo: sposta la voce più tardi. Negativo: più presto.")
        form.addRow("Correzione manuale voce", self.offset)

        self.metro = QSlider(Qt.Horizontal)
        self.metro.setRange(0, 100)
        self.metro.setValue(int(cfg.metronome_volume * 100))
        form.addRow("Volume metronomo", self.metro)

        lay.addLayout(form)
        note = QLabel("Se senti crepitii o interruzioni, aumenta il buffer. "
                      "Se la voce è in anticipo o in ritardo rispetto al piano, regola la correzione manuale.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Applica")
        bb.button(QDialogButtonBox.Cancel).setText("Annulla")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update_latency()

    def _update_latency(self) -> None:
        b = self.buffer.currentData()
        est = 2 * b / self.samplerate * 1000
        self.latency.setText(f"Latenza stimata con questo buffer: circa {est:.1f} ms "
                             f"(attuale misurata dal driver: {self._current:.1f} ms)")

    def apply_to(self, cfg: Config) -> bool:
        """Scrive i valori nella config. Ritorna True se l'audio va riaperto."""
        reopen = (cfg.host_api != self.api.currentData() or cfg.block_size != self.buffer.currentData()
                  or cfg.wasapi_exclusive != self.exclusive.isChecked())
        cfg.host_api = self.api.currentData()
        cfg.block_size = self.buffer.currentData()
        cfg.wasapi_exclusive = self.exclusive.isChecked()
        cfg.voice_manual_offset_ms = self.offset.value()
        cfg.metronome_volume = self.metro.value() / 100.0
        return reopen
