# Earthquake Timelapse Visualization · 1990–2023

A single Python script that turns 34 years of global seismic data into two publication-ready outputs: an **interactive HTML map** you can explore in any browser, and an **MP4 + GIF** for sharing anywhere.

Data is pulled directly from the **USGS ComCat API** — no credentials, no manual download steps.

## Demo

![Earthquake timelapse 1990–2023](./assets/demo.gif)

---

## Why I built this

The raw numbers behind earthquakes are staggering — roughly 13,000 M≥4.0 events per year, each one a data point with magnitude, depth, coordinates, and timestamp. But a spreadsheet of 3.4 million rows tells you nothing visceral about where the Earth is breaking and why.

The challenge I set myself: encode **four data dimensions simultaneously** (location, magnitude, depth, time), render 408 monthly frames efficiently enough to fit in a self-contained HTML file, and make the Ring of Fire immediately legible to someone who has never heard the term. No dashboarding framework, no Jupyter notebook — just a clean Python script you can run end-to-end in one command.

---

## What it produces

| Output | Description |
|---|---|
| `earthquake_viz.html` | Self-contained interactive Plotly map. Play/pause, time scrubber, hover tooltips. ~15–25 MB. |
| `earthquake_viz.mp4` | 12 fps animated video, Robinson projection, dark basemap. |
| `earthquake_viz.gif` | 8 fps GIF at every 2nd frame. |

---

## Visual design

Every frame covers one calendar month from January 1990 to December 2023 (408 frames total). Four data dimensions are encoded simultaneously:

| Dimension | Visual channel |
|---|---|
| **Magnitude** | Circle size — exponential: M4 = dot, M6 = medium, M8+ = large |
| **Magnitude** | Color — blue → green → yellow → orange → red → white |
| **Depth** | Opacity — shallow (<70 km) fully opaque; deep (>300 km) at 30% |
| **Time** | Animation frame — monthly steps |

Additional effects layered on top:

- **Fade trail** — the current month renders at full brightness; the prior 3 months ghost out at 40% / 18% / 8% opacity, creating a comet-tail cluster effect around active zones.
- **M7+ flash** — major earthquakes get a gold outer ring/halo so they visually pop from the surrounding noise.
- **Tectonic plate lines** — 54 plate boundaries (Peter Bird 2002) overlaid as dim grey lines. The Ring of Fire becomes immediately visible as earthquakes snap to plate edges.
- **Live stats panel** — each frame updates: cumulative event count, largest quake recorded so far, and total seismic energy released (in megatons of TNT, using E = 10^(1.5M + 4.8) J).

---

## Interactive controls (HTML mode)

### Playback
| Control | What it does |
|---|---|
| **▶ / ⏸ button** | Play or pause the animation |
| **Timeline scrubber** | Drag to jump to any month |
| **Speed slider** | Set playback rate in fps (default 8 fps) |

### Magnitude floor (`M4+` / `M5+` / `M6+`)
Filters out earthquakes below the selected threshold. Raising the floor declutters the map to highlight only the strongest events. Affects both the current frame and the trail/cumulative background.

### Cumulative mode
- **Off (default):** Shows a **rolling 3-month trail** — the previous three months fade out at decreasing opacity (40% → 18% → 8%), giving a comet-tail effect around active zones without overwhelming the display.
- **On:** Shows **every earthquake from the beginning of the dataset up to the current frame**, accumulating over time. Older events fade toward a low-opacity floor so recent activity still stands out. Lets you watch seismic patterns build up across decades — the Ring of Fire emerges clearly within the first few years.

### Energy burst mode
Changes the dot size formula to use a steeper exponent, making the size difference between magnitudes far more dramatic:

| | M5 | M6 | M7 | M8 |
|---|---|---|---|---|
| **Normal** | 8 px | 16 px | 32 px | 60 px |
| **Energy burst** | 5 px | 16 px | 50 px | 90 px |

This reflects the true energy gap — an M8 releases roughly 1,000× more energy than an M6 — which the default linear-looking sizes understate.

### Projection
Switches the map projection via a dropdown. Default is **Natural Earth**. Options include Mercator, orthographic, and others provided by Plotly.

---

## Quick start

### 1. Install dependencies

```bash
pip install pandas plotly numpy matplotlib cartopy geopandas imageio moviepy kaleido kaggle
```

> **Windows / conda note:** Cartopy can be tricky to build from source. If `pip install cartopy` fails, use:
> ```bash
> conda install -c conda-forge cartopy
> ```

### 2. Fetch the earthquake data

The USGS ComCat API is free and requires no account. The script fetches 34 years of M≥4.0 data in year-sized chunks (~400–500 k events total):

```bash
python earthquake_viz.py --fetch-usgs
```

This takes 5–10 minutes on a typical connection and saves `data/earthquakes.csv` (~15–20 MB).

> **Alternative — Kaggle dataset:** If you have a Kaggle account and prefer the pre-bundled 3 M-row dataset (includes historical catalogs beyond USGS):
> ```bash
> # Place your kaggle.json in ~/.kaggle/ first
> python earthquake_viz.py --download
> ```
> Or download manually and save as `data/earthquakes.csv`.

### 3. Generate outputs

```bash
# Interactive HTML only (fastest — ~2–5 min)
python earthquake_viz.py --html-only

# Video + GIF only
python earthquake_viz.py --video-only

# Quick video preview (quarterly frames, lower resolution)
python earthquake_viz.py --video-only --fast

# Everything
python earthquake_viz.py
```

Open `earthquake_viz.html` in any browser. No server needed — it's fully self-contained.

---

## CLI reference

```
python earthquake_viz.py [options]

Options:
  --fetch-usgs    Download data from USGS ComCat API (free, no login), then run
  --download      Download dataset via Kaggle API, then run
  --html-only     Generate interactive HTML only; skip video/GIF
  --video-only    Generate MP4 + GIF only; skip HTML
  --fast          Quarterly frames at lower resolution — fast preview of the video
  -h, --help      Show this message and exit
```

---

## How it works

### Pipeline overview

```
USGS ComCat API                     tectonic_plates.geojson
(chunked by year)                   (Peter Bird 2002, public domain)
       │                                        │
       ▼                                        ▼
 data/earthquakes.csv            54 polygon rings → (lons, lats) segments
       │                                        │
       └──────────────┬─────────────────────────┘
                      ▼
              load_data() + load_plates()
              • flexible column detection
              • M≥4.0 filter, lat/lon bounds check
              • derived: size_px, opacity_dep, hex_color, energy_J
              • group by year_month → 408 periods
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
  build_plotly_html()        render_video()
  Plotly Scattergeo          Matplotlib + Cartopy
  • 7 fixed trace slots      • Robinson projection
  • frames update slots 1–6  • frame-by-frame PNG render
  • plate trace is static    • plate + trail + halos per frame
  • Play/Pause + scrubber     • imageio → MP4 (libx264) + GIF
          │                       │
          ▼                       ▼
  earthquake_viz.html    earthquake_viz.mp4
                         earthquake_viz.gif
```

### Plotly animation design

The HTML animation uses **7 fixed Scattergeo trace slots** so the plate boundary trace (slot 0) is written once and never repeated across frames. Only slots 1–6 are swapped per frame — this keeps file size manageable even at 408 frames.

```
Slot 0  │ Plate boundaries        — static, written once
Slot 1  │ Trail: month − 3        — 8% opacity
Slot 2  │ Trail: month − 2        — 18% opacity
Slot 3  │ Trail: month − 1        — 40% opacity
Slot 4  │ Current month, M < 7    — full opacity, depth-modulated
Slot 5  │ Current month, M ≥ 7 halos  — gold ring
Slot 6  │ Current month, M ≥ 7 cores  — full opacity
```

### Magnitude → size scaling

Size grows exponentially so the difference between a M5 and a M7 is viscerally obvious:

```
M4  →   4 px   (reference dot)
M5  →   8 px
M6  →  16 px
M7  →  32 px
M8+ →  60 px   (capped)
```

Formula: `size = 2^(magnitude − 3)`, clipped to [3, 60].

### Depth → opacity

```
0 km   →  1.00  (fully opaque — crustal / shallow events)
70 km  →  0.84  (upper mantle)
150 km →  0.65
300 km →  0.30  (capped minimum — deep slab events ghosted out)
```

### Color scale

```
M4.0  ──  #1a78c2  (steel blue)
M5.6  ──  #39b54a  (green)
M6.5  ──  #f5a623  (amber)
M7.3  ──  #e8272b  (red)
M9.0  ──  #ffffff  (white)
```

### Energy calculation

Cumulative energy is tracked per frame using the Gutenberg–Richter energy–magnitude relation:

```
E = 10^(1.5 × M + 4.8)  joules
  → converted to megatons TNT  (1 Mt = 4.184 × 10¹⁵ J)
```

---

## File structure

```
earthquakes_dataviz/
├── earthquake_viz.py            Main script
├── README.md
├── data/
│   ├── earthquakes.csv          Earthquake catalog (generated by --fetch-usgs)
│   └── tectonic_plates.geojson  Plate boundaries (included — public domain)
├── assets/
│   └── demo.gif                 Preview GIF for README
├── earthquake_viz.html          OUTPUT: interactive map
├── earthquake_viz.mp4           OUTPUT: video
└── earthquake_viz.gif           OUTPUT: animated GIF
```

---

## Dependencies

| Library | Role |
|---|---|
| `pandas` | Load, clean, filter, aggregate the CSV |
| `numpy` | Array maths (magnitude scaling, color interpolation) |
| `plotly` | Interactive HTML animation via `Scattergeo` |
| `matplotlib` | Frame-by-frame rendering for the video |
| `cartopy` | Robinson map projection, coastlines, Natural Earth features |
| `imageio` | Stitch PNG frames → MP4 (libx264) and GIF |
| `moviepy` | MP4 encoding fallback and video finalization |
| `kaggle` | Optional — Kaggle API download path only |

All data fetched via Python's standard `urllib` — no extra HTTP library needed.

---

## Data sources

- **Earthquake catalog** — [USGS Earthquake Hazards Program ComCat API](https://earthquake.usgs.gov/fdsnws/event/1/) — public domain, no license restrictions.
- **Alternative catalog** — [Kaggle: The Ultimate Earthquake Dataset 1990–2023](https://www.kaggle.com/datasets/alessandrolobello/the-ultimate-earthquake-dataset-from-1990-2023) — community dataset, same underlying USGS data.
- **Tectonic plate boundaries** — Peter Bird (2002), *An updated digital model of plate boundaries*, Geochemistry Geophysics Geosystems. Public domain GeoJSON via [fraxen/tectonicplates](https://github.com/fraxen/tectonicplates).
