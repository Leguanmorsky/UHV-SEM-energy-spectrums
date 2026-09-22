"""Application entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from spectrum_app.ui.main_window import MainWindow

ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "app.ico"


def _use_app_icon_on_taskbar() -> None:
    """On Windows, give the app its own taskbar identity so it shows our icon
    instead of the generic python(w) one."""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "uhvsem.spectrum.app"
            )
        except Exception:
            pass


def main() -> int:
    _use_app_icon_on_taskbar()
    app = QApplication(sys.argv)
    app.setApplicationName("UHV-SEM Energetic Spectrum")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
