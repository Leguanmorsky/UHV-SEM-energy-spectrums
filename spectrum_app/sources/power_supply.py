"""Thread-safe wrapper around the Elektro-Automatik PS 2000 (``eaps2k``).

This owns the single serial connection to the power supply and guards **every**
transaction with a lock, because two threads touch it: the GUI thread (Connect,
the live V/I poll) and the acquisition worker thread (the bias sweep).

The physical unit here is an **EA PS 2342-06 B**: a single-quadrant, positive-only
supply (roughly 0-42 V / 0-6 A), so voltage set-points are clamped to
``[0, nominal_voltage]``.

Only thin wrappers over the proven ``eaps2000`` API live here — no re-implementation
of the telegram protocol.
"""
from __future__ import annotations

import threading
from typing import Optional

from eaps2000 import eaps2k
from serial.tools import list_ports


class PowerSupplyError(RuntimeError):
    """Raised for connection / command failures the UI should surface."""


class PowerSupply:
    """Owns the ``eaps2k`` connection; all methods are safe to call cross-thread."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dev: Optional[eaps2k] = None
        self._info: dict = {}
        self._nominal_v: float = 0.0
        self._nominal_i: float = 0.0

    # ---- discovery -------------------------------------------------------
    @staticmethod
    def list_ports() -> list[tuple[str, str]]:
        """Return ``(device, description)`` for every serial port on the system."""
        return [(p.device, p.description or p.device) for p in list_ports.comports()]

    @staticmethod
    def auto_detect() -> Optional[str]:
        """Probe each serial port and return the first that answers as an EA PS 2000.

        ``eaps2k.__init__`` reads the nominal voltage/current, so a port that is not
        a PS 2000 raises or times out; we swallow that and move on.
        """
        for device, _desc in PowerSupply.list_ports():
            dev = None
            try:
                dev = eaps2k(port=device)
                # If construction succeeded these reads already worked, but be sure:
                dev.get_type()
                return device
            except Exception:
                continue
            finally:
                if dev is not None:
                    try:
                        dev.ser_dev.close()
                    except Exception:
                        pass
        return None

    # ---- connection ------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._dev is not None

    @property
    def nominal_voltage(self) -> float:
        return self._nominal_v

    @property
    def nominal_current(self) -> float:
        return self._nominal_i

    def connect(self, port: str) -> dict:
        """Open ``port``, switch the unit to remote, and cache its identity."""
        with self._lock:
            self.disconnect()
            try:
                dev = eaps2k(port=port)
                dev.set_remote(True)
                info = {
                    "port": port,
                    "type": dev.get_type().strip(),
                    "serial": dev.get_serial().strip(),
                    "nominal_v": dev.get_nominal_voltage(),
                    "nominal_i": dev.get_nominal_current(),
                }
            except Exception as exc:  # noqa: BLE001 - re-raise as a friendly error
                raise PowerSupplyError(f"Could not connect on {port}: {exc}") from exc
            self._dev = dev
            self._info = info
            self._nominal_v = info["nominal_v"]
            self._nominal_i = info["nominal_i"]
            return dict(info)

    def disconnect(self) -> None:
        """Turn the output off, hand control back to the front panel, close serial."""
        with self._lock:
            if self._dev is None:
                return
            dev, self._dev = self._dev, None
            for step in (lambda: dev.set_output_state(False),
                         lambda: dev.set_remote(False),
                         lambda: dev.ser_dev.close()):
                try:
                    step()
                except Exception:
                    pass
            self._info = {}

    def info(self) -> dict:
        """Cached identity dict (empty when disconnected)."""
        return dict(self._info)

    # ---- commands --------------------------------------------------------
    def set_voltage(self, volts: float) -> float:
        """Set the output voltage, clamped to ``[0, nominal]``. Returns the value used."""
        clamped = max(0.0, min(float(volts), self._nominal_v)) if self._nominal_v else max(0.0, float(volts))
        with self._lock:
            self._require().set_voltage(clamped)
        return clamped

    def set_current(self, amps: float) -> None:
        with self._lock:
            self._require().set_current(float(amps))

    def set_ovp(self, volts: float) -> None:
        with self._lock:
            self._require().set_ovp(float(volts))

    def set_ocp(self, amps: float) -> None:
        with self._lock:
            self._require().set_ocp(float(amps))

    def ack_alarm(self) -> None:
        with self._lock:
            self._require().ack_alarm()

    def output_on(self, on: bool = True) -> None:
        with self._lock:
            if self._dev is not None:  # tolerate "turn off while disconnected"
                self._dev.set_output_state(bool(on))

    def read_actual(self) -> dict:
        """Live state: ``{'V', 'I', 'on', 'CC', 'CV', 'OVP', ...}`` (see ``get_actual``)."""
        with self._lock:
            return self._require().get_actual()

    # ---- internal --------------------------------------------------------
    def _require(self) -> eaps2k:
        if self._dev is None:
            raise PowerSupplyError("Power supply is not connected.")
        return self._dev
