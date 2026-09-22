"""Write synthetic 'scan' images into a folder so you can test the app now.

Each frame's mean brightness follows a sigmoid vs. frame number (an S-curve,
exactly the integral-of-spectrum shape you expect from a bias sweep), plus a
little noise. Point the app at the same folder, press START, and watch the
graph fill in live.

Usage:
    python tools/simulate_scans.py --folder ./_sim_scans --n 40 --interval 3
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def main() -> None:
    ap = argparse.ArgumentParser(description="Emit fake SEM scan images.")
    ap.add_argument("--folder", default="./_sim_scans", help="output folder")
    ap.add_argument("--n", type=int, default=40, help="number of frames")
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between frames")
    ap.add_argument("--size", type=int, default=256, help="image side in px")
    ap.add_argument("--noise", type=float, default=4.0, help="brightness noise (grey levels)")
    args = ap.parse_args()

    out = Path(args.folder)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Writing {args.n} frames to {out.resolve()} every {args.interval}s")

    rng = np.random.default_rng(0)
    for i in range(args.n):
        # Sweep the sigmoid centre across the run: dark -> bright transition.
        x = (i - args.n / 2) / (args.n / 8)
        level = 40 + 170 * sigmoid(x)
        level += rng.normal(0, args.noise)
        level = float(np.clip(level, 0, 255))
        frame = np.full((args.size, args.size), level, dtype=np.float64)
        frame += rng.normal(0, 6, frame.shape)  # spatial texture
        img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8), mode="L")
        name = out / f"scan_{i:04d}.png"
        img.save(name)
        print(f"  {name.name}  mean~{level:6.1f}")
        if i < args.n - 1:
            time.sleep(args.interval)
    print("Done.")


if __name__ == "__main__":
    main()
