"""Dark winter theme."""

BG = "#0b1220"
PANEL = "#121c2e"
PANEL_2 = "#18243a"
BORDER = "#24344f"
TEXT = "#e7f0fb"
MUTED = "#8ea3bf"
ICE = "#8fd3ff"
ICE_DARK = "#3a8fc4"
RED = "#ff5a6e"
GREEN = "#6fe3b0"
AMBER = "#ffc566"

QSS = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 11pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#central {{ background: {BG}; }}
QLabel#title {{ font-size: 22pt; font-weight: 300; color: {ICE}; letter-spacing: 2px; }}
QLabel#subtitle {{ color: {MUTED}; }}
QLabel#bigTime {{ font-size: 34pt; font-weight: 300; color: {TEXT}; }}
QLabel#countIn {{ font-size: 48pt; font-weight: 600; color: {AMBER}; }}
QLabel#hint {{ color: {MUTED}; }}
QLabel#warn {{ color: {RED}; font-weight: 600; }}
QFrame#panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ border-color: {ICE_DARK}; }}
QPushButton:disabled {{ color: #4d5d75; border-color: #1c2840; }}
QPushButton#big {{ font-size: 15pt; min-height: 64px; min-width: 150px; border-radius: 16px; }}
QPushButton#record {{ font-size: 15pt; min-height: 64px; min-width: 150px; border-radius: 16px;
    background: #2a1620; border: 1px solid #6b2a3a; color: #ffd6dc; }}
QPushButton#record:hover {{ border-color: {RED}; }}
QPushButton#record[active="true"] {{ background: {RED}; color: white; }}
QPushButton#nudge {{ padding: 4px 8px; min-width: 44px; border-radius: 8px; }}
QPushButton#step {{ font-size: 12pt; padding: 12px 18px; border-radius: 12px; background: {PANEL}; color: {MUTED}; }}
QPushButton#step:checked {{ background: {ICE_DARK}; color: white; border-color: {ICE}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: {PANEL_2}; }}
QCheckBox::indicator:checked {{ background: {ICE}; border-color: {ICE}; }}
QSlider::groove:horizontal {{ height: 6px; background: {PANEL_2}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ICE_DARK}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ICE}; width: 18px; margin: -7px 0; border-radius: 9px; }}
QSpinBox, QDoubleSpinBox, QComboBox {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px 8px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; selection-background-color: {ICE_DARK}; }}
QScrollBar:horizontal {{ background: {PANEL}; height: 12px; border-radius: 6px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 6px; min-width: 40px; }}
QScrollBar::handle:horizontal:hover {{ background: {ICE_DARK}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
QMenuBar {{ background: {BG}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {ICE_DARK}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
QProgressBar {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {ICE_DARK}; border-radius: 6px; }}
QMessageBox {{ background: {PANEL}; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""
