# UHV-SEM Energetic Spectrum

A small desktop app that turns a stream of SEM scan images into a live
**brightness-vs-bias** spectrum, and saves each measurement (graph + data +
description).

## What it does today

- Window with a **live graph** (pyqtgraph) that draws each new point as a scan
  arrives.
- **Left control panel**: pick the scan folder, START / STOP watching, set the
  bias schedule and measurement description, see live statistics.
- Watches a folder for **new scan images**, waits until each file is fully
  written, averages its brightness (full frame for now), and plots it.
- Each incoming scan is tagged with a **bias** computed from `bias start` +
  n x `bias step` (X-axis can also be `index` or `time` while testing).
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
  ui/
    main_window.py     assembles + wires everything
    control_panel.py   left panel widgets & signals
    plot_view.py       live pyqtgraph plot
tools/
  simulate_scans.py    synthetic scan generator for testing
sessions/              saved measurements land here
```

## Where the next pieces plug in

- **Power supply (EA PS 2342-06 B)** — the USB port is a real remote-control
  interface (virtual COM port, EA telegram protocol). Control belongs in
  `AcquisitionController._apply_bias()`: instead of only computing the bias,
  it will call `power_supply.set_voltage(v)` before/while the next scan is
  taken. A standalone `sources/power_supply.py` + a `tools/test_power_supply.py`
  will be added once the unit is on the bench.
- **UHV-SEM app API** — if the microscope software exposes an API (frame grab
  or the raw detector value), it can replace `FolderWatcher` as the signal
  source by emitting the same "new value" signal. That removes folder-polling
  and image parsing entirely.
- **Detector / DAQ** — same seam: a DAQ source emits values instead of images.

## Known simplifications (v1, on purpose)

- Brightness is full-frame; ROI fields exist in `config.py` but there is no ROI
  picker UI yet.
- Bias is scheduled, not yet commanded (no hardware control).
- Screenshot-style brightness assumes the SEM export has auto-contrast/gamma
  turned OFF and detector gain fixed for the whole sweep.
