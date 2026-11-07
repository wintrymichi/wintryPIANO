"""Entry point: sets up logging and error handling, then opens the window."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

# The PortAudio DLL with ASIO must be chosen before importing sounddevice.
os.environ.setdefault("SD_ENABLE_ASIO", "1")

from wintrypiano import APP_NAME, __version__  # noqa: E402
from wintrypiano.paths import log_file  # noqa: E402

log = logging.getLogger("wintrypiano")


def setup_logging() -> None:
    handler = RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wintrypiano", description=APP_NAME)
    ap.add_argument("--demo", action="store_true", help="simulate the notes of a MIDI piano")
    args = ap.parse_args(argv)
    setup_logging()
    log.info("starting %s %s (Python %s)", APP_NAME, __version__, sys.version.split()[0])

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print("PySide6 is missing. Run the installer (install.bat) and try again.")
        return 1

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    from wintrypiano.errors import friendly_message
    from wintrypiano.gui import theme

    app.setStyleSheet(theme.QSS)

    def show_error(exc: BaseException) -> None:
        try:
            QMessageBox.warning(None, APP_NAME, friendly_message(exc))
        except Exception:  # noqa: BLE001
            pass

    def excepthook(exc_type, exc, tb):
        log.error("unhandled error", exc_info=(exc_type, exc, tb))
        if issubclass(exc_type, KeyboardInterrupt):
            app.quit()
            return
        show_error(exc)

    def thread_hook(args):
        log.error("unhandled error in thread %s", args.thread.name if args.thread else "?",
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook

    try:
        from wintrypiano.config import Config
        from wintrypiano.gui.main_window import MainWindow

        cfg = Config.load()
        win = MainWindow(cfg, demo=args.demo)
        win.show()
    except Exception as exc:  # noqa: BLE001
        log.exception("startup failed")
        show_error(exc)
        return 1
    return app.exec()
