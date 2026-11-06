"""Widget riutilizzabili: indicatore di livello, pannelli, pulsanti grandi."""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget

from wintrypiano.gui import theme


class Panel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(22, 18, 22, 18)
        self.layout_.setSpacing(12)


def big_button(text: str, record: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("record" if record else "big")
    b.setCursor(Qt.PointingHandCursor)
    return b


def set_active(button: QPushButton, active: bool) -> None:
    button.setProperty("active", "true" if active else "false")
    button.style().unpolish(button)
    button.style().polish(button)


class LevelMeter(QWidget):
    """Barra di livello in dBFS con picco trattenuto e avviso di saturazione."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(22)
        self._level = 0.0
        self._hold = 0.0
        self._clip = False

    def set_level(self, peak: float, clip: bool = False) -> None:
        db = 20 * math.log10(max(peak, 1e-5))
        frac = max(0.0, min(1.0, (db + 60.0) / 60.0))
        self._level = max(frac, self._level * 0.85)
        self._hold = max(frac, self._hold - 0.01)
        if clip:
            self._clip = True
        self.update()

    def reset_clip(self) -> None:
        self._clip = False
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - API Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.PANEL_2))
        p.drawRoundedRect(r, 6, 6)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0.0, QColor(theme.ICE_DARK))
        g.setColorAt(0.75, QColor(theme.ICE))
        g.setColorAt(0.9, QColor(theme.AMBER))
        g.setColorAt(1.0, QColor(theme.RED))
        filled = QRectF(r.left(), r.top(), r.width() * self._level, r.height())
        p.setBrush(g)
        p.drawRoundedRect(filled, 6, 6)
        x = r.left() + r.width() * self._hold
        p.setBrush(QColor(theme.TEXT))
        p.drawRect(QRectF(x - 1, r.top(), 2, r.height()))
        if self._clip:
            p.setBrush(QColor(theme.RED))
            p.drawRoundedRect(QRectF(r.right() - 16, r.top(), 16, r.height()), 4, 4)
        p.end()
