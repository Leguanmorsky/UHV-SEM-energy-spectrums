"""Main window: control panel on the left, live spectrum plot on the right."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QMainWindow, QMessageBox, QScrollArea, QWidget,
)

from spectrum_app.core.acquisition import AcquisitionController
from spectrum_app.core.models import SessionMeta
from spectrum_app.core.storage import save_session
from spectrum_app.sources.power_supply import PowerSupply
from spectrum_app.ui.control_panel import ControlPanel
from spectrum_app.ui.plot_view import PlotView

# Seconds to wait for a connection attempt before giving up. A dead or Bluetooth
# COM port can block the serial open() indefinitely, so the attempt runs on a
# background thread and this watchdog reports an error if it overruns.
CONNECT_TIMEOUT_MS = 10_000


class _ConnectWorker(QObject):
    """Runs the (blocking) auto-detect / connect off the GUI thread."""
    succeeded = Signal(dict, str)   # info, resolved port
    failed = Signal(str)

    def __init__(self, supply: PowerSupply, port: str):
        super().__init__()
        self._supply = supply
        self._port = port

    @Slot()
    def run(self) -> None:
        try:
            port = self._port
            if port == "Auto":
                found = PowerSupply.auto_detect()
                if not found:
                    self.failed.emit("No EA PS 2000 found on any serial port.")
                    return
                port = found
            info = self._supply.connect(port)
            self.succeeded.emit(info, port)
        except Exception as exc:  # noqa: BLE001 - report to the UI
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UHV-SEM Energetic Spectrum")
        self.resize(1160, 640)
        self.setMinimumHeight(480)

        self.supply = PowerSupply()
        self.panel = ControlPanel()
        self.plot = PlotView()

        # The left panel can be taller than the screen, so make it scroll while the
        # graph on the right keeps its size and fills the remaining width.
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setWidget(self.panel)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_scroll.setFixedWidth(self.panel.maximumWidth() + 22)  # panel + scrollbar room

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(panel_scroll)
        layout.addWidget(self.plot, stretch=1)
        self.setCentralWidget(central)

        self.controller = AcquisitionController(self.supply, self)

        # Background connection state (threaded connect + timeout watchdog).
        self._connecting = False
        self._active_worker: _ConnectWorker | None = None
        self._connect_timer: QTimer | None = None
        self._conn_threads: list[tuple[QThread, _ConnectWorker]] = []

        # Panel -> controller / supply
        self.panel.start_requested.connect(self._start)
        self.panel.continue_requested.connect(self._continue)
        self.panel.stop_requested.connect(self.controller.stop)
        self.panel.save_requested.connect(self._save)
        self.panel.clear_requested.connect(self._clear)
        self.panel.connect_requested.connect(self._connect_supply)
        self.panel.disconnect_requested.connect(self._disconnect_supply)

        # Controller -> UI
        self.controller.point_added.connect(self.plot.add_point)
        self.controller.stats_updated.connect(self.panel.update_stats)
        self.controller.status_changed.connect(self._on_status)
        self.controller.error.connect(self._on_error)
        self.controller.sweep_finished.connect(self._on_sweep_finished)

        # Live power-supply readout.
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._poll_supply)
        self._poll.start()

        self.panel.refresh_ports()
        self.statusBar().showMessage("Ready")

    # ---- power supply ----
    def _connect_supply(self, port: str) -> None:
        if self._connecting:
            return
        self._connecting = True
        self.panel.set_connecting(True)
        self.statusBar().showMessage(f"Connecting to {port}…")

        thread = QThread(self)
        worker = _ConnectWorker(self.supply, port)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_connect_ok)
        worker.failed.connect(self._on_connect_fail)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda t=thread: self._reap_thread(t))
        self._conn_threads.append((thread, worker))   # keep refs alive
        self._active_worker = worker
        thread.start()

        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self._on_connect_timeout)
        self._connect_timer.start(CONNECT_TIMEOUT_MS)

    def _stop_connect_timer(self) -> None:
        if self._connect_timer is not None:
            self._connect_timer.stop()
            self._connect_timer = None

    def _on_connect_ok(self, info: dict, port: str) -> None:
        if self.sender() is not self._active_worker:
            # A timed-out attempt that finally connected — undo it so the UI and
            # the hardware don't disagree.
            self.supply.disconnect()
            return
        self._active_worker = None
        self._connecting = False
        self._stop_connect_timer()
        label = f"{info.get('type', 'PS 2000')} · SN {info.get('serial', '?')} · {port}"
        self.panel.set_connecting(False)
        self.panel.set_connected(True, label)
        self.statusBar().showMessage(f"Connected: {label}", 6000)

    def _on_connect_fail(self, msg: str) -> None:
        if self.sender() is not self._active_worker:
            return
        self._active_worker = None
        self._connecting = False
        self._stop_connect_timer()
        self.panel.set_connecting(False)
        self.panel.set_connected(False, "Connect failed")
        self.statusBar().showMessage("Connection failed", 6000)
        QMessageBox.critical(self, "Connection failed", msg)

    def _on_connect_timeout(self) -> None:
        if not self._connecting:
            return
        self._connecting = False
        self._active_worker = None   # orphan the still-blocked attempt
        self._connect_timer = None
        self.panel.set_connecting(False)
        self.panel.set_connected(False, "Connection timed out")
        self.statusBar().showMessage("Connection timed out", 6000)
        QMessageBox.warning(
            self, "Connection timed out",
            "The power supply did not respond in time.\n\n"
            "Check that it is powered on, the USB/serial cable is connected, "
            "and the selected COM port is correct — then try again.")

    def _reap_thread(self, thread: QThread) -> None:
        thread.wait(50)
        self._conn_threads = [(t, w) for (t, w) in self._conn_threads if t is not thread]
        thread.deleteLater()

    def _disconnect_supply(self) -> None:
        self.supply.disconnect()
        self.panel.set_connected(False)
        self.panel.update_actual(None)
        self.statusBar().showMessage("Power supply disconnected", 4000)

    def _poll_supply(self) -> None:
        if not self.supply.is_connected:
            return
        try:
            self.panel.update_actual(self.supply.read_actual())
        except Exception:  # noqa: BLE001 - transient serial hiccup; skip this tick
            pass

    # ---- acquisition ----
    def _start(self, config) -> None:
        self._begin(config, append=False)

    def _continue(self, config) -> None:
        self._begin(config, append=True)

    def _begin(self, config, append: bool) -> None:
        if not config.test_mode:
            if not config.watch_folder or not Path(config.watch_folder).is_dir():
                QMessageBox.warning(self, "No folder",
                                    "Choose a valid scan folder first, or enable Test mode.")
                return

        want_drive = (config.drive_supply and config.x_axis == "bias")
        # In test mode without a connected supply we still run, using a synthetic
        # signal; only a real (connected) sweep applies power.
        if want_drive and not self.supply.is_connected and not config.test_mode:
            QMessageBox.warning(
                self, "Not connected",
                "Connect the power supply first, or turn off "
                "'Drive the supply during a bias sweep'.")
            return

        driving = want_drive and self.supply.is_connected
        if driving:
            span = (f"from {config.bias_start:.3g} V"
                    + (f" to {config.bias_stop:.3g} V" if config.bias_stop is not None
                       else f" in steps of {config.bias_step:.3g} V"))
            polarity = "NEGATIVE (leads must be swapped)" if (
                config.bias_start < 0 or (config.bias_stop or 0) < 0) else "POSITIVE"
            resp = QMessageBox.question(
                self, "Apply power to probe?",
                f"The output will turn ON and sweep the bias {span}.\n"
                f"Polarity: {polarity}.\n"
                f"Current limit {config.current_limit:.3g} A"
                + (f", OVP {config.ovp:.3g} V" if config.ovp > 0 else "")
                + (".\n\nCheck the output leads match the polarity above.\n\nContinue?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return

        if not append:
            self.plot.clear_points()
            self.plot.configure(config.x_axis, time.time())
        self.controller.start(config, append=append)
        self.panel.set_running(self.controller.is_running)

    def _on_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)
        self.panel.set_running(self.controller.is_running)

    def _on_error(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 5000)

    def _on_sweep_finished(self) -> None:
        self.panel.set_running(False)
        QMessageBox.information(
            self, "Sweep finished",
            "Reached the end of the bias sweep. The output has been turned off.")

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
        self._poll.stop()
        self._stop_connect_timer()
        self.controller.stop()
        self.supply.disconnect()
        super().closeEvent(event)
