"""Finestra «Sincronizza tracce»: sposta voce e audio importato rispetto al piano.

Il piano è il riferimento (tempo 0 = inizio della take). Le altre tracce si spostano
trascinandole, con i campi in millisecondi oppure con l'allineamento automatico.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollBar, QSizePolicy, QVBoxLayout, QWidget)

from wintrypiano.audio.engine import PLAYING
from wintrypiano.core import align
from wintrypiano.core.mixer import MixSettings, combine, prevent_clipping
from wintrypiano.gui import theme
from wintrypiano.gui.workers import run_task

PEAK_RATE = 400          # valori della forma d'onda al secondo
HEADER_W = 92            # colonna dei nomi
RULER_H = 26
LANE_H = 78
MAX_OFFSET_MS = 600_000  # ±10 minuti


@dataclass
class Lane:
    key: str
    title: str
    color: str
    peaks: np.ndarray | None = None
    offset_ms: float = 0.0       # dove parte la traccia rispetto al piano
    draggable: bool = True
    stretch: float = 1.0         # solo piano: durata visualizzata = durata / stretch

    def start_s(self) -> float:
        return self.offset_ms / 1000.0

    def duration_s(self) -> float:
        if self.peaks is None:
            return 0.0
        return self.peaks.shape[0] / PEAK_RATE / self.stretch


class TrackView(QWidget):
    """Linea del tempo con le forme d'onda; le tracce si trascinano col mouse."""

    offsetChanged = Signal(str, float)   # chiave traccia, nuovo offset in ms
    cursorChanged = Signal(float)        # secondi

    def __init__(self, lanes: list[Lane], parent=None):
        super().__init__(parent)
        self.lanes = lanes
        self.px_per_s = 40.0
        self.view_start = -1.0
        self.cursor_s = 0.0
        self.playhead_s: float | None = None
        self._drag: tuple[Lane, float, float] | None = None   # traccia, x iniziale, offset iniziale
        self._fit_pending = True
        self.setFixedHeight(RULER_H + LANE_H * len(lanes) + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.scrollbar: QScrollBar | None = None

    # -------------------------------------------------------- geometria
    def bounds(self) -> tuple[float, float]:
        starts = [min(0.0, l.start_s()) for l in self.lanes]
        ends = [l.start_s() + l.duration_s() for l in self.lanes]
        return min(starts + [0.0]) - 1.0, max(ends + [5.0]) + 1.0

    def wave_width(self) -> int:
        return max(50, self.width() - HEADER_W)

    def t_to_x(self, t: float) -> float:
        return HEADER_W + (t - self.view_start) * self.px_per_s

    def x_to_t(self, x: float) -> float:
        return self.view_start + (x - HEADER_W) / self.px_per_s

    def lane_at(self, y: float) -> Lane | None:
        i = int((y - RULER_H) // LANE_H)
        if y >= RULER_H and 0 <= i < len(self.lanes):
            return self.lanes[i]
        return None

    def fit(self) -> None:
        lo, hi = self.bounds()
        self.px_per_s = max(2.0, self.wave_width() / max(hi - lo, 1.0))
        self.view_start = lo
        self._sync_scrollbar()
        self.update()

    def zoom(self, factor: float, anchor_x: float | None = None) -> None:
        if anchor_x is None:
            anchor_x = HEADER_W + self.wave_width() / 2
        t = self.x_to_t(anchor_x)
        lo, hi = self.bounds()
        min_pps = max(1.0, self.wave_width() / max(hi - lo, 1.0) * 0.5)
        self.px_per_s = float(min(4000.0, max(min_pps, self.px_per_s * factor)))
        self.view_start = t - (anchor_x - HEADER_W) / self.px_per_s
        self._clamp()
        self._sync_scrollbar()
        self.update()

    def _clamp(self) -> None:
        lo, hi = self.bounds()
        span = self.wave_width() / self.px_per_s
        self.view_start = min(max(self.view_start, lo), max(lo, hi - span))

    def _sync_scrollbar(self) -> None:
        sb = self.scrollbar
        if sb is None:
            return
        lo, hi = self.bounds()
        span = self.wave_width() / self.px_per_s
        sb.blockSignals(True)
        sb.setRange(int(lo * 100), int(max(lo, hi - span) * 100))
        sb.setPageStep(int(span * 100))
        sb.setSingleStep(max(1, int(span * 10)))
        sb.setValue(int(self.view_start * 100))
        sb.blockSignals(False)

    def scroll_to(self, value: int) -> None:
        self.view_start = value / 100.0
        self.update()

    def ensure_visible(self, t: float) -> None:
        span = self.wave_width() / self.px_per_s
        if t < self.view_start or t > self.view_start + span * 0.95:
            self.view_start = t - span * 0.1
            self._clamp()
            self._sync_scrollbar()

    def refresh(self) -> None:
        self._clamp()
        self._sync_scrollbar()
        self.update()

    # -------------------------------------------------------- disegno
    def resizeEvent(self, _event) -> None:  # noqa: N802
        if self._fit_pending and self.width() > HEADER_W + 100:
            self._fit_pending = False
            self.fit()
        else:
            self.refresh()

    def _tick_step(self) -> float:
        target = 90.0 / self.px_per_s   # circa una tacca ogni 90 px
        for step in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
            if step >= target:
                return step
        return 600.0

    @staticmethod
    def _fmt(t: float, step: float) -> str:
        sign = "-" if t < 0 else ""
        t = abs(t)
        m, s = divmod(t, 60)
        if step < 0.1:
            return f"{sign}{int(m)}:{s:05.2f}"
        if step < 1:
            return f"{sign}{int(m)}:{s:04.1f}"
        return f"{sign}{int(m)}:{int(round(s)):02d}"

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(theme.BG))
        small = QFont(self.font())
        small.setPointSizeF(max(7.5, small.pointSizeF() * 0.8))
        p.setFont(small)

        # righello
        p.fillRect(0, 0, w, RULER_H, QColor(theme.PANEL_2))
        step = self._tick_step()
        t = math.floor(self.view_start / step) * step
        end_t = self.x_to_t(w)
        p.setPen(QColor(theme.MUTED))
        while t <= end_t:
            x = self.t_to_x(t)
            if x >= HEADER_W:
                p.drawLine(QLineF(x, RULER_H - 7, x, RULER_H))
                p.drawText(QPointF(x + 3, RULER_H - 9), self._fmt(t, step))
            t += step

        # tracce
        for i, lane in enumerate(self.lanes):
            top = RULER_H + i * LANE_H
            p.fillRect(0, top, w, LANE_H - 2, QColor(theme.PANEL))
            self._draw_wave(p, lane, top + 4, LANE_H - 10)
            # colonna con il nome
            p.fillRect(0, top, HEADER_W, LANE_H - 2, QColor(theme.PANEL_2))
            p.setPen(QColor(lane.color))
            title_font = QFont(self.font())
            title_font.setBold(True)
            p.setFont(title_font)
            p.drawText(QRectF(10, top + 6, HEADER_W - 14, 22), Qt.AlignLeft | Qt.AlignVCenter, lane.title)
            p.setFont(small)
            p.setPen(QColor(theme.MUTED))
            sub = "riferimento" if not lane.draggable else f"{lane.offset_ms:+.0f} ms"
            p.drawText(QRectF(10, top + 30, HEADER_W - 14, 20), Qt.AlignLeft | Qt.AlignVCenter, sub)

        # zero del piano, cursore e testina
        x0 = self.t_to_x(0.0)
        if x0 >= HEADER_W:
            p.setPen(QPen(QColor(theme.BORDER), 1, Qt.DashLine))
            p.drawLine(QLineF(x0, RULER_H, x0, h))
        xc = self.t_to_x(self.cursor_s)
        if xc >= HEADER_W:
            p.setPen(QPen(QColor(theme.GREEN), 2))
            p.drawLine(QLineF(xc, 0, xc, h))
        if self.playhead_s is not None:
            xp = self.t_to_x(self.playhead_s)
            if xp >= HEADER_W:
                p.setPen(QPen(QColor(theme.TEXT), 2))
                p.drawLine(QLineF(xp, 0, xp, h))
        p.end()

    def _draw_wave(self, p: QPainter, lane: Lane, top: float, height: float) -> None:
        if lane.peaks is None:
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(HEADER_W + 10, top, 300, height), Qt.AlignVCenter, "Preparo la forma d'onda…")
            return
        peaks = lane.peaks
        if peaks.size == 0:
            return
        x_start = max(HEADER_W, int(self.t_to_x(lane.start_s())))
        x_end = min(self.width(), int(self.t_to_x(lane.start_s() + lane.duration_s())) + 1)
        if x_end <= x_start:
            return
        xs = np.arange(x_start, x_end + 1)
        # tempo (dentro la traccia, in secondi del file) di ogni bordo di colonna
        local = (self.view_start + (xs - HEADER_W) / self.px_per_s - lane.start_s()) * lane.stretch
        idx = np.clip((local * PEAK_RATE).astype(np.int64), 0, peaks.size - 1)
        # un valore per colonna: il massimo dei picchi che cadono nella colonna
        vals = np.maximum.reduceat(peaks, idx[:-1]).astype(np.float64)
        vals[-1] = peaks[idx[-2]:idx[-1] + 1].max()
        dup = np.nonzero(np.diff(idx[:-1]) <= 0)[0]
        vals[dup] = peaks[idx[dup]]   # colonne più strette di un picco (zoom molto alto)
        vals = np.sqrt(np.clip(vals, 0.0, 1.0))   # scala più leggibile per i suoni piani
        mid = top + height / 2
        amp = vals * (height / 2 - 1)
        color = QColor(lane.color)
        color.setAlpha(210)
        p.setPen(QPen(color, 1))
        lines = [QLineF(float(x) + 0.5, mid - a, float(x) + 0.5, mid + a)
                 for x, a in zip(xs[:-1], amp)]
        p.drawLines(lines)
        # bordo della traccia
        border = QColor(lane.color)
        border.setAlpha(90)
        p.setPen(QPen(border, 1))
        p.drawRect(QRectF(x_start, top, x_end - x_start - 1, height))

    # -------------------------------------------------------- mouse e tastiera
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position()
        lane = self.lane_at(pos.y())
        if ev.button() == Qt.LeftButton:
            if lane is not None and lane.draggable and pos.x() > HEADER_W and lane.peaks is not None:
                t = self.x_to_t(pos.x())
                if lane.start_s() <= t <= lane.start_s() + lane.duration_s():
                    self._drag = (lane, pos.x(), lane.offset_ms)
                    self.setCursor(Qt.ClosedHandCursor)
                    return
            if pos.x() > HEADER_W:
                self.cursor_s = self.x_to_t(pos.x())
                self.cursorChanged.emit(self.cursor_s)
                self.update()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position()
        if self._drag is not None:
            lane, x0, off0 = self._drag
            dx = pos.x() - x0
            if ev.modifiers() & Qt.ShiftModifier:
                dx *= 0.1   # spostamento fine
            new = max(-MAX_OFFSET_MS, min(MAX_OFFSET_MS, off0 + dx / self.px_per_s * 1000.0))
            self.offsetChanged.emit(lane.key, round(new))
            return
        lane = self.lane_at(pos.y())
        if lane is not None and lane.draggable and pos.x() > HEADER_W:
            t = self.x_to_t(pos.x())
            inside = lane.start_s() <= t <= lane.start_s() + lane.duration_s()
            self.setCursor(Qt.OpenHandCursor if inside else Qt.ArrowCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, _ev) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.OpenHandCursor)
            self.refresh()

    def wheelEvent(self, ev) -> None:  # noqa: N802
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if ev.modifiers() & Qt.ControlModifier:
            self.zoom(1.25 if delta > 0 else 0.8, ev.position().x())
        else:
            span = self.wave_width() / self.px_per_s
            self.view_start -= span * 0.1 * (1 if delta > 0 else -1)
            self.refresh()
        ev.accept()


class SyncDialog(QDialog):
    """Dialogo modale. I dati arrivano già pronti; i calcoli lunghi girano in background.

    ``engine`` serve per l'ascolto, ``render_piano(speed)`` ritorna l'audio del piano
    renderizzato alla velocità data (usato solo se la velocità cambia).
    """

    def __init__(self, parent, *, samplerate: int, engine, piano_audio, piano_events, voice_audio,
                 base_audio, settings: MixSettings, voice_fixed_ms: float, voice_user_ms: float,
                 render_piano, base_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Sincronizza tracce")
        self.setMinimumSize(900, 600)
        self.resize(1150, 720)
        self.sr = samplerate
        self.engine = engine
        self.piano_audio = piano_audio
        self.piano_events = piano_events
        self.voice_audio = voice_audio
        self.base_audio = base_audio
        self.mix = settings
        self.voice_fixed_ms = voice_fixed_ms   # compensazione automatica della latenza (+ correzione globale)
        self.render_piano = render_piano
        self._rendered_speed = 1.0
        self._preview_start = 0.0
        self._preview_task = None
        self._closing = False

        self.lanes: dict[str, Lane] = {}
        order = []
        if piano_audio is not None:
            order.append(Lane("piano", "Piano", theme.ICE, draggable=False))
        if voice_audio is not None:
            order.append(Lane("voice", "Voce", theme.GREEN, offset_ms=voice_fixed_ms + voice_user_ms))
        if base_audio is not None:
            order.append(Lane("base", "Importato", theme.AMBER, offset_ms=settings.base_offset_ms))
        for lane in order:
            self.lanes[lane.key] = lane

        lay = QVBoxLayout(self)
        hint = QLabel("Il piano è il riferimento. Trascina le altre tracce con il mouse "
                      "(tieni premuto Maiusc per uno spostamento fine), oppure scrivi lo spostamento in ms. "
                      "Clic su un punto vuoto per scegliere da dove ascoltare. Ctrl + rotella per lo zoom.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        lay.addWidget(hint)

        self.view = TrackView(order)
        self.view.offsetChanged.connect(self._lane_dragged)
        self.view.cursorChanged.connect(lambda _t: self._update_pos_label())
        lay.addWidget(self.view)
        sb = QScrollBar(Qt.Horizontal)
        self.view.scrollbar = sb
        sb.valueChanged.connect(self.view.scroll_to)
        lay.addWidget(sb)

        zoom_row = QHBoxLayout()
        for text, fn in (("−", lambda: self.view.zoom(0.66)), ("+", lambda: self.view.zoom(1.5)),
                         ("Adatta", self.view.fit)):
            b = QPushButton(text)
            b.setObjectName("nudge")
            b.clicked.connect(fn)
            zoom_row.addWidget(b)
        zoom_row.addWidget(QLabel("Zoom"))
        zoom_row.addStretch(1)
        self.pos_label = QLabel("")
        self.pos_label.setObjectName("hint")
        zoom_row.addWidget(self.pos_label)
        lay.addLayout(zoom_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        self.spins: dict[str, QDoubleSpinBox] = {}
        row = 0
        for key, label in (("voice", "Spostamento voce"), ("base", "Spostamento audio importato")):
            if key not in self.lanes:
                continue
            grid.addWidget(QLabel(label), row, 0)
            spin = QDoubleSpinBox()
            spin.setRange(-MAX_OFFSET_MS, MAX_OFFSET_MS)
            spin.setDecimals(0)
            spin.setSuffix(" ms")
            spin.setSingleStep(1)
            spin.setKeyboardTracking(False)
            spin.setMinimumWidth(130)
            spin.setValue(self.lanes[key].offset_ms if key == "base" else voice_user_ms)
            spin.valueChanged.connect(lambda v, k=key: self._spin_changed(k, v))
            self.spins[key] = spin
            grid.addWidget(spin, row, 1)
            col = 2
            for step in (-100, -10, -1, 1, 10, 100):
                b = QPushButton(f"{step:+d}")
                b.setObjectName("nudge")
                b.setToolTip(f"Sposta di {step:+d} ms ({'prima' if step < 0 else 'dopo'})")
                b.clicked.connect(lambda _c=False, k=key, s=step: self.spins[k].setValue(self.spins[k].value() + s))
                grid.addWidget(b, row, col)
                col += 1
            z = QPushButton("Azzera")
            z.setObjectName("nudge")
            z.clicked.connect(lambda _c=False, k=key: self.spins[k].setValue(0))
            grid.addWidget(z, row, col)
            if key == "voice":
                spin.setToolTip(f"Correzione a mano. Si aggiunge alla compensazione automatica "
                                f"della latenza ({voice_fixed_ms:+.0f} ms).")
            row += 1
        if "piano" in self.lanes and piano_events:
            grid.addWidget(QLabel("Velocità del piano (MIDI)"), row, 0)
            self.speed = QDoubleSpinBox()
            self.speed.setRange(50.0, 200.0)
            self.speed.setDecimals(1)
            self.speed.setSingleStep(0.1)
            self.speed.setSuffix(" %")
            self.speed.setValue(100.0)
            self.speed.setKeyboardTracking(False)
            self.speed.setToolTip("Utile se il MIDI ha un tempo un po' diverso dall'audio importato: "
                                  "sopra 100% il piano va più veloce.")
            self.speed.valueChanged.connect(self._speed_changed)
            grid.addWidget(self.speed, row, 1)
            col = 2
            for step in (-1.0, -0.1, 0.1, 1.0):
                b = QPushButton(f"{step:+.1f}")
                b.setObjectName("nudge")
                b.clicked.connect(lambda _c=False, s=step: self.speed.setValue(self.speed.value() + s))
                grid.addWidget(b, row, col)
                col += 1
            z = QPushButton("100%")
            z.setObjectName("nudge")
            z.clicked.connect(lambda: self.speed.setValue(100.0))
            grid.addWidget(z, row, col)
            row += 1
        else:
            self.speed = None
        grid.setColumnStretch(grid.columnCount(), 1)
        lay.addLayout(grid)

        auto = QHBoxLayout()
        self.btn_auto = QPushButton("✦  Allinea automaticamente l'audio importato al piano")
        self.btn_auto.clicked.connect(self.auto_align)
        self.cb_speed = QCheckBox("Correggi anche la velocità del MIDI")
        self.cb_speed.setToolTip("Più lento: prova velocità dall'80% al 125% per trovare quella che combacia meglio.")
        can_auto = "base" in self.lanes and "piano" in self.lanes and bool(piano_events)
        self.btn_auto.setEnabled(can_auto)
        self.cb_speed.setEnabled(can_auto)
        auto.addWidget(self.btn_auto)
        auto.addWidget(self.cb_speed)
        auto.addStretch(1)
        lay.addLayout(auto)
        self.auto_label = QLabel("" if can_auto else
                                 "L'allineamento automatico serve quando ci sono sia il piano sia un audio importato.")
        self.auto_label.setObjectName("hint")
        self.auto_label.setWordWrap(True)
        lay.addWidget(self.auto_label)

        bottom = QHBoxLayout()
        self.btn_play = QPushButton("▶  Ascolta dal cursore")
        self.btn_play.setObjectName("big")
        self.btn_play.clicked.connect(self.preview)
        self.btn_stop = QPushButton("■  Stop")
        self.btn_stop.setObjectName("big")
        self.btn_stop.clicked.connect(self.stop_preview)
        bottom.addWidget(self.btn_play)
        bottom.addWidget(self.btn_stop)
        bottom.addStretch(1)
        cancel = QPushButton("Annulla")
        cancel.setObjectName("big")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Applica")
        ok.setObjectName("big")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        bottom.addWidget(cancel)
        bottom.addWidget(ok)
        lay.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._update_pos_label()
        self._compute_peaks()

    # -------------------------------------------------------- risultati
    @property
    def base_offset_ms(self) -> float:
        return self.lanes["base"].offset_ms if "base" in self.lanes else self.mix.base_offset_ms

    @property
    def voice_user_offset_ms(self) -> float:
        return self.spins["voice"].value() if "voice" in self.spins else 0.0

    @property
    def piano_speed(self) -> float:
        return self.speed.value() / 100.0 if self.speed is not None else 1.0

    # -------------------------------------------------------- forme d'onda
    def _compute_peaks(self) -> None:
        sources = {"piano": self.piano_audio, "voice": self.voice_audio, "base": self.base_audio}

        def work():
            return {k: align.peaks(a, self.sr, PEAK_RATE) for k, a in sources.items()
                    if a is not None and k in self.lanes}

        def done(res):
            if self._closing:
                return
            for k, pk in res.items():
                self.lanes[k].peaks = pk
            self.view.fit()

        run_task(work, on_done=done, on_error=lambda exc: None)

    # -------------------------------------------------------- spostamenti
    def _lane_dragged(self, key: str, offset_ms: float) -> None:
        if key == "voice":
            self.spins["voice"].setValue(offset_ms - self.voice_fixed_ms)
        else:
            self.spins[key].setValue(offset_ms)

    def _spin_changed(self, key: str, value: float) -> None:
        lane = self.lanes[key]
        lane.offset_ms = value + self.voice_fixed_ms if key == "voice" else value
        self.view.update()
        self._preview_dirty()

    def _speed_changed(self, value: float) -> None:
        self.lanes["piano"].stretch = (value / 100.0) / self._rendered_speed
        self.view.refresh()
        self._preview_dirty()

    def _preview_dirty(self) -> None:
        # se sto ascoltando, riparto dal punto attuale con le nuove impostazioni
        if self.view.playhead_s is not None:
            self._restart_timer = getattr(self, "_restart_timer", None)
            if self._restart_timer is None:
                self._restart_timer = QTimer(self)
                self._restart_timer.setSingleShot(True)
                self._restart_timer.setInterval(250)
                self._restart_timer.timeout.connect(self._restart_preview)
            self._restart_timer.start()

    def _restart_preview(self) -> None:
        if self.view.playhead_s is not None:
            self.preview(start=self.view.playhead_s)

    # -------------------------------------------------------- allineamento automatico
    def auto_align(self) -> None:
        find_speed = self.cb_speed.isChecked()
        self.btn_auto.setEnabled(False)
        self.auto_label.setText("Analizzo le note del piano e l'audio importato…")
        events = self.piano_events
        base = self.base_audio
        sr = self.sr

        def work(progress):
            return align.align_base_to_midi(events, base, sr, find_speed=find_speed,
                                            progress=lambda f: progress(f, ""))

        def prog(frac, _msg):
            if not self._closing:
                self.auto_label.setText(f"Analizzo le note del piano e l'audio importato… {int(frac * 100)}%")

        def done(res):
            if self._closing:
                return
            offset, speed, conf = res
            self.btn_auto.setEnabled(True)
            if conf < 0.2:
                self.auto_label.setText("Non ho trovato un punto in cui piano e audio combaciano con sicurezza: "
                                        "forse non è lo stesso brano. Ho lasciato tutto com'era, sistemalo a mano.")
                return
            if self.speed is not None and find_speed:
                self.speed.setValue(round(speed * 1000) / 10.0)
            self.spins["base"].setValue(round(offset))
            level = "alta" if conf > 0.5 else "media" if conf > 0.3 else "bassa: controlla ad orecchio"
            extra = f", velocità del MIDI {speed * 100:.1f}%" if find_speed else ""
            self.auto_label.setText(f"Fatto: audio importato spostato di {offset:+.0f} ms{extra}. "
                                    f"Affidabilità {level}. Ascolta per controllare.")

        def failed(exc):
            if not self._closing:
                self.btn_auto.setEnabled(True)
                self.auto_label.setText("L'allineamento automatico non è riuscito.")

        run_task(work, on_done=done, on_error=failed, on_progress=prog)

    # -------------------------------------------------------- ascolto
    def _update_pos_label(self) -> None:
        t = self.view.cursor_s
        sign = "-" if t < 0 else ""
        m, s = divmod(abs(t), 60)
        self.pos_label.setText(f"Cursore: {sign}{int(m)}:{s:05.2f}")

    def preview(self, _checked=False, start: float | None = None) -> None:
        start_s = self.view.cursor_s if start is None else start
        speed = self.piano_speed
        settings = MixSettings(piano_volume=self.mix.piano_volume, voice_volume=self.mix.voice_volume,
                               voice_offset_ms=self.lanes["voice"].offset_ms if "voice" in self.lanes else 0.0,
                               base_volume=self.mix.base_volume, base_offset_ms=self.base_offset_ms)
        self.btn_play.setEnabled(False)

        def work():
            piano = self.piano_audio
            if piano is not None and abs(speed - self._rendered_speed) > 1e-6:
                piano = self.render_piano(speed)
                return piano, speed, self._build(piano, settings, start_s)
            return None, None, self._build(piano, settings, start_s)

        def done(res):
            if self._closing:
                return
            piano, rendered, (audio, first_s) = res
            self.btn_play.setEnabled(True)
            if piano is not None:
                # tengo il render nuovo: la forma d'onda ora è quella vera
                self.piano_audio, self._rendered_speed = piano, rendered
                self.lanes["piano"].stretch = 1.0
                self.lanes["piano"].peaks = align.peaks(piano, self.sr, PEAK_RATE)
            if audio.shape[0] == 0:
                return
            self._preview_start = first_s
            self.engine.playback_gain = 1.0
            self.engine.play(audio)
            self.view.playhead_s = first_s

        def failed(exc):
            if not self._closing:
                self.btn_play.setEnabled(True)
                QMessageBox.warning(self, "Ascolto", "Non riesco a preparare l'ascolto.")

        run_task(work, on_done=done, on_error=failed)

    def _build(self, piano, settings: MixSettings, start_s: float):
        """Mix senza effetti dal punto ``start_s`` (secondi sulla linea del tempo del piano)."""
        audio, lead = combine(piano, self.voice_audio, self.sr, settings, self.base_audio)
        first = max(0, int(round(start_s * self.sr)) + lead)
        audio = audio[first:]
        if audio.shape[0]:
            audio, _ = prevent_clipping(audio.copy())
        return audio, (first - lead) / self.sr

    def stop_preview(self) -> None:
        self.engine.stop()
        self.view.playhead_s = None
        self.view.update()

    def _tick(self) -> None:
        if self.view.playhead_s is None:
            return
        pos, total = self.engine.playback_position()
        if self.engine.mode != PLAYING:
            self.view.playhead_s = None
            self.view.update()
            return
        self.view.playhead_s = self._preview_start + pos
        self.view.ensure_visible(self.view.playhead_s)
        self.view.update()

    def done(self, result: int) -> None:  # noqa: D401 - chiusura del dialogo
        self._closing = True
        self.timer.stop()
        self.engine.stop()
        super().done(result)
