"""Finestra per scegliere o scaricare il suono del pianoforte."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout)

from wintrypiano.errors import friendly_message
from wintrypiano.gui.widgets import Panel
from wintrypiano.gui.workers import run_task
from wintrypiano.soundfonts import download
from wintrypiano.soundfonts.catalog import CATALOG, installed_path


class SoundfontDialog(QDialog):
    chosen = Signal(str)

    def __init__(self, parent=None, first_run: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Suono del pianoforte")
        self.setMinimumSize(700, 600)
        self._task = None
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        intro = QLabel(
            ("Non ho trovato un suono di pianoforte. " if first_run else "") +
            "Scegli un pianoforte a coda gratuito da scaricare (una sola volta) oppure un file "
            ".sf2/.sf3 che hai già sul disco.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.buttons = []
        for info in CATALOG:
            panel = Panel()
            t = QLabel(f"<b>{info.title}</b>")
            d = QLabel(info.description)
            d.setWordWrap(True)
            meta = QLabel(f"Download circa {info.archive_mb} MB · {info.license}\n{info.author}")
            meta.setObjectName("hint")
            row = QHBoxLayout()
            row.addWidget(t, 1)
            have = installed_path(info)
            b = QPushButton("Usa questo" if have else "Scarica e usa")
            b.clicked.connect(lambda _=False, i=info: self._get(i))
            row.addWidget(b)
            self.buttons.append(b)
            panel.layout_.addLayout(row)
            panel.layout_.addWidget(d)
            panel.layout_.addWidget(meta)
            lay.addWidget(panel)
        pick = QPushButton("Scegli un file .sf2 / .sf3 dal disco…")
        pick.clicked.connect(self._pick)
        self.buttons.append(pick)
        lay.addWidget(pick)
        where = QLabel(
            "Altri pianoforti gratuiti: <a style='color:#8fd3ff' href='https://freepats.zenvoid.org/Piano/'>"
            "freepats.zenvoid.org/Piano</a> (licenze CC0 e CC BY). Controlla sempre la licenza "
            "prima di ridistribuire un soundfont.")
        where.setOpenExternalLinks(True)
        where.setWordWrap(True)
        where.setObjectName("hint")
        lay.addWidget(where)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        self.status = QLabel("")
        self.status.setObjectName("hint")
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.cancel_btn = QPushButton("Chiudi")
        self.cancel_btn.clicked.connect(self._cancel_or_close)
        bottom.addWidget(self.cancel_btn)
        lay.addLayout(bottom)

    def _busy(self, busy: bool) -> None:
        for b in self.buttons:
            b.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_btn.setText("Annulla" if busy else "Chiudi")

    def _get(self, info) -> None:
        have = installed_path(info)
        if have:
            self.chosen.emit(str(have))
            self.accept()
            return
        self._busy(True)
        self.status.setText("Connessione…")
        self._cancelled = False
        self._task = run_task(download.install, info, cancel=lambda: self._cancelled,
                              on_done=self._done, on_error=self._failed, on_progress=self._progress)

    def _progress(self, frac: float, msg: str) -> None:
        self.progress.setValue(int(frac * 1000))
        self.status.setText(msg)

    def _done(self, path) -> None:
        self._task = None
        self._busy(False)
        self.chosen.emit(str(path))
        self.accept()

    def _failed(self, exc) -> None:
        self._task = None
        self._busy(False)
        if isinstance(exc, download.Cancelled):
            self.status.setText("Download annullato.")
        else:
            self.status.setText(friendly_message(exc))

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Scegli un soundfont", str(Path.home()),
                                              "SoundFont (*.sf2 *.sf3)")
        if path:
            self.chosen.emit(path)
            self.accept()

    def _cancel_or_close(self) -> None:
        if self._task is not None:
            self._cancelled = True
        else:
            self.reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._task is not None:
            self._cancelled = True
        super().closeEvent(event)
