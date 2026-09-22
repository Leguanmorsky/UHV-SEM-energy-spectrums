"""Left-hand control / management panel."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from spectrum_app.config import ROI, AcquisitionConfig
from spectrum_app.core.models import SessionMeta


class ControlPanel(QWidget):
    start_requested = Signal(object)   # AcquisitionConfig
    stop_requested = Signal()
    save_requested = Signal(object)    # SessionMeta
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        root = QVBoxLayout(self)

        # --- Source folder ---
        src = QGroupBox("Scan folder")
        src_l = QVBoxLayout(src)
        row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder the microscope writes scans to")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder_edit)
        row.addWidget(browse)
        src_l.addLayout(row)
        self.process_existing = QCheckBox("Also process files already there")
        src_l.addWidget(self.process_existing)
        root.addWidget(src)

        # --- X axis / bias schedule ---
        bias = QGroupBox("X-axis / bias schedule")
        form = QFormLayout(bias)
        self.x_axis = QComboBox()
        self.x_axis.addItems(["bias", "index", "time"])
        self.bias_start = self._dspin(-1000, 1000, 0.0, " V")
        self.bias_step = self._dspin(-1000, 1000, 1.0, " V")
        self.settle = self._dspin(0, 60, 0.0, " s")
        form.addRow("X axis", self.x_axis)
        form.addRow("Bias start", self.bias_start)
        form.addRow("Bias step / scan", self.bias_step)
        form.addRow("Settle after new file", self.settle)
        root.addWidget(bias)

        # --- Metadata ---
        meta = QGroupBox("Measurement description")
        mform = QFormLayout(meta)
        self.sample = QLineEdit(); self.sample.setPlaceholderText("Platinum")
        self.temperature = QLineEdit(); self.temperature.setPlaceholderText("400")
        self.operator = QLineEdit()
        self.notes = QLineEdit()
        mform.addRow("Sample", self.sample)
        mform.addRow("Temperature", self.temperature)
        mform.addRow("Operator", self.operator)
        mform.addRow("Notes", self.notes)
        root.addWidget(meta)

        # --- Controls ---
        controls = QHBoxLayout()
        self.start_btn = QPushButton("START")
        self.start_btn.setStyleSheet("background:#1a7f37;color:white;font-weight:bold;padding:8px;")
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setStyleSheet("background:#cf222e;color:white;font-weight:bold;padding:8px;")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        root.addLayout(controls)

        save_row = QHBoxLayout()
        self.save_btn = QPushButton("Save graph + data")
        self.save_btn.clicked.connect(lambda: self.save_requested.emit(self.session_meta()))
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        save_row.addWidget(self.save_btn)
        save_row.addWidget(self.clear_btn)
        root.addLayout(save_row)

        # --- Statistics ---
        stats = QGroupBox("Statistics")
        sform = QFormLayout(stats)
        self.lbl_count = QLabel("0")
        self.lbl_last = QLabel("-")
        self.lbl_minmax = QLabel("-")
        self.lbl_bias = QLabel("-")
        self.lbl_elapsed = QLabel("-")
        self.lbl_rate = QLabel("-")
        sform.addRow("Points", self.lbl_count)
        sform.addRow("Last brightness", self.lbl_last)
        sform.addRow("Min / Max", self.lbl_minmax)
        sform.addRow("Current bias", self.lbl_bias)
        sform.addRow("Elapsed", self.lbl_elapsed)
        sform.addRow("Rate", self.lbl_rate)
        root.addWidget(stats)

        root.addStretch(1)

    # ---- helpers ----
    def _dspin(self, lo, hi, val, suffix):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(3)
        s.setValue(val)
        s.setSuffix(suffix)
        return s

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select scan folder",
                                                  self.folder_edit.text() or "")
        if folder:
            self.folder_edit.setText(folder)

    def build_config(self) -> AcquisitionConfig:
        return AcquisitionConfig(
            watch_folder=self.folder_edit.text().strip(),
            roi=ROI(),  # full-frame for now; ROI UI can be added later
            x_axis=self.x_axis.currentText(),
            bias_start=self.bias_start.value(),
            bias_step=self.bias_step.value(),
            settle_seconds=self.settle.value(),
            process_existing=self.process_existing.isChecked(),
        )

    def session_meta(self) -> SessionMeta:
        sample = self.sample.text().strip()
        temp = self.temperature.text().strip()
        desc_parts = [p for p in (sample, f"T={temp}" if temp else "") if p]
        return SessionMeta(
            sample=sample,
            temperature=temp,
            description=", ".join(desc_parts),
            operator=self.operator.text().strip(),
            notes=self.notes.text().strip(),
        )

    def _on_start(self) -> None:
        self.start_requested.emit(self.build_config())

    def _on_stop(self) -> None:
        self.stop_requested.emit()

    def set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        for w in (self.folder_edit, self.x_axis, self.bias_start, self.bias_step,
                  self.settle, self.process_existing):
            w.setEnabled(not running)

    def update_stats(self, stats: dict) -> None:
        def fmt(v, p="{:.2f}"):
            return "-" if v is None else p.format(v)
        self.lbl_count.setText(str(stats.get("count", 0)))
        self.lbl_last.setText(fmt(stats.get("last")))
        mn, mx = stats.get("min"), stats.get("max")
        self.lbl_minmax.setText("-" if mn is None else f"{mn:.2f} / {mx:.2f}")
        cb = stats.get("current_bias")
        self.lbl_bias.setText("-" if cb is None else f"{cb:.3g} V")
        self.lbl_elapsed.setText(f"{stats.get('elapsed_s', 0):.0f} s")
        self.lbl_rate.setText(f"{stats.get('rate_per_min', 0):.1f} /min")
