"""Main window: control panel on the left, live spectrum plot on the right."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout, QMainWindow, QMessageBox, QWidget,
)

from spectrum_app.core.acquisition import AcquisitionController
from spectrum_app.core.models import DataPoint, SessionMeta
from spectrum_app.core.storage import save_session
from spectrum_app.ui.control_panel import ControlPanel
from spectrum_app.ui.plot_view import PlotView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UHV-SEM Energetic Spectrum")
        self.resize(1100, 680)

        self.panel = ControlPanel()
        self.plot = PlotView()

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self.panel)
        layout.addWidget(self.plot, stretch=1)
        self.setCentralWidget(central)

        self.controller = AcquisitionController(self)

        # Panel -> controller
        self.panel.start_requested.connect(self._start)
        self.panel.stop_requested.connect(self.controller.stop)
        self.panel.save_requested.connect(self._save)
        self.panel.clear_requested.connect(self._clear)

        # Controller -> UI
        self.controller.point_added.connect(self.plot.add_point)
        self.controller.stats_updated.connect(self.panel.update_stats)
        self.controller.status_changed.connect(self._on_status)
        self.controller.error.connect(self._on_error)

        self.statusBar().showMessage("Ready")

    # ---- slots ----
    def _start(self, config) -> None:
        if not config.watch_folder or not Path(config.watch_folder).is_dir():
            QMessageBox.warning(self, "No folder", "Choose a valid scan folder first.")
            return
        self.plot.clear_points()
        self.plot.configure(config.x_axis, time.time())
        self.controller.start(config)
        self.panel.set_running(self.controller.is_running)

    def _on_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)
        self.panel.set_running(self.controller.is_running)

    def _on_error(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 5000)

    def _clear(self) -> None:
        self.plot.clear_points()
        self.controller._points = []
        self.panel.update_stats({"count": 0})

    def _save(self, meta: SessionMeta) -> None:
        points = self.controller.points
        if not points:
            QMessageBox.information(self, "Nothing to save", "No data points yet.")
            return
        base = Path(__file__).resolve().parents[2] / "sessions"
        try:
            png = self.plot.export_png_bytes()
            out = save_session(base, meta, points, self.controller.config, png)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.statusBar().showMessage(f"Saved to {out}", 8000)
        QMessageBox.information(self, "Saved", f"Measurement saved to:\n{out}")

    def closeEvent(self, event):
        self.controller.stop()
        super().closeEvent(event)
