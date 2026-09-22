"""Persist a finished measurement: CSV data, JSON metadata, PNG of the graph."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Sequence

from spectrum_app.config import AcquisitionConfig
from spectrum_app.core.models import DataPoint, SessionMeta


def _slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "measurement"


def save_session(base_dir: str | Path, meta: SessionMeta, points: Sequence[DataPoint],
                 config: AcquisitionConfig | None, plot_png_bytes: bytes | None) -> Path:
    """Write a self-contained folder for one measurement. Returns its path."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(base_dir) / f"{stamp}_{_slug(meta.label())}"
    out.mkdir(parents=True, exist_ok=True)

    # data.csv
    with (out / "data.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["index", "timestamp_iso", "bias_v", "brightness", "source"])
        for p in points:
            w.writerow([
                p.index,
                datetime.fromtimestamp(p.timestamp).isoformat(timespec="milliseconds"),
                "" if p.bias_v is None else f"{p.bias_v:.6g}",
                f"{p.brightness:.6f}",
                p.source,
            ])

    # meta.json
    meta_doc = {
        "meta": asdict(meta),
        "config": asdict(config) if config else None,
        "n_points": len(points),
        "saved": datetime.now().isoformat(timespec="seconds"),
    }
    (out / "meta.json").write_text(json.dumps(meta_doc, indent=2), encoding="utf-8")

    # graph.png
    if plot_png_bytes:
        (out / "graph.png").write_bytes(plot_png_bytes)

    return out
