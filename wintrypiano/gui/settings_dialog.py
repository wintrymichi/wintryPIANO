"""Advanced settings: host API, buffer, latency correction, metronome."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QSlider, QVBoxLayout)
from PySide6.QtCore import Qt

from wintrypiano.audio.devices import HOSTAPI_LABELS
from wintrypiano.config import BUFFER_SIZES, EXPERIMENTAL_BUFFERS, Config


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, hostapis: list[str], samplerate: int, current_latency_ms: float,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.samplerate = samplerate
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        self.api = QComboBox()
        self.api.addItem("Automatic (ASIO if available, otherwise WASAPI)", "auto")
        for name in hostapis:
            self.api.addItem(HOSTAPI_LABELS.get(name, name), name)
        idx = self.api.findData(cfg.host_api)
        self.api.setCurrentIndex(max(0, idx))
        form.addRow("Audio driver", self.api)

        self.exclusive = QCheckBox("WASAPI exclusive mode (lower latency, other apps are muted)")
        self.exclusive.setChecked(cfg.wasapi_exclusive)
        form.addRow("", self.exclusive)

        self.buffer = QComboBox()
        for b in BUFFER_SIZES:
            tag = "  (experimental)" if b in EXPERIMENTAL_BUFFERS else ""
            self.buffer.addItem(f"{b} samples{tag}", b)
        self.buffer.setCurrentIndex(max(0, self.buffer.findData(cfg.block_size)))
        self.buffer.currentIndexChanged.connect(self._update_latency)
        form.addRow("Audio buffer", self.buffer)
        self.latency = QLabel()
        self.latency.setObjectName("hint")
        form.addRow("", self.latency)
        self._current = current_latency_ms

        self.offset = QDoubleSpinBox()
        self.offset.setRange(-500, 500)
        self.offset.setDecimals(1)
        self.offset.setSuffix(" ms")
        self.offset.setValue(cfg.voice_manual_offset_ms)
        self.offset.setToolTip("Positive: moves the voice later. Negative: earlier.")
        form.addRow("Manual voice offset", self.offset)

        self.metro = QSlider(Qt.Horizontal)
        self.metro.setRange(0, 100)
        self.metro.setValue(int(cfg.metronome_volume * 100))
        form.addRow("Metronome volume", self.metro)

        lay.addLayout(form)
        note = QLabel("If you hear crackles or dropouts, increase the buffer. The experimental buffers (16-48) "
                      "give the lowest latency but only hold up with WASAPI exclusive or ASIO on a fast PC. "
                      "If the voice is early or late compared to the piano, adjust the manual offset.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Apply")
        bb.button(QDialogButtonBox.Cancel).setText("Cancel")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update_latency()

    def _update_latency(self) -> None:
        b = self.buffer.currentData()
        est = 2 * b / self.samplerate * 1000
        self.latency.setText(f"Estimated latency with this buffer: about {est:.1f} ms "
                             f"(current, reported by the driver: {self._current:.1f} ms)")

    def apply_to(self, cfg: Config) -> bool:
        """Write the values to the config. Return True if audio must be reopened."""
        reopen = (cfg.host_api != self.api.currentData() or cfg.block_size != self.buffer.currentData()
                  or cfg.wasapi_exclusive != self.exclusive.isChecked())
        cfg.host_api = self.api.currentData()
        cfg.block_size = self.buffer.currentData()
        cfg.wasapi_exclusive = self.exclusive.isChecked()
        cfg.voice_manual_offset_ms = self.offset.value()
        cfg.metronome_volume = self.metro.value() / 100.0
        return reopen
