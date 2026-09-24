# UHV-SEM Energetic Spectrum

A small desktop app that turns a stream of SEM scan images into a live
**brightness-vs-bias** spectrum, and saves each measurement (graph + data +
description).

## What it does today

- Window with a **live graph** (pyqtgraph) that draws each new point as a scan
  arrives.
- **Left control panel**: connect the power supply, pick the scan folder,
  START / STOP watching, set the bias sweep, safety limits and measurement
  description, and see live statistics (including the supply's actual V/I).
- **Drives the EA PS 2000 power supply** (EA PS 2342-06 B). Connect on `Auto`
  (the app scans serial ports and picks the one that answers) or type a port
  like `COM6`. During a bias sweep the app sets the first voltage, and for each
  new scan it reads the **actual** voltage back, tags the point with it, then
  advances to the next bias — stopping (and turning the output off) at the
  configured end voltage.
- **Output & safety**: current limit, OVP and OCP are pushed to the supply
  before the output goes live; the output turns ON at START (after a
  confirmation prompt), and OFF at STOP, at end-of-sweep, and when you close the
  app. Set voltages are clamped to the supply's nominal range (this unit is
  positive-only, ~0–42 V).
- Watches a folder for **new scan images**, waits until each file is fully
  written, averages its brightness (full frame for now), and plots it.
- Without a supply (or with X-axis `index` / `time`), it behaves as a passive
  viewer: bias is the computed `bias start` + n x `bias step` and no hardware is
  touched.
- **Save** writes a timestamped folder under `sessions/` containing
  `data.csv`, `meta.json` and `graph.png`. Folders are named from your
  description, e.g. `20260920_141530_platinum_t_400/`.

## Install & run (Windows)

Double-click `run.bat` (first run creates a venv and installs dependencies),
or manually:

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m spectrum_app
```

## Try it right now (no microscope needed)

In one terminal, start the fake scanner:

```bat
python tools\simulate_scans.py --folder .\_sim_scans --n 40 --interval 3
```

In the app: set the scan folder to `_sim_scans`, X-axis `bias`, press **START**,
and watch the S-curve build. (The derivative of that curve is your energy
distribution — differentiation will come once real data looks right.)

## Project layout

```
spectrum_app/
  main.py              app entry (python -m spectrum_app)
  config.py            AcquisitionConfig + ROI (JSON load/save)
  core/
    models.py          DataPoint, SessionMeta
    image_metrics.py   mean brightness + wait-until-file-stable
    folder_watcher.py  watchdog watcher -> new_image(path)
    acquisition.py     controller: new scan -> brightness -> point (+bias)
    storage.py         save CSV / JSON / PNG
  sources/
    power_supply.py    thread-safe EA PS 2000 control (eaps2000 wrapper)
  ui/
    main_window.py     assembles + wires everything
    control_panel.py   left panel widgets & signals
    plot_view.py       live pyqtgraph plot
tools/
  simulate_scans.py    synthetic scan generator for testing
sessions/              saved measurements land here
```

## Where the next pieces plug in

- **Power supply (EA PS 2342-06 B)** — DONE. Control lives in
  `spectrum_app/sources/power_supply.py` (a thread-safe wrapper over the
  `eaps2000` package) and is driven from `AcquisitionController` during the bias
  sweep. `test.py` in the repo root is a minimal standalone connection check.
- **UHV-SEM app API** — if the microscope software exposes an API (frame grab
  or the raw detector value), it can replace `FolderWatcher` as the signal
  source by emitting the same "new value" signal. That removes folder-polling
  and image parsing entirely.
- **Detector / DAQ** — same seam: a DAQ source emits values instead of images.

## Known simplifications (v1, on purpose)

- Brightness is full-frame; ROI fields exist in `config.py` but there is no ROI
  picker UI yet.
- One scan == one bias step: the app advances the voltage as soon as a scan
  lands, so take exactly one scan per bias and keep stray files out of the
  watched folder during a sweep.
- Screenshot-style brightness assumes the SEM export has auto-contrast/gamma
  turned OFF and detector gain fixed for the whole sweep.
