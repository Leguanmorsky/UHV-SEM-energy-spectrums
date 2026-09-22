"""Application configuration and persisted acquisition settings."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ROI:
    """Region of interest in pixels. If unused, brightness is computed full-frame."""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    def is_valid(self) -> bool:
        return self.w > 0 and self.h > 0


@dataclass
class AcquisitionConfig:
    """Everything needed to run one acquisition sweep.

    The x-axis of the spectrum is the sample BIAS. Until the power supply is
    driven programmatically, each incoming scan is tagged with a bias computed
    from ``bias_start`` + n * ``bias_step`` (you turn the knob in sync, or later
    the power-supply module sets it automatically). ``x_axis`` can instead be
    "index" or "time" while you are still testing.
    """
    watch_folder: str = ""
    file_patterns: tuple[str, ...] = ("*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff", "*.bmp")
    roi: ROI = field(default_factory=ROI)

    # x-axis semantics
    x_axis: str = "bias"          # "bias" | "index" | "time"
    bias_start: float = 0.0        # volts
    bias_step: float = 1.0         # volts per new scan
    settle_seconds: float = 0.0    # ignore this long after a file appears (settling)

    # file handling
    stability_checks: int = 3      # times the file size must be unchanged
    stability_interval: float = 0.3  # seconds between size checks
    process_existing: bool = False   # process files already present when START pressed

    output_dir: str = "sessions"

    def to_json(self, path: str | Path) -> None:
        data = asdict(self)
        data["file_patterns"] = list(self.file_patterns)
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: str | Path) -> "AcquisitionConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        roi = ROI(**data.pop("roi", {}))
        data["file_patterns"] = tuple(data.get("file_patterns", cls().file_patterns))
        return cls(roi=roi, **data)
