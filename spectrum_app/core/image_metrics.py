"""Compute a scalar signal (mean brightness) from a scan image file."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from spectrum_app.config import ROI


def wait_until_stable(path: str | Path, checks: int = 3, interval: float = 0.3,
                      timeout: float = 15.0) -> bool:
    """Return True once the file size has stopped changing.

    Guards against reading a scan image while the microscope software is still
    writing it. Returns False on timeout or if the file vanishes.
    """
    path = Path(path)
    deadline = time.time() + timeout
    last = -1
    stable = 0
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last and size > 0:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
            last = size
        time.sleep(interval)
    return False


def mean_brightness(path: str | Path, roi: Optional[ROI] = None) -> float:
    """Mean grey level (0-255) of the image, optionally within an ROI.

    Raises on unreadable files so the caller can log and skip.
    """
    with Image.open(path) as im:
        im = im.convert("L")  # 8-bit greyscale
        arr = np.asarray(im, dtype=np.float64)
    if roi is not None and roi.is_valid():
        y0, y1 = max(0, roi.y), min(arr.shape[0], roi.y + roi.h)
        x0, x1 = max(0, roi.x), min(arr.shape[1], roi.x + roi.w)
        if y1 > y0 and x1 > x0:
            arr = arr[y0:y1, x0:x1]
    return float(arr.mean())
