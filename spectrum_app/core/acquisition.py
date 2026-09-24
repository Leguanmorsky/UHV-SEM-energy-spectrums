"""Orchestrates a sweep: set bias -> new scan -> brightness -> data point.

The EA power supply is now driven here. When ``config.drive_supply`` is on and the
x-axis is ``bias`` and a supply is connected:

  * ``start`` applies the safety limits, sets the first bias and turns the output on.
  * For each scan that arrives, the worker reads the **actual** voltage back from the
    supply, tags the point with it, then sets the next bias in the schedule.
  * The sweep ends when the next bias would pass ``bias_stop`` (honouring the sign of
    ``bias_step``); the output is then turned off.

If no supply is connected (or the x-axis is ``index`` / ``time``), the behaviour is
exactly as before: bias is the computed ``bias_start + n * bias_step`` and no hardware
is touched. ``FolderWatcher`` remains the signal source and can later be swapped for a
DAQ / SEM-API source emitting the same ``new_image`` signal.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, QThread, QTimer, Slot

from spectrum_app.config import AcquisitionConfig
from spectrum_app.core.folder_watcher import FolderWatcher
from spectrum_app.core.image_metrics import mean_brightness, wait_until_stable
from spectrum_app.core.models import DataPoint
from spectrum_app.sources.power_supply import PowerSupply


class _Worker(QObject):
    """Does the (blocking) image read and supply I/O off the GUI thread."""
    point_ready = Signal(object)   # DataPoint
    failed = Signal(str)
    warning = Signal(str)          # non-fatal notes (e.g. bias clamped)
    sweep_finished = Signal()      # reached bias_stop

    def __init__(self, config: AcquisitionConfig, supply: Optional[PowerSupply],
                 driving: bool, base_index: int = 0):
        super().__init__()
        self._config = config
        self._supply = supply
        self._driving = driving
        self._base_index = base_index   # global point index offset (for "Continue")
        self._count = 0                 # segment-local step counter
        self._done = False

    @Slot(str)
    def handle(self, path: str) -> None:
        if self._done:
            return
        cfg = self._config
        if cfg.settle_seconds > 0:
            time.sleep(cfg.settle_seconds)
        if not wait_until_stable(path, cfg.stability_checks, cfg.stability_interval):
            self.failed.emit(f"Skipped (not stable): {Path(path).name}")
            return
        try:
            value = mean_brightness(path, cfg.roi)
        except Exception as exc:  # noqa: BLE001 - report and continue
            self.failed.emit(f"Read error {Path(path).name}: {exc}")
            return

        # Intended (signed) sample bias for this scan. The supply only outputs a
        # positive magnitude; the sign comes from the schedule (negative means the
        # output leads are swapped for this segment).
        setpoint = cfg.bias_start + self._count * cfg.bias_step
        bias = None
        if cfg.x_axis == "bias":
            if self._driving and self._supply is not None:
                try:
                    magnitude = float(self._supply.read_actual()["V"])
                    bias = math.copysign(magnitude, setpoint) if setpoint else magnitude
                except Exception as exc:  # noqa: BLE001
                    self.failed.emit(f"Supply read failed: {exc}")
                    bias = setpoint
            else:
                bias = setpoint

        point = DataPoint(
            index=self._base_index + self._count,
            timestamp=time.time(),
            brightness=value,
            bias_v=bias,
            source=path,
        )
        self._count += 1
        self.point_ready.emit(point)

        # Advance the sweep to the next bias (only when driving).
        if self._driving and self._supply is not None and cfg.x_axis == "bias":
            self._advance(cfg)

    def _advance(self, cfg: AcquisitionConfig) -> None:
        nxt = cfg.bias_start + self._count * cfg.bias_step
        if _past_stop(nxt, cfg.bias_stop, cfg.bias_step):
            self._done = True
            self.sweep_finished.emit()
            return
        try:
            # Command the magnitude; polarity is set by the cabling for this segment.
            used = self._supply.set_voltage(abs(nxt))
            if abs(used - abs(nxt)) > 1e-6:
                self.warning.emit(f"Bias |{nxt:.3g}| V clamped to {used:.3g} V")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Set bias failed: {exc}")


def _past_stop(value: float, stop: Optional[float], step: float) -> bool:
    """True once ``value`` has moved beyond ``stop`` in the sweep direction."""
    if stop is None or step == 0:
        return False
    return value > stop if step > 0 else value < stop


def _synthetic_signal(bias: float, cfg: AcquisitionConfig) -> float:
    """A smooth stand-in signal for test mode when no supply/current is available:
    a Gaussian bump centred in the sweep so the graph forms a recognisable curve."""
    start = cfg.bias_start
    stop = cfg.bias_stop if cfg.bias_stop is not None else start + 20 * (cfg.bias_step or 1)
    centre = (start + stop) / 2.0
    width = max(abs(stop - start) / 4.0, 1e-6)
    return 100.0 * math.exp(-((bias - centre) ** 2) / (2 * width ** 2))


class AcquisitionController(QObject):
    """Public controller the UI talks to."""
    point_added = Signal(object)      # DataPoint
    stats_updated = Signal(dict)
    status_changed = Signal(str)
    error = Signal(str)
    sweep_finished = Signal()

    def __init__(self, supply: Optional[PowerSupply] = None, parent=None):
        super().__init__(parent)
        self._supply = supply
        self._config: AcquisitionConfig | None = None
        self._watcher: FolderWatcher | None = None
        self._worker: _Worker | None = None
        self._thread: QThread | None = None
        self._points: list[DataPoint] = []
        self._t0 = 0.0
        self._running = False
        self._driving = False
        # test mode (timer-driven, no folder)
        self._test_timer: QTimer | None = None
        self._test_count = 0
        self._test_base_index = 0
        self._test_done = False

    @property
    def points(self) -> list[DataPoint]:
        return self._points

    @property
    def config(self) -> AcquisitionConfig | None:
        return self._config

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, config: AcquisitionConfig, append: bool = False) -> None:
        """Begin a sweep. With ``append`` the existing points and graph are kept,
        so a second segment (e.g. the negative-bias half after swapping leads)
        continues on the same graph."""
        if not config.test_mode:
            folder = Path(config.watch_folder)
            if not folder.is_dir():
                self.error.emit(f"Watch folder does not exist: {config.watch_folder}")
                return

        self._config = config
        base_index = self._prepare_points(append)
        self._driving = bool(
            config.drive_supply
            and config.x_axis == "bias"
            and self._supply is not None
            and self._supply.is_connected
        )
        self._prime_supply(config)

        if config.test_mode:
            self._start_test_mode(config, base_index)
            return

        # Worker on its own thread for blocking file reads + supply I/O.
        self._worker = _Worker(config, self._supply, self._driving, base_index)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._worker.point_ready.connect(self._on_point)
        self._worker.failed.connect(self.error)
        self._worker.warning.connect(self.error)
        self._worker.sweep_finished.connect(self._on_sweep_finished)
        self._thread.start()

        # Optionally seed with files already present.
        folder = Path(config.watch_folder)
        if config.process_existing:
            for p in sorted(folder.glob("*")):
                if p.is_file():
                    self._dispatch(str(p))

        self._watcher = FolderWatcher(str(folder), config.file_patterns)
        self._watcher.new_image.connect(self._dispatch)
        self._watcher.start()

        self._running = True
        self.status_changed.emit(f"Watching {folder}")
        self._emit_stats()

    def _prepare_points(self, append: bool) -> int:
        """Reset or extend the point list; return the starting global index."""
        if append and self._points:
            return self._points[-1].index + 1
        self._points = []
        self._t0 = time.time()
        return 0

    def _prime_supply(self, config: AcquisitionConfig) -> None:
        """Bring the supply to the sweep's start (limits, first bias, output on).
        The supply outputs a positive magnitude; the sign is set by the cabling."""
        if not self._driving:
            return
        try:
            self._apply_limits(config)
            self._apply_bias(abs(config.bias_start))
            self._supply.output_on(True)
            self.status_changed.emit(f"Output ON, bias {config.bias_start:.3g} V")
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"Supply start failed: {exc}")
            self._driving = False

    # ---- test mode: step the bias on a timer, no folder needed ----
    def _start_test_mode(self, config: AcquisitionConfig, base_index: int) -> None:
        self._test_base_index = base_index
        self._test_count = 0
        self._test_done = False
        interval_ms = int(max(0.05, config.test_interval) * 1000)
        self._test_timer = QTimer(self)
        self._test_timer.setInterval(interval_ms)
        self._test_timer.timeout.connect(self._test_tick)
        self._running = True
        self.status_changed.emit(
            f"TEST MODE — stepping bias every {config.test_interval:.3g} s")
        self._emit_stats()
        self._test_tick()          # record the first point immediately
        self._test_timer.start()

    def _test_tick(self) -> None:
        if self._test_done:
            return
        cfg = self._config
        setpoint = cfg.bias_start + self._test_count * cfg.bias_step

        # Signal (y): the supply's actual current when connected, else a synthetic
        # bell curve over the sweep so the graph shows something on the bench.
        bias = None
        if self._driving and self._supply is not None:
            try:
                actual = self._supply.read_actual()
                magnitude = float(actual["V"])
                bias = math.copysign(magnitude, setpoint) if setpoint else magnitude
                signal = float(actual["I"])
            except Exception as exc:  # noqa: BLE001
                self.error.emit(f"Supply read failed: {exc}")
                bias = setpoint
                signal = 0.0
        else:
            bias = setpoint if cfg.x_axis == "bias" else None
            signal = _synthetic_signal(setpoint, cfg)

        point = DataPoint(
            index=self._test_base_index + self._test_count,
            timestamp=time.time(),
            brightness=signal,
            bias_v=bias,
            source="test",
        )
        self._test_count += 1
        self._on_point(point)

        # Advance the bias for the next tick.
        nxt = cfg.bias_start + self._test_count * cfg.bias_step
        if _past_stop(nxt, cfg.bias_stop, cfg.bias_step):
            self._test_done = True
            self._on_sweep_finished()
            return
        if self._driving and self._supply is not None:
            try:
                self._supply.set_voltage(abs(nxt))
            except Exception as exc:  # noqa: BLE001
                self.error.emit(f"Set bias failed: {exc}")

    def _dispatch(self, path: str) -> None:
        # Hand the path to the worker thread (queued connection).
        if self._worker is not None:
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(
                self._worker, "handle", Qt.QueuedConnection, Q_ARG(str, path)
            )

    def _on_point(self, point: DataPoint) -> None:
        self._points.append(point)
        self.point_added.emit(point)
        self._emit_stats()

    def _on_sweep_finished(self) -> None:
        self.status_changed.emit("Sweep finished — output OFF")
        self.stop()
        self.sweep_finished.emit()

    def _apply_limits(self, config: AcquisitionConfig) -> None:
        """Push the safety limits to the supply before the output goes live."""
        self._supply.ack_alarm()
        if config.current_limit > 0:
            self._supply.set_current(config.current_limit)
        if config.ovp > 0:
            self._supply.set_ovp(config.ovp)
        if config.ocp > 0:
            self._supply.set_ocp(config.ocp)

    def _apply_bias(self, volts: float) -> None:
        """Command the real output voltage (clamped inside the supply wrapper)."""
        self._supply.set_voltage(volts)

    def _emit_stats(self) -> None:
        vals = [p.brightness for p in self._points]
        elapsed = time.time() - self._t0 if self._t0 else 0.0
        stats = {
            "count": len(self._points),
            "last": vals[-1] if vals else None,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
            "current_bias": self._points[-1].bias_v if self._points else (
                self._config.bias_start if self._config else None),
            "elapsed_s": elapsed,
            "rate_per_min": (len(self._points) / elapsed * 60.0) if elapsed > 0 else 0.0,
        }
        self.stats_updated.emit(stats)

    def stop(self) -> None:
        if self._test_timer is not None:
            self._test_timer.stop()
            self._test_timer = None
        self._test_done = True
        if self._driving and self._supply is not None:
            try:
                self._supply.output_on(False)
            except Exception as exc:  # noqa: BLE001
                self.error.emit(f"Turning output off failed: {exc}")
        self._driving = False
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        self._worker = None
        self._running = False
        self.status_changed.emit("Stopped")
