#!/usr/bin/env python3
"""Earthquake Timelapse Visualization (1990-2023)

Outputs:
  earthquake_viz.html  — interactive Plotly map (portfolio-ready)
  earthquake_viz.mp4   — animated video  (12 fps, Robinson projection)
  earthquake_viz.gif   — animated GIF    (8 fps, every 2nd frame)

Usage:
  python earthquake_viz.py               # generate all outputs
  python earthquake_viz.py --html-only   # skip video/GIF
  python earthquake_viz.py --video-only  # skip HTML
  python earthquake_viz.py --fast        # quick preview (quarterly frames, lower res)
  python earthquake_viz.py --fetch-usgs  # fetch data from USGS API (no login needed)
  python earthquake_viz.py --download    # download dataset via Kaggle API then run
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

warnings.filterwarnings("ignore")

# ── Paths ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
CSV_PATH = DATA_DIR / "earthquakes.csv"
PLATES_PATH = DATA_DIR / "tectonic_plates.geojson"

# ── Visual constants ────────────────────────────────────────────────────────
BG_COLOR    = "#0a0a0f"
LAND_COLOR  = "#12121e"
OCEAN_COLOR = "#0a0a0f"
COAST_COLOR = "#2a2a3a"
PLATE_COLOR = "#3a3a5a"

CUSTOM_COLORSCALE = [
    [0.00, "#1a78c2"],
    [0.40, "#39b54a"],
    [0.65, "#f5a623"],
    [0.85, "#e8272b"],
    [1.00, "#ffffff"],
]

MAG_MIN        = 4.0
TRAIL_MONTHS   = 3
# Opacity for each trail slot: [oldest … current]
TRAIL_OPACITIES = [0.08, 0.18, 0.40, 1.00]


# ══════════════════════════════════════════════════════════════════════════
# 1. Data loading & cleaning
# ══════════════════════════════════════════════════════════════════════════

def fetch_usgs() -> None:
    """Download M≥4.0 earthquakes 1990-2023 from the free USGS ComCat API.

    The API caps results at 20 000 per request, so we chunk by year.
    Total download: ~150-200 k events, a few MB of CSV.
    No account or API key required.
    """
    import urllib.request
    import io

    BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    YEARS    = range(1990, 2024)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.exists():
        print(f"  {CSV_PATH} already exists — delete it first to re-fetch.")
        return

    print("Fetching earthquake data from USGS ComCat API …")
    print("  (chunked by year, M≥4.0, 1990-2023 — no login required)")

    all_frames = []
    for year in YEARS:
        url = (
            f"{BASE_URL}?format=csv"
            f"&starttime={year}-01-01"
            f"&endtime={year}-12-31"
            f"&minmagnitude={MAG_MIN}"
            f"&orderby=time-asc"
            f"&limit=20000"
        )
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
            year_df = pd.read_csv(io.StringIO(raw))
            all_frames.append(year_df)
            print(f"  {year}: {len(year_df):,} events")
        except Exception as e:
            print(f"  {year}: FAILED ({e}) — skipping")

    if not all_frames:
        print("ERROR: No data retrieved from USGS. Check your internet connection.")
        sys.exit(1)

    combined = pd.concat(all_frames, ignore_index=True)
    combined.to_csv(CSV_PATH, index=False)
    print(f"\n  Saved {len(combined):,} events → {CSV_PATH}  "
          f"({CSV_PATH.stat().st_size / 1e6:.1f} MB)")


def download_dataset() -> None:
    """Download the Kaggle dataset. Requires ~/.kaggle/kaggle.json credentials."""
    DATASET = "alessandrolobello/the-ultimate-earthquake-dataset-from-1990-2023"
    creds_path = Path.home() / ".kaggle" / "kaggle.json"
    if not creds_path.exists():
        print(f"""
Kaggle API credentials not found at: {creds_path}

To set up:
  1. Go to https://www.kaggle.com/settings  →  "API"  →  "Create New Token"
  2. Save the downloaded kaggle.json to:  {creds_path}
  3. Run:  python earthquake_viz.py --download

Alternatively, download manually:
  https://www.kaggle.com/datasets/alessandrolobello/the-ultimate-earthquake-dataset-from-1990-2023
  → Save the CSV as: {CSV_PATH}
""")
        sys.exit(1)

    try:
        import kaggle  # noqa: F401 — triggers credential check
        from kaggle.api.kaggle_api_extended import KaggleApiExtended
        api = KaggleApiExtended()
        api.authenticate()
    except Exception as e:
        print(f"Kaggle API error: {e}\nInstall with: pip install kaggle")
        sys.exit(1)

    print(f"Downloading dataset: {DATASET} …")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    api.dataset_download_files(DATASET, path=str(DATA_DIR), unzip=True)
    # Rename if needed — dataset may extract with a different filename
    csvs = list(DATA_DIR.glob("*.csv"))
    if csvs and not CSV_PATH.exists():
        csvs[0].rename(CSV_PATH)
        print(f"  Renamed {csvs[0].name} → earthquakes.csv")
    if CSV_PATH.exists():
        print(f"  Dataset ready: {CSV_PATH}  ({CSV_PATH.stat().st_size / 1e6:.0f} MB)")
    else:
        print(f"  WARNING: Could not find a CSV at {CSV_PATH} after download.")
        print(f"  Files in data/: {[f.name for f in DATA_DIR.iterdir()]}")


def load_data() -> pd.DataFrame:
    if not CSV_PATH.exists():
        print(f"""
ERROR: Dataset not found at:
  {CSV_PATH}

Option 1 — Kaggle API (automatic):
  pip install kaggle
  # place kaggle.json in ~/.kaggle/  (from kaggle.com/settings → API)
  python earthquake_viz.py --download

Option 2 — Manual download:
  https://www.kaggle.com/datasets/alessandrolobello/the-ultimate-earthquake-dataset-from-1990-2023
  Save the CSV as: {CSV_PATH}
""")
        sys.exit(1)

    print("Loading earthquake data …")
    df = pd.read_csv(CSV_PATH, low_memory=False)
    print(f"  Raw rows: {len(df):,}  |  columns: {list(df.columns)[:8]} …")

    # ── Flexible column detection ──────────────────────────────────────────
    def find_col(df, *keywords) -> str | None:
        for kw in keywords:
            for c in df.columns:
                if kw in c.lower():
                    return c
        return None

    dt_col    = find_col(df, "date_time", "date", "time", "occurred")
    lat_col   = find_col(df, "latitude", "lat")
    lon_col   = find_col(df, "longitude", "lon")
    mag_col   = find_col(df, "magnitude", "mag")
    depth_col = find_col(df, "depth")
    place_col = find_col(df, "place", "locat", "region", "area")

    if not all([dt_col, lat_col, lon_col, mag_col]):
        missing = [n for n, c in [("date/time", dt_col), ("latitude", lat_col),
                                   ("longitude", lon_col), ("magnitude", mag_col)] if not c]
        print(f"ERROR: Could not find columns for: {missing}")
        print(f"  Available columns: {list(df.columns)}")
        sys.exit(1)

    rename = {dt_col: "datetime", lat_col: "latitude",
              lon_col: "longitude", mag_col: "magnitude"}
    if depth_col:
        rename[depth_col] = "depth"
    if place_col:
        rename[place_col] = "place"
    df = df.rename(columns=rename)

    # ── Parse & clean ──────────────────────────────────────────────────────
    df["datetime"]  = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
    df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["magnitude"] = pd.to_numeric(df["magnitude"], errors="coerce")
    if "depth" not in df.columns:
        df["depth"] = 50.0
    else:
        df["depth"] = pd.to_numeric(df["depth"], errors="coerce").fillna(50.0)
    if "place" not in df.columns:
        df["place"] = ""
    else:
        df["place"] = df["place"].fillna("").astype(str)

    df = df.dropna(subset=["datetime", "latitude", "longitude", "magnitude"])
    df = df[df["magnitude"] >= MAG_MIN]
    df = df[df["latitude"].between(-90, 90) & df["longitude"].between(-180, 180)]
    print(f"  After M≥{MAG_MIN} filter: {len(df):,} rows")

    # ── Derived columns ────────────────────────────────────────────────────
    df["year_month"]  = df["datetime"].dt.to_period("M")
    df["size_px"]     = _mag_to_size(df["magnitude"])
    df["opacity_dep"] = _depth_to_opacity(df["depth"])
    df["color_val"]   = ((df["magnitude"] - MAG_MIN) / (9.0 - MAG_MIN)).clip(0, 1)
    df["hex_color"]   = df["color_val"].apply(_val_to_hex)
    # Energy in Joules: E = 10^(1.5M + 4.8)
    df["energy_J"]    = 10.0 ** (1.5 * df["magnitude"] + 4.8)

    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def _mag_to_size(mag: pd.Series) -> pd.Series:
    """Exponential: M4≈4 px, M6≈16 px, M8+≈60 px."""
    return (2.0 ** (mag - 3.0)).clip(3, 60)


def _depth_to_opacity(depth: pd.Series) -> pd.Series:
    """Shallow (<70 km) → 1.0 opacity; deep (>300 km) → 0.30."""
    return (1.0 - depth.clip(0, 300) / 300.0 * 0.70).clip(0.30, 1.0)


def _val_to_hex(t: float) -> str:
    """Map 0–1 value through CUSTOM_COLORSCALE → hex string."""
    t = max(0.0, min(1.0, t))
    for i in range(len(CUSTOM_COLORSCALE) - 1):
        lo_t, lo_c = CUSTOM_COLORSCALE[i]
        hi_t, hi_c = CUSTOM_COLORSCALE[i + 1]
        if t <= hi_t:
            f = (t - lo_t) / (hi_t - lo_t) if hi_t > lo_t else 0.0
            return _lerp_hex(lo_c, hi_c, f)
    return CUSTOM_COLORSCALE[-1][1]


def _lerp_hex(c1: str, c2: str, t: float) -> str:
    def h2r(h):
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r1, g1, b1 = h2r(c1)
    r2, g2, b2 = h2r(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.3f})"


# ══════════════════════════════════════════════════════════════════════════
# 2. Tectonic plates
# ══════════════════════════════════════════════════════════════════════════

def load_plates() -> list[tuple[list, list]]:
    """Return list of (lons, lats) ring segments from the plates GeoJSON."""
    if not PLATES_PATH.exists():
        print("  Warning: tectonic_plates.geojson not found — plate overlay skipped.")
        return []
    print("Loading tectonic plate boundaries …")
    with open(PLATES_PATH) as f:
        geojson = json.load(f)

    segments: list[tuple[list, list]] = []

    def _add_ring(ring):
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        segments.append((lons, lats))

    for feature in geojson["features"]:
        geom = feature["geometry"]
        gtype = geom["type"]
        coords = geom["coordinates"]
        if gtype == "Polygon":
            for ring in coords:
                _add_ring(ring)
        elif gtype == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    _add_ring(ring)
        elif gtype == "LineString":
            _add_ring(coords)
        elif gtype == "MultiLineString":
            for line in coords:
                _add_ring(line)

    print(f"  {len(segments)} plate boundary segments")
    return segments


def _plates_to_geo_trace(segments: list) -> go.Scattergeo:
    """Flatten all segments into one Scattergeo line trace (None separators)."""
    all_lons, all_lats = [], []
    for lons, lats in segments:
        all_lons.extend(lons)
        all_lons.append(None)
        all_lats.extend(lats)
        all_lats.append(None)
    return go.Scattergeo(
        lon=all_lons,
        lat=all_lats,
        mode="lines",
        line=dict(color=PLATE_COLOR, width=0.8),
        hoverinfo="skip",
        showlegend=False,
        name="Plate Boundaries",
    )


# ══════════════════════════════════════════════════════════════════════════
# 3. Cumulative stats helper
# ══════════════════════════════════════════════════════════════════════════

def build_cumulative_stats(df: pd.DataFrame, periods) -> dict:
    """Pre-compute per-period cumulative count, energy, and largest event."""
    stats = {}
    cum_count = 0
    cum_energy = 0.0
    max_mag = 0.0
    max_label = "—"

    for period in periods:
        sub = df[df["year_month"] == period]
        cum_count += len(sub)
        cum_energy += sub["energy_J"].sum()
        if not sub.empty:
            idx = sub["magnitude"].idxmax()
            row = sub.loc[idx]
            if row["magnitude"] > max_mag:
                max_mag = row["magnitude"]
                place = str(row["place"])[:35] if row["place"] else ""
                max_label = f"M{max_mag:.1f} — {place or str(period)[:7]}"
        stats[period] = {
            "count": cum_count,
            "energy_mt": cum_energy / 4.184e15,  # Megatons TNT
            "max_mag": max_mag,
            "max_label": max_label,
        }
    return stats


# ══════════════════════════════════════════════════════════════════════════
# 4. Interactive HTML (Plotly)
# ══════════════════════════════════════════════════════════════════════════

def build_plotly_html(df: pd.DataFrame, plate_segments: list) -> str:  # noqa: C901
    """Build a fully interactive single-file HTML visualization.

    Architecture: static Plotly figure (5 traces) + custom JavaScript animation
    loop.  All five interactive controls (speed, magnitude floor, projection,
    cumulative mode, energy-burst mode) are driven by JS that calls
    Plotly.restyle / Plotly.relayout each frame — no pre-baked frames needed,
    which keeps the file small regardless of mode combinations.
    """
    import json as _json

    print("\nBuilding interactive Plotly HTML …")
    periods = sorted(df["year_month"].unique())
    n = len(periods)
    print(f"  {n} monthly frames")

    cum_stats = build_cumulative_stats(df, periods)
    periods_str = [str(p)[:7] for p in periods]

    # ── Static Plotly figure — map background + 4 updatable traces ─────────
    # Trace 0: plate boundaries (never touched by JS)
    # Trace 1: trail events          (JS updates each frame)
    # Trace 2: current-month events  (JS updates each frame, has hover)
    # Trace 3: M7+ halos             (JS updates each frame)
    # Trace 4: M7+ cores             (JS updates each frame, has hover)
    plate_trace = _plates_to_geo_trace(plate_segments)

    def _eg(name=""):
        return go.Scattergeo(lon=[], lat=[], mode="markers",
                             marker=dict(size=[], color=[], line=dict(width=0)),
                             hoverinfo="skip", showlegend=False, name=name)

    fig = go.Figure(
        data=[
            plate_trace,
            _eg("trail"),
            go.Scattergeo(lon=[], lat=[], mode="markers",
                          marker=dict(size=[], color=[], line=dict(width=0)),
                          hoverinfo="text", text=[], showlegend=False, name="current"),
            go.Scattergeo(lon=[], lat=[], mode="markers",
                          marker=dict(size=[], color="rgba(0,0,0,0)",
                                      line=dict(color="rgba(255,200,50,0.75)", width=2)),
                          hoverinfo="skip", showlegend=False, name="halos"),
            go.Scattergeo(lon=[], lat=[], mode="markers",
                          marker=dict(size=[], color=[], line=dict(width=0)),
                          hoverinfo="text", text=[], showlegend=False, name="M7+"),
        ],
        layout=go.Layout(
            paper_bgcolor=BG_COLOR,
            plot_bgcolor=BG_COLOR,
            geo=dict(
                projection_type="natural earth",
                projection_scale=0.9,
                showocean=True,      oceancolor=OCEAN_COLOR,
                showland=True,       landcolor=LAND_COLOR,
                showcoastlines=True, coastlinecolor=COAST_COLOR, coastlinewidth=0.5,
                showcountries=False, showframe=False,
                bgcolor=BG_COLOR,
                lataxis=dict(range=[-75, 80]),
                lonaxis=dict(range=[-180, 180]),
            ),
            margin=dict(l=0, r=0, t=0, b=0),
            annotations=[
            ],
        ),
    )

    # ── Serialize monthly data compactly for JS ────────────────────────────
    print("  Serializing monthly data …")
    monthly_js: dict = {}
    for period in periods:
        sub = df[df["year_month"] == period]
        s   = cum_stats[period]
        monthly_js[str(period)[:7]] = {
            "a": sub["latitude"].round(3).tolist(),
            "o": sub["longitude"].round(3).tolist(),
            "m": sub["magnitude"].round(2).tolist(),
            "d": sub["depth"].round(1).tolist(),
            "p": sub["place"].tolist(),
            "s": {
                "n":  s["count"],
                "e":  round(s["energy_mt"], 2),
                "ml": s["max_label"],
            },
        }
    monthly_json = _json.dumps(monthly_js, separators=(",", ":"))
    periods_json = _json.dumps(periods_str)
    print(f"  Monthly data: {len(monthly_json)/1e6:.1f} MB")

    # ── Plotly figure as an embeddable div (no plotlyjs, we add CDN) ───────
    plot_div = fig.to_html(
        include_plotlyjs=False, full_html=False, div_id="eq-map",
        config={"displayModeBar": True, "scrollZoom": True, "responsive": True},
    )

    # ── CSS ────────────────────────────────────────────────────────────────
    CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: {BG_COLOR}; font-family: 'Courier New', monospace;
        color: #ccc; overflow: hidden; }}
/* ── Top header bar (title + date, above the map) ───── */
#header {{
  position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
  height: 90px; padding-top: 20px; padding-bottom: 8px;
  display: flex; flex-direction: column;
  align-items: center; justify-content: flex-end; gap: 6px;
  pointer-events: none;
}}
#header-title {{
  font-size: 20px; color: #8899bb; font-family: 'Courier New', monospace;
  letter-spacing: 1px;
}}
#date-display {{
  font-size: 26px; color: white; font-family: 'Courier New', monospace;
  font-weight: bold; letter-spacing: 2px;
}}

/* Position the map — Plotly controls width/height explicitly via JS */
#eq-map {{
  position: fixed !important;
  top: 90px !important;
  left: 60px !important;
  border-radius: 6px;
  overflow: hidden;
}}

/* ── Control panel ───────────────────────────────────── */
#panel {{
  position: fixed; top: 12px; left: 12px; z-index: 1000;
  background: rgba(10,10,20,0.90); border: 1px solid #2a2a4a;
  border-radius: 8px; padding: 10px 11px; width: 190px;
  backdrop-filter: blur(8px);
}}
#panel h3 {{
  font-size: 10px; letter-spacing: 2px; color: #5577aa;
  text-transform: uppercase; margin-bottom: 11px; padding-bottom: 6px;
  border-bottom: 1px solid #1e1e38; text-align: center;
}}
.row {{ margin-bottom: 10px; }}
.lbl {{ font-size: 10px; color: #778; margin-bottom: 4px; display: flex;
        justify-content: space-between; }}
.lbl span {{ color: #bbb; }}

/* ── Range inputs ────────────────────────────────────── */
input[type=range] {{
  -webkit-appearance: none; width: 100%; height: 3px; border-radius: 2px;
  background: #252540; outline: none; cursor: pointer;
}}
input[type=range]::-webkit-slider-thumb {{
  -webkit-appearance: none; width: 13px; height: 13px; border-radius: 50%;
  background: #4466cc; cursor: pointer;
}}
input[type=range]::-moz-range-thumb {{
  width: 13px; height: 13px; border-radius: 50%;
  background: #4466cc; cursor: pointer; border: none;
}}

/* ── Button groups ───────────────────────────────────── */
.btn-group {{ display: flex; gap: 3px; flex-wrap: nowrap; }}
.btn {{
  padding: 4px 6px; font-size: 10px; font-family: inherit;
  background: #14142a; color: #99a; border: 1px solid #2a2a44;
  border-radius: 4px; cursor: pointer; transition: all 0.12s;
  letter-spacing: 0.3px;
}}
.btn:hover  {{ background: #1e1e3a; color: #dde; }}
.btn.active {{ background: #2e2e7a; color: #fff; border-color: #4455aa; }}
.btn.toggle.on {{ background: #1a4a1a; color: #77ee77; border-color: #2a7a2a; }}

/* ── Select ──────────────────────────────────────────── */
select {{
  width: 100%; background: #14142a; color: #bbb; border: 1px solid #2a2a44;
  border-radius: 4px; padding: 4px 6px; font-family: inherit;
  font-size: 10px; cursor: pointer; outline: none;
}}
select option {{ background: #14142a; }}

/* ── Playback bar ────────────────────────────────────── */
#playbar {{
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 1000;
  background: rgba(10,10,20,0.92); border-top: 1px solid #1e1e38;
  padding: 7px 12px; display: flex; align-items: center; gap: 10px;
}}
#play-btn {{
  padding: 3px 13px; font-size: 15px; background: #14142a; color: #fff;
  border: 1px solid #3a3a5a; border-radius: 4px; cursor: pointer;
  font-family: inherit; min-width: 42px; text-align: center;
}}
#play-btn:hover {{ background: #1e1e3a; }}
#timeline {{
  flex: 1; -webkit-appearance: none; height: 3px; border-radius: 2px;
  background: #252540; outline: none; cursor: pointer;
}}
#timeline::-webkit-slider-thumb {{
  -webkit-appearance: none; width: 13px; height: 13px; border-radius: 50%;
  background: #5566cc; cursor: pointer;
}}
#timeline::-moz-range-thumb {{
  width: 13px; height: 13px; border-radius: 50%;
  background: #5566cc; cursor: pointer; border: none;
}}
#frame-lbl {{ font-size: 11px; color: #778; min-width: 54px; text-align: right; }}

/* ── Cumulative stats (bottom-left, outside the map) ── */
#stats-panel {{
  position: fixed; bottom: 52px; left: 12px; z-index: 1000;
  width: 380px;
  font-size: 11px; color: #cccccc; font-family: 'Courier New', monospace;
  background: rgba(10,10,20,0.88); border: 1px solid #2a2a4a;
  border-radius: 6px; padding: 8px 10px;
  backdrop-filter: blur(8px);
  line-height: 1.6;
  word-wrap: break-word;
}}

/* ── Magnitude legend (bottom-right) ────────────────── */
#legend {{
  position: fixed; bottom: 52px; right: 12px; z-index: 1000;
  background: rgba(10,10,20,0.88); border: 1px solid #2a2a4a;
  border-radius: 8px; padding: 10px 14px;
  backdrop-filter: blur(8px);
}}
#legend h4 {{
  font-size: 10px; letter-spacing: 2px; color: #5577aa;
  text-transform: uppercase; margin-bottom: 8px; padding-bottom: 5px;
  border-bottom: 1px solid #1e1e38;
}}
.leg-row {{
  display: flex; align-items: center; gap: 9px; margin-bottom: 6px;
}}
.leg-row:last-child {{ margin-bottom: 0; }}
.leg-dot {{
  border-radius: 50%; flex-shrink: 0;
  box-shadow: 0 0 4px currentColor;
}}
.leg-lbl {{ font-size: 10px; color: #bbb; white-space: nowrap; }}
"""

    # ── JavaScript ─────────────────────────────────────────────────────────
    # Uses __PLACEHOLDERS__ to avoid f-string brace collisions with JS syntax.
    JS_TEMPLATE = r"""
// ── Embedded data ─────────────────────────────────────────────────────────
var MONTHLY = __MONTHLY__;
var PERIODS = __PERIODS__;
var N       = PERIODS.length;
var DIV     = 'eq-map';

// Custom colorscale stops  [threshold, [r,g,b]]
var CS = [
  [0.00, [26,  120, 194]],
  [0.40, [57,  181,  74]],
  [0.65, [245, 166,  35]],
  [0.85, [232,  39,  43]],
  [1.00, [255, 255, 255]]
];

// ── State ─────────────────────────────────────────────────────────────────
var S = {
  playing:    false,
  frameIdx:   0,
  fps:        8,
  magMin:     4.0,
  cumulative: false,
  energy:     false,
};
var timer    = null;
var cumCache = null;   // { lat, lon, mag, depth, place, pidx[] } filtered by magMin
var cumMag   = null;   // magMin used when cumCache was built

// ── Helpers ───────────────────────────────────────────────────────────────
function magToRGB(mag) {
  var t = Math.max(0, Math.min(1, (mag - 4.0) / 5.0));
  for (var i = 0; i < CS.length - 1; i++) {
    if (t <= CS[i+1][0]) {
      var f  = (t - CS[i][0]) / (CS[i+1][0] - CS[i][0]);
      var lo = CS[i][1], hi = CS[i+1][1];
      return [
        Math.round(lo[0] + (hi[0]-lo[0])*f),
        Math.round(lo[1] + (hi[1]-lo[1])*f),
        Math.round(lo[2] + (hi[2]-lo[2])*f)
      ];
    }
  }
  return [255,255,255];
}
function rgba(rgb, a) {
  return 'rgba('+rgb[0]+','+rgb[1]+','+rgb[2]+','+(+a.toFixed(3))+')';
}
function size(mag) {
  // Normal mode: exponential (M4≈4 M6≈16 M8+≈60)
  return Math.min(60, Math.max(3, Math.pow(2, mag - 3)));
}
function sizeEnergy(mag) {
  // Energy burst: steeper — makes M8 dramatically larger than M5
  return Math.min(90, Math.max(3, Math.pow(2, (mag - 3) * 1.75)));
}
function depthA(depth) {
  return Math.max(0.30, 1.0 - Math.min(depth, 300) / 300 * 0.70);
}

// ── Frame builder ─────────────────────────────────────────────────────────
function buildFrame(idx) {
  var sz = S.energy ? sizeEnergy : size;
  var cur = MONTHLY[PERIODS[idx]];

  // ── Trail / cumulative background ───────────────────────────────────────
  var tLat=[], tLon=[], tCol=[], tSz=[];

  if (S.cumulative) {
    // Rebuild cache when magMin changes
    if (cumMag !== S.magMin) { cumCache = null; cumMag = S.magMin; }
    if (!cumCache) {
      cumCache = { lat:[], lon:[], mag:[], dep:[], pla:[], pi:[] };
      for (var pi = 0; pi < N; pi++) {
        var pd = MONTHLY[PERIODS[pi]];
        for (var j = 0; j < pd.m.length; j++) {
          if (pd.m[j] < S.magMin) continue;
          cumCache.lat.push(pd.a[j]); cumCache.lon.push(pd.o[j]);
          cumCache.mag.push(pd.m[j]); cumCache.dep.push(pd.d[j]);
          cumCache.pla.push(pd.p[j]); cumCache.pi.push(pi);
        }
      }
    }
    for (var k = 0; k < cumCache.pi.length; k++) {
      if (cumCache.pi[k] > idx) break;
      var age   = idx - cumCache.pi[k];
      var alpha = age === 0 ? depthA(cumCache.dep[k])
                            : Math.max(0.04, 0.30 - age * 0.003);
      tLat.push(cumCache.lat[k]); tLon.push(cumCache.lon[k]);
      tCol.push(rgba(magToRGB(cumCache.mag[k]), alpha));
      tSz.push(sz(cumCache.mag[k]));
    }
  } else {
    // Rolling 3-month trail
    var ALPHAS = [0.08, 0.18, 0.40];
    for (var t = 0; t < 3; t++) {
      var ti = idx - (3 - t);
      if (ti < 0) continue;
      var pd = MONTHLY[PERIODS[ti]];
      var a  = ALPHAS[t];
      for (var j = 0; j < pd.m.length; j++) {
        if (pd.m[j] < S.magMin) continue;
        tLat.push(pd.a[j]); tLon.push(pd.o[j]);
        tCol.push(rgba(magToRGB(pd.m[j]), a));
        tSz.push(sz(pd.m[j]));
      }
    }
  }

  // ── Current month ────────────────────────────────────────────────────────
  var cLat=[], cLon=[], cCol=[], cSz=[], cTxt=[];
  var hLat=[], hLon=[], hSz=[];
  var mLat=[], mLon=[], mCol=[], mSz=[], mTxt=[];

  for (var j = 0; j < cur.m.length; j++) {
    var mag=cur.m[j], dep=cur.d[j];
    if (mag < S.magMin) continue;
    var rgb=magToRGB(mag), s2=sz(mag);
    var tip='M'+mag.toFixed(1)+' | '+dep.toFixed(0)+' km | '+cur.p[j];
    if (mag >= 7.0) {
      hLat.push(cur.a[j]); hLon.push(cur.o[j]);
      hSz.push(Math.min(120, s2 * 3.5));
      mLat.push(cur.a[j]); mLon.push(cur.o[j]);
      mCol.push(rgba(rgb, 1.0)); mSz.push(s2); mTxt.push(tip);
    } else {
      cLat.push(cur.a[j]); cLon.push(cur.o[j]);
      cCol.push(rgba(rgb, depthA(dep))); cSz.push(s2); cTxt.push(tip);
    }
  }

  return {
    tLat:tLat, tLon:tLon, tCol:tCol, tSz:tSz,
    cLat:cLat, cLon:cLon, cCol:cCol, cSz:cSz, cTxt:cTxt,
    hLat:hLat, hLon:hLon, hSz:hSz,
    mLat:mLat, mLon:mLon, mCol:mCol, mSz:mSz, mTxt:mTxt,
    stats: cur.s,
  };
}

// ── Render ────────────────────────────────────────────────────────────────
function render(idx) {
  var f = buildFrame(idx);
  var period = PERIODS[idx];
  var s = f.stats;

  // Update all 4 earthquake traces in one restyle call
  Plotly.restyle(DIV, {
    lat:           [f.tLat, f.cLat, f.hLat, f.mLat],
    lon:           [f.tLon, f.cLon, f.hLon, f.mLon],
    'marker.size': [f.tSz,  f.cSz,  f.hSz,  f.mSz],
    'marker.color':[f.tCol, f.cCol,
                    f.hLat.map(function(){return 'rgba(0,0,0,0)';}),
                    f.mCol],
    text:          [f.tLat.map(function(){return '';}), f.cTxt,
                    f.hLat.map(function(){return '';}), f.mTxt],
    'marker.line.color': [
      f.tLat.map(function(){return 'rgba(0,0,0,0)';}),
      f.cLat.map(function(){return 'rgba(0,0,0,0)';}),
      f.hLat.map(function(){return 'rgba(255,200,50,0.75)';}),
      f.mLat.map(function(){return 'rgba(0,0,0,0)';}),
    ],
    'marker.line.width': [
      f.tLat.map(function(){return 0;}),
      f.cLat.map(function(){return 0;}),
      f.hLat.map(function(){return 2;}),
      f.mLat.map(function(){return 0;}),
    ],
  }, [1, 2, 3, 4]);

  document.getElementById('date-display').textContent = period;
  document.getElementById('stats-panel').innerHTML =
    '<b>Cumulative events:</b> ' + s.n.toLocaleString() + '<br>' +
    '<b>Largest:</b> '           + s.ml                 + '<br>' +
    '<b>Total energy:</b> '      + s.e.toFixed(1)       + ' Mt TNT';

  document.getElementById('timeline').value  = idx;
  document.getElementById('frame-lbl').textContent = period;
  S.frameIdx = idx;
}

// ── Playback ──────────────────────────────────────────────────────────────
function play() {
  if (S.playing) return;
  S.playing = true;
  document.getElementById('play-btn').textContent = '⏸';
  timer = setInterval(function() {
    render((S.frameIdx + 1) % N);
  }, Math.round(1000 / S.fps));
}
function pause() {
  S.playing = false;
  document.getElementById('play-btn').textContent = '▶';
  clearInterval(timer); timer = null;
}

// ── Control wiring ────────────────────────────────────────────────────────
document.getElementById('play-btn')
  .addEventListener('click', function() { S.playing ? pause() : play(); });

document.getElementById('timeline')
  .addEventListener('input', function() { render(parseInt(this.value)); });

document.getElementById('speed-slider')
  .addEventListener('input', function() {
    S.fps = parseInt(this.value);
    document.getElementById('speed-val').textContent = S.fps + ' fps';
    if (S.playing) { pause(); play(); }
  });

document.querySelectorAll('#mag-btns .btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    document.querySelectorAll('#mag-btns .btn')
      .forEach(function(b) { b.classList.remove('active'); });
    this.classList.add('active');
    S.magMin = parseFloat(this.dataset.mag);
    cumCache = null;   // invalidate cumulative cache
    render(S.frameIdx);
  });
});

document.getElementById('proj-select')
  .addEventListener('change', function() {
    Plotly.relayout(DIV, {'geo.projection.type': this.value});
  });

document.getElementById('btn-cumulative')
  .addEventListener('click', function() {
    S.cumulative = !S.cumulative;
    this.classList.toggle('on', S.cumulative);
    render(S.frameIdx);
  });

document.getElementById('btn-energy')
  .addEventListener('click', function() {
    S.energy = !S.energy;
    this.classList.toggle('on', S.energy);
    render(S.frameIdx);
  });

// ── Sizing ────────────────────────────────────────────────────────────────
// Drive the map size explicitly in pixels so Plotly cannot override it.
// MAP_TOP matches the header height; MAP_SIDE is left/right margin.
var MAP_TOP  = 90;
var MAP_SIDE = 60;
var PLAYBAR_H = 44;

function resizeMap() {
  var w = window.innerWidth  - MAP_SIDE * 2;
  var h = window.innerHeight - MAP_TOP - PLAYBAR_H - MAP_SIDE;
  Plotly.relayout(DIV, { width: w, height: h, autosize: false });
}

window.addEventListener('resize', resizeMap);

// ── Boot ──────────────────────────────────────────────────────────────────
(function waitForPlotly() {
  var el = document.getElementById(DIV);
  if (el && el._fullLayout) {
    resizeMap();
    setTimeout(function() { render(0); }, 80);
  } else {
    setTimeout(waitForPlotly, 100);
  }
})();
"""

    JS = (JS_TEMPLATE
          .replace("__MONTHLY__", monthly_json)
          .replace("__PERIODS__", periods_json))

    # ── Build legend HTML from Python-computed colorscale ─────────────────
    LEGEND_ENTRIES = [
        (4.0, "M4  — minor",    8),
        (5.0, "M5  — moderate", 12),
        (6.0, "M6  — strong",   18),
        (7.0, "M7  — major",    26),
        (8.0, "M8  — great",    34),
        (9.0, "M9+ — extreme",  42),
    ]
    legend_rows = ""
    for mag, label, diameter in LEGEND_ENTRIES:
        color = _val_to_hex((mag - MAG_MIN) / (9.0 - MAG_MIN))
        legend_rows += (
            f'<div class="leg-row">'
            f'<div class="leg-dot" style="width:{diameter}px;height:{diameter}px;'
            f'background:{color};box-shadow:0 0 6px {color};"></div>'
            f'<span class="leg-lbl">{label}</span>'
            f'</div>\n'
        )

    # ── Assemble full HTML ─────────────────────────────────────────────────
    first = periods_str[0]
    HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Earthquake Timelapse 1990\u20132023</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>{CSS}</style>
</head>
<body>

{plot_div}

<!-- ── Title + date header (above the map) ───────────── -->
<div id="header">
  <span id="header-title">Worldwide Earthquakes (1990&#8211;2023)</span>
  <span id="date-display">{first}</span>
</div>

<!-- ── Controls panel (top-right) ──────────────────────── -->
<div id="panel">
  <h3>Visualization<br>Controls</h3>

  <div class="row">
    <div class="lbl">Speed <span id="speed-val">8 fps</span></div>
    <input type="range" id="speed-slider" min="1" max="24" value="8">
  </div>

  <div class="row">
    <div class="lbl">Min Magnitude</div>
    <div class="btn-group" id="mag-btns">
      <button class="btn active" data-mag="4.0">M4+</button>
      <button class="btn"        data-mag="5.0">M5+</button>
      <button class="btn"        data-mag="6.0">M6+</button>
      <button class="btn"        data-mag="7.0">M7+</button>
    </div>
  </div>

  <div class="row">
    <div class="lbl">Projection</div>
    <select id="proj-select">
      <option value="natural earth" selected>Natural Earth</option>
      <option value="orthographic">Orthographic (Globe)</option>
      <option value="mercator">Mercator</option>
    </select>
  </div>

  <div class="row">
    <div class="lbl">Display Mode</div>
    <div class="btn-group">
      <button class="btn toggle" id="btn-cumulative">Cumulative</button>
      <button class="btn toggle" id="btn-energy">Energy Burst</button>
    </div>
  </div>
</div>

<!-- ── Cumulative stats (bottom-left) ────────────────────── -->
<div id="stats-panel"></div>

<!-- ── Magnitude legend (bottom-right) ──────────────────── -->
<div id="legend">
  <h4>Magnitude</h4>
{legend_rows}</div>

<!-- ── Playback bar (bottom) ─────────────────────────────── -->
<div id="playbar">
  <button id="play-btn">&#x25B6;</button>
  <input type="range" id="timeline" min="0" max="{n - 1}" value="0" step="1">
  <span id="frame-lbl">{first}</span>
</div>

<script>{JS}</script>
</body>
</html>"""

    out = BASE / "earthquake_viz.html"
    print(f"  Writing {out} …")
    with open(str(out), "w", encoding="utf-8") as fh:
        fh.write(HTML)
    size_mb = out.stat().st_size / 1e6
    print(f"  Saved: {out}  ({size_mb:.1f} MB)")
    return str(out)


# ══════════════════════════════════════════════════════════════════════════
# 5. Video / GIF (Matplotlib + Cartopy)
# ══════════════════════════════════════════════════════════════════════════

def render_video(df: pd.DataFrame, plate_segments: list,
                 fast: bool = False) -> tuple[str, str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    import imageio

    print("\nRendering video frames …")

    periods = sorted(df["year_month"].unique())
    if fast:
        # Quarterly frames for quick preview
        periods = [p for i, p in enumerate(periods) if i % 3 == 0]
        print(f"  Fast mode: {len(periods)} quarterly frames")
    else:
        print(f"  {len(periods)} monthly frames")

    cum_stats = build_cumulative_stats(df, sorted(df["year_month"].unique()))

    # Custom colormap
    cmap = LinearSegmentedColormap.from_list(
        "earthquake", [c for _, c in CUSTOM_COLORSCALE], N=256
    )

    FIG_W = 12.8 if fast else 16.0
    FIG_H = 7.2  if fast else 9.0
    DPI   = 80   if fast else 100
    proj  = ccrs.Robinson()

    frames_dir = Path(tempfile.mkdtemp(prefix="eq_frames_"))
    frame_paths = []

    def mag_to_area(mag_arr):
        """Scatter s= (area) from magnitude."""
        return np.clip(2.0 ** (mag_arr - 2.5), 4, 900)

    for i, period in enumerate(periods):
        fig = plt.figure(figsize=(FIG_W, FIG_H), facecolor=BG_COLOR)
        ax = fig.add_axes([0, 0, 1, 1], projection=proj)
        ax.set_facecolor(BG_COLOR)
        ax.set_global()
        # Hide the map border frame (API changed across cartopy versions)
        try:
            ax.outline_patch.set_visible(False)
        except AttributeError:
            pass

        # Background
        ax.add_feature(cfeature.OCEAN.with_scale("110m"), facecolor=OCEAN_COLOR, zorder=0)
        ax.add_feature(cfeature.LAND.with_scale("110m"),  facecolor=LAND_COLOR,  zorder=1)
        ax.add_feature(cfeature.COASTLINE.with_scale("110m"),
                       edgecolor=COAST_COLOR, linewidth=0.4, zorder=2)

        # Plate boundaries
        for seg_lons, seg_lats in plate_segments:
            if len(seg_lons) < 2:
                continue
            try:
                ax.plot(seg_lons, seg_lats, color=PLATE_COLOR, linewidth=0.5,
                        transform=ccrs.PlateCarree(), zorder=3, alpha=0.75)
            except Exception:
                pass

        # Find this period's index in the original full periods list
        all_periods = sorted(df["year_month"].unique())
        full_i = all_periods.index(period)

        # Trail: up to TRAIL_MONTHS prior months
        trail_indices = range(max(0, full_i - TRAIL_MONTHS), full_i + 1)
        trail_list = [all_periods[j] for j in trail_indices]

        for k, tp in enumerate(trail_list):
            alpha_idx = k - (len(trail_list) - len(TRAIL_OPACITIES))
            alpha = TRAIL_OPACITIES[max(0, alpha_idx)]
            is_current = k == len(trail_list) - 1

            sub = df[df["year_month"] == tp]
            if sub.empty:
                continue

            lons   = sub["longitude"].values
            lats   = sub["latitude"].values
            mags   = sub["magnitude"].values
            cvals  = sub["color_val"].values
            sizes  = mag_to_area(mags)

            if is_current:
                depth_alphas = _depth_to_opacity(sub["depth"]).values * alpha
            else:
                depth_alphas = np.full(len(sub), alpha)

            reg = mags < 7.0
            maj = mags >= 7.0

            # Regular events
            if reg.any():
                rgba = cmap(cvals[reg])
                rgba[:, 3] = depth_alphas[reg]
                ax.scatter(lons[reg], lats[reg], s=sizes[reg], c=rgba,
                           transform=ccrs.PlateCarree(), zorder=4,
                           linewidths=0, rasterized=True)

            # M7+ halo + core
            if maj.any():
                ax.scatter(lons[maj], lats[maj], s=sizes[maj] * 9,
                           facecolors="none", edgecolors="#ffc832",
                           linewidths=1.5, transform=ccrs.PlateCarree(),
                           zorder=5, alpha=min(1.0, alpha * 1.2))
                rgba_maj = cmap(cvals[maj])
                rgba_maj[:, 3] = np.minimum(1.0, depth_alphas[maj])
                ax.scatter(lons[maj], lats[maj], s=sizes[maj], c=rgba_maj,
                           transform=ccrs.PlateCarree(), zorder=6,
                           linewidths=0, rasterized=True)

        # ── Overlays ───────────────────────────────────────────────────────
        s = cum_stats[period]
        period_str = str(period)[:7]

        # Title + date (upper center)
        ax.text(0.5, 0.995, "Worldwide Earthquakes (1990\u20132023)",
                transform=ax.transAxes, ha="center", va="top",
                fontsize=8, color="#8899bb", fontfamily="monospace",
                zorder=10)
        ax.text(0.5, 0.97, period_str,
                transform=ax.transAxes, ha="center", va="top",
                fontsize=18, color="white", fontfamily="monospace",
                fontweight="bold", zorder=10)

        # Stats panel (lower left)
        stats_txt = (f"Events: {s['count']:,}\n"
                     f"Largest: {s['max_label']}\n"
                     f"Energy: {s['energy_mt']:.1f} Mt TNT")
        ax.text(0.012, 0.04, stats_txt,
                transform=ax.transAxes, ha="left", va="bottom",
                fontsize=8, color="#cccccc", fontfamily="monospace",
                bbox=dict(facecolor="#0a0a14", edgecolor="#333355",
                          boxstyle="round,pad=0.5", linewidth=0.7),
                zorder=10)

        # Size legend (lower right)
        legend_entries = [(4, "M4"), (5, "M5"), (6, "M6"), (7, "M7"), (8, "M8+")]
        leg_y = 0.20
        for lm, label in legend_entries:
            lm_area  = mag_to_area(np.array([float(lm)]))[0]
            lm_cval  = (lm - MAG_MIN) / (9.0 - MAG_MIN)
            lm_color = cmap(np.clip(lm_cval, 0, 1))
            # Fake scatter at axes coords via annotation trick
            ax.scatter([0.945], [leg_y], s=lm_area, c=[lm_color],
                       transform=ax.transAxes, zorder=10,
                       linewidths=0, clip_on=False)
            ax.text(0.965, leg_y, label,
                    transform=ax.transAxes, ha="left", va="center",
                    fontsize=7, color="#aaaaaa", zorder=10, clip_on=False)
            leg_y -= 0.032

        fpath = frames_dir / f"frame_{i:04d}.png"
        fig.savefig(str(fpath), dpi=DPI, facecolor=BG_COLOR)
        plt.close(fig)
        frame_paths.append(str(fpath))

        if (i + 1) % 20 == 0 or (i + 1) == len(periods):
            print(f"  Rendered {i+1}/{len(periods)}")

    print(f"  All frames saved to {frames_dir}")

    # ── Stitch MP4 ─────────────────────────────────────────────────────────
    mp4_path = BASE / "earthquake_viz.mp4"
    print(f"  Writing MP4: {mp4_path} …")
    fps_mp4 = 8 if fast else 12
    # imageio ≥2.28 uses imageio.v3; older uses get_writer — try both
    try:
        import imageio.v3 as iio3
        frames_arr = [iio3.imread(p) for p in frame_paths]
        iio3.imwrite(str(mp4_path), frames_arr, fps=fps_mp4, codec="libx264")
    except (ImportError, AttributeError):
        with imageio.get_writer(str(mp4_path), fps=fps_mp4,
                                codec="libx264", macro_block_size=None) as writer:
            for p in frame_paths:
                writer.append_data(imageio.imread(p))
    print(f"  Saved MP4: {mp4_path}  ({mp4_path.stat().st_size / 1e6:.1f} MB)")

    # ── Stitch GIF ─────────────────────────────────────────────────────────
    gif_path = BASE / "earthquake_viz.gif"
    print(f"  Writing GIF: {gif_path} …")
    gif_frames = [imageio.imread(p) for p in frame_paths[::2]]
    fps_gif = 6 if fast else 8
    imageio.mimsave(str(gif_path), gif_frames, fps=fps_gif, loop=0)
    print(f"  Saved GIF: {gif_path}  ({gif_path.stat().st_size / 1e6:.1f} MB)")

    shutil.rmtree(frames_dir, ignore_errors=True)
    print("  Temp frames cleaned up.")
    return str(mp4_path), str(gif_path)


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Earthquake Timelapse Visualization")
    parser.add_argument("--html-only",  action="store_true", help="Generate HTML only")
    parser.add_argument("--video-only", action="store_true", help="Generate video/GIF only")
    parser.add_argument("--fast",       action="store_true",
                        help="Quick preview: quarterly frames, lower resolution")
    parser.add_argument("--fetch-usgs",  action="store_true",
                        help="Fetch data from USGS ComCat API (free, no login), then run")
    parser.add_argument("--download",   action="store_true",
                        help="Download dataset via Kaggle API, then run")
    args = parser.parse_args()

    if args.fetch_usgs:
        fetch_usgs()
    elif args.download:
        download_dataset()

    df             = load_data()
    plate_segments = load_plates()

    if not args.video_only:
        build_plotly_html(df, plate_segments)

    if not args.html_only:
        render_video(df, plate_segments, fast=args.fast)

    print("\n✓ Done!")


if __name__ == "__main__":
    main()
