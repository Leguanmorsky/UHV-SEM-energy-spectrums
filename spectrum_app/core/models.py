"""Plain data records shared across the app."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DataPoint:
    """One measured point on the spectrum."""
    index: int
    timestamp: float          # epoch seconds
    brightness: float         # mean grey level (0-255)
    bias_v: Optional[float]   # sample bias in volts, if known
    source: str               # file path or source identifier

    def x_value(self, x_axis: str, t0: float) -> float:
        if x_axis == "bias" and self.bias_v is not None:
            return self.bias_v
        if x_axis == "time":
            return self.timestamp - t0
        return float(self.index)


@dataclass
class SessionMeta:
    """Human-facing description saved alongside the data."""
    sample: str = ""              # e.g. "Platinum"
    temperature: str = ""         # e.g. "400" (free text; unit up to you)
    description: str = ""         # e.g. "platinum, T=400"
    operator: str = ""
    notes: str = ""
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def label(self) -> str:
        if self.description.strip():
            return self.description.strip()
        parts = [p for p in (self.sample, f"T={self.temperature}" if self.temperature else "") if p]
        return ", ".join(parts) if parts else "measurement"
