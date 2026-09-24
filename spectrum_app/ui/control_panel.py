"""Left-hand control / management panel."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from spectrum_app.config import ROI, AcquisitionConfig
from spectrum_app.core.models import SessionMeta


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    """Spin box that ignores the mouse wheel, so a stray scroll can't silently
    change a safety-critical value (bias, OVP, current limit). Values still change
    by clicking the arrows, typing, or using the up/down keys."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)  # don't grab focus on hover-scroll

    def wheelEvent(self, event):
        event.ignore()  # let the scroll area handle it instead


class NoScrollComboBox(QComboBox):
    """Combo box that ignores the mouse wheel (same accidental-change guard)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class ControlPanel(QWidget):
    start_requested = Signal(object)      # AcquisitionConfig (fresh graph)
    continue_requested = Signal(object)   # AcquisitionConfig (append to graph)
    stop_requested = Signal()
    save_requested = Signal(object)    # SessionMeta
    clear_requested = Signal()
    connect_requested = Signal(str)    # chosen port ("Auto" or e.g. "COM6")
    disconnect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(340)
        self._connected = False
        root = QVBoxLayout(self)

        # --- Power supply ---
        psu = QGroupBox("Power supply (EA PS 2000)")
        psu_l = QVBoxLayout(psu)
        prow = QHBoxLayout()
        self.port_combo = NoScrollComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setToolTip("Choose 'Auto' to scan, or type a port like COM6")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(28)
        self.refresh_btn.setToolTip("Rescan serial ports")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        prow.addWidget(self.port_combo, 1)
        prow.addWidget(self.refresh_btn)
        prow.addWidget(self.connect_btn)
        psu_l.addLayout(prow)
        self.psu_status = QLabel("● Disconnected")
        self.psu_status.setStyleSheet("color:#cf222e;")
        psu_l.addWidget(self.psu_status)
        self.drive_supply = QCheckBox("Drive the supply during a bias sweep")
        self.drive_supply.setChecked(True)
        psu_l.addWidget(self.drive_supply)
        root.addWidget(psu)

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
        bias = QGroupBox("X-axis / bias sweep")
        form = QFormLayout(bias)
        self.x_axis = NoScrollComboBox()
        self.x_axis.addItems(["bias", "index", "time"])
        self.bias_start = self._dspin(-1000, 1000, 0.0, " V")
        self.bias_step = self._dspin(-1000, 1000, 1.0, " V")
        self.bias_stop_enable = QCheckBox("Stop at")
        self.bias_stop = self._dspin(-1000, 1000, 10.0, " V")
        stop_row = QHBoxLayout()
        stop_row.addWidget(self.bias_stop_enable)
        stop_row.addWidget(self.bias_stop)
        self.settle = self._dspin(0, 60, 0.0, " s")
        form.addRow("X axis", self.x_axis)
        form.addRow("Bias start", self.bias_start)
        form.addRow("Bias step / scan", self.bias_step)
        form.addRow("End of sweep", stop_row)
        form.addRow("Settle after set bias", self.settle)
        self.test_mode = QCheckBox("Test mode — no folder, step bias on a timer")
        self.test_mode.toggled.connect(self._on_test_toggled)
        self.test_interval = self._dspin(0.05, 3600, 2.0, " s")
        form.addRow(self.test_mode)
        form.addRow("Time step (test)", self.test_interval)
        hint = QLabel("Negative bias = leads swapped. Sweep one polarity, then swap "
                      "the leads and press CONTINUE for the other half on one graph.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#57606a;font-size:11px;")
        form.addRow(hint)
        root.addWidget(bias)

        # --- Output & safety ---
        safety = QGroupBox("Output & safety limits")
        sfm = QFormLayout(safety)
        self.current_limit = self._dspin(0, 100, 0.1, " A")
        self.ovp = self._dspin(0, 1000, 0.0, " V")
        self.ocp = self._dspin(0, 100, 0.0, " A")
        sfm.addRow("Current limit", self.current_limit)
        sfm.addRow("OVP (0 = off)", self.ovp)
        sfm.addRow("OCP (0 = off)", self.ocp)
        root.addWidget(safety)

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

        self.continue_btn = QPushButton("CONTINUE on current graph")
        self.continue_btn.setToolTip(
            "Run another sweep segment, appending to the current graph "
            "(e.g. the negative half after swapping the output leads).")
        self.continue_btn.setStyleSheet("background:#0969da;color:white;padding:6px;")
        self.continue_btn.clicked.connect(self._on_continue)
        root.addWidget(self.continue_btn)

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
        self.lbl_actual = QLabel("-")
        self.lbl_output = QLabel("-")
        self.lbl_elapsed = QLabel("-")
        self.lbl_rate = QLabel("-")
        sform.addRow("Points", self.lbl_count)
        sform.addRow("Last brightness", self.lbl_last)
        sform.addRow("Min / Max", self.lbl_minmax)
        sform.addRow("Current bias", self.lbl_bias)
        sform.addRow("Actual V / I", self.lbl_actual)
        sform.addRow("Output", self.lbl_output)
        sform.addRow("Elapsed", self.lbl_elapsed)
        sform.addRow("Rate", self.lbl_rate)
        root.addWidget(stats)

        root.addStretch(1)

    # ---- helpers ----
    def _dspin(self, lo, hi, val, suffix):
        s = NoScrollDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(3)
        s.setValue(val)
        s.setSuffix(suffix)
        return s

    def _on_test_toggled(self, on: bool) -> None:
        # In test mode the scan folder is irrelevant, so grey it out.
        self.folder_edit.setEnabled(not on)
        self.process_existing.setEnabled(not on)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select scan folder",
                                                  self.folder_edit.text() or "")
        if folder:
            self.folder_edit.setText(folder)

    def refresh_ports(self) -> None:
        """Populate the port combo with 'Auto' + detected serial ports."""
        from spectrum_app.sources.power_supply import PowerSupply
        current = self.port_combo.currentText()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        self.port_combo.addItem("Auto")
        for device, desc in PowerSupply.list_ports():
            self.port_combo.addItem(f"{device} — {desc}", device)
        self.port_combo.blockSignals(False)
        if current:
            self.port_combo.setCurrentText(current)

    def selected_port(self) -> str:
        """Resolve the chosen port to 'Auto' or a bare device name like 'COM6'."""
        data = self.port_combo.currentData()
        if data:
            return str(data)
        return self.port_combo.currentText().strip() or "Auto"

    def _on_connect_clicked(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
        else:
            self.connect_requested.emit(self.selected_port())

    def set_connecting(self, connecting: bool) -> None:
        """Show an in-progress connection and block the button until it resolves."""
        self.connect_btn.setEnabled(not connecting)
        self.port_combo.setEnabled(not connecting)
        self.refresh_btn.setEnabled(not connecting)
        if connecting:
            self.psu_status.setText("● Connecting…")
            self.psu_status.setStyleSheet("color:#9a6700;")

    def set_connected(self, connected: bool, info: str = "") -> None:
        self._connected = connected
        if connected:
            self.psu_status.setText(f"● {info}" if info else "● Connected")
            self.psu_status.setStyleSheet("color:#1a7f37;")
            self.connect_btn.setText("Disconnect")
        else:
            self.psu_status.setText(f"● {info}" if info else "● Disconnected")
            self.psu_status.setStyleSheet("color:#cf222e;")
            self.connect_btn.setText("Connect")

    def build_config(self) -> AcquisitionConfig:
        return AcquisitionConfig(
            watch_folder=self.folder_edit.text().strip(),
            roi=ROI(),  # full-frame for now; ROI UI can be added later
            x_axis=self.x_axis.currentText(),
            bias_start=self.bias_start.value(),
            bias_step=self.bias_step.value(),
            bias_stop=self.bias_stop.value() if self.bias_stop_enable.isChecked() else None,
            settle_seconds=self.settle.value(),
            process_existing=self.process_existing.isChecked(),
            com_port=self.selected_port(),
            drive_supply=self.drive_supply.isChecked(),
            current_limit=self.current_limit.value(),
            ovp=self.ovp.value(),
            ocp=self.ocp.value(),
            test_mode=self.test_mode.isChecked(),
            test_interval=self.test_interval.value(),
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

    def _on_continue(self) -> None:
        self.continue_requested.emit(self.build_config())

    def _on_stop(self) -> None:
        self.stop_requested.emit()

    def set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.continue_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        for w in (self.folder_edit, self.x_axis, self.bias_start, self.bias_step,
                  self.bias_stop, self.bias_stop_enable, self.settle,
                  self.process_existing, self.drive_supply, self.current_limit,
                  self.ovp, self.ocp, self.port_combo, self.connect_btn,
                  self.refresh_btn, self.test_mode, self.test_interval):
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

    def update_actual(self, actual: dict | None) -> None:
        """Live power-supply readout (or clear it when disconnected)."""
        if not actual:
            self.lbl_actual.setText("-")
            self.lbl_output.setText("-")
            return
        self.lbl_actual.setText(f"{actual.get('V', 0):.3g} V / {actual.get('I', 0):.3g} A")
        on = actual.get("on", False)
        mode = "CC" if actual.get("CC") else "CV"
        self.lbl_output.setText(f"{'ON' if on else 'OFF'} ({mode})" if on else "OFF")
        self.lbl_output.setStyleSheet("color:#cf222e;font-weight:bold;" if on else "")
