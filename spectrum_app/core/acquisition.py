"""Orchestrates a sweep: new scan -> brightness -> data point (+ bias schedule).

This is the seam where instrument control will later plug in:
  * ``_apply_bias`` currently only records the commanded value. When the
    EA power supply module exists, set the real voltage there.
  * ``FolderWatcher`` is the current signal source; a DAQ or SEM-API source
    can replace it by emitting the same ``new_image`` / value signal.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QThread

from spectrum_app.config import AcquisitionConfig
from spectrum_app.core.folder_watcher import FolderWatcher
from spectrum_app.core.image_metrics import mean_brightness, wait_until_stable
from spectrum_app.core.models import DataPoint


class _Worker(QObject):
    """Does the (blocking) image read off the GUI thread."""
    point_ready = Signal(object)   # DataPoint
    failed = Signal(str)

    def __init__(self, config: AcquisitionConfig):
        super().__init__()
        self._config = config
        self._count = 0

    def handle(self, path: str) -> None:
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
        bias = None
        if cfg.x_axis == "bias":
            bias = cfg.bias_start + self._count * cfg.bias_step
        point = DataPoint(
            index=self._count,
            timestamp=time.time(),
            brightness=value,
            bias_v=bias,
            source=path,
        )
        self._count += 1
        self.point_ready.emit(point)


class AcquisitionController(QObject):
    """Public controller the UI talks to."""
    point_added = Signal(object)      # DataPoint
    stats_updated = Signal(dict)
    status_changed = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config: AcquisitionConfig | None = None
        self._watcher: FolderWatcher | None = None
        self._worker: _Worker | None = None
        self._thread: QThread | None = None
        self._points: list[DataPoint] = []
        self._t0 = 0.0
        self._running = False

    @property
    def points(self) -> list[DataPoint]:
        return self._points

    @property
    def config(self) -> AcquisitionConfig | None:
        return self._config

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, config: AcquisitionConfig) -> None:
        folder = Path(config.watch_folder)
        if not folder.is_dir():
            self.error.emit(f"Watch folder does not exist: {config.watch_folder}")
            return
        self._config = config
        self._points = []
        self._t0 = time.time()

        # Worker on its own thread for blocking file reads.
        self._worker = _Worker(config)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._worker.point_ready.connect(self._on_point)
        self._worker.failed.connect(self.error)
        self._thread.start()

        # Optionally seed with files already present.
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

    def _dispatch(self, path: str) -> None:
        # Hand the path to the worker thread (queued connection).
        if self._worker is not None:
            # invoke handle() in the worker's thread
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(
                self._worker, "handle", Qt.QueuedConnection, Q_ARG(str, path)
            )

    def _on_point(self, point: DataPoint) -> None:
        self._points.append(point)
        self.point_added.emit(point)
        self._emit_stats()

    def _apply_bias(self, volts: float) -> None:
        """Hook for real power-supply control. Currently a no-op placeholder."""
        # TODO: power_supply.set_voltage(volts)
        pass

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
