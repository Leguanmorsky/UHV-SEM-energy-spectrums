"""Live spectrum plot built on pyqtgraph."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QBuffer, QByteArray, QIODevice

from spectrum_app.core.models import DataPoint

pg.setConfigOptions(antialias=True, background="w", foreground="k")

_X_LABELS = {
    "bias": ("Sample bias", "V"),
    "index": ("Scan index", ""),
    "time": ("Time since start", "s"),
}


class PlotView(pg.PlotWidget):
    """Scatter + line of brightness vs. the chosen x-axis, updated point by point."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._x_axis = "bias"
        self._t0 = 0.0
        self._xs: list[float] = []
        self._ys: list[float] = []

        self.showGrid(x=True, y=True, alpha=0.3)
        self._curve = self.plot([], [], pen=pg.mkPen("#1f6feb", width=2))
        self._scatter = pg.ScatterPlotItem(size=7, brush=pg.mkBrush("#1f6feb"),
                                            pen=pg.mkPen("#0b3d91"))
        self.addItem(self._scatter)
        self.setLabel("left", "Mean brightness", units="a.u.")
        self._apply_x_label()

    def _apply_x_label(self) -> None:
        name, unit = _X_LABELS.get(self._x_axis, ("x", ""))
        self.setLabel("bottom", name, units=unit)

    def configure(self, x_axis: str, t0: float) -> None:
        self._x_axis = x_axis
        self._t0 = t0
        self._apply_x_label()

    def clear_points(self) -> None:
        self._xs.clear()
        self._ys.clear()
        self._curve.setData([], [])
        self._scatter.setData([], [])

    def add_point(self, point: DataPoint) -> None:
        self._xs.append(point.x_value(self._x_axis, self._t0))
        self._ys.append(point.brightness)
        self._curve.setData(self._xs, self._ys)
        self._scatter.setData(self._xs, self._ys)

    def export_png_bytes(self) -> bytes:
        """Render the current plot to PNG bytes for saving with the session."""
        pixmap = self.grab()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pixmap.save(buf, "PNG")
        data = bytes(buf.data())
        buf.close()
        return data
