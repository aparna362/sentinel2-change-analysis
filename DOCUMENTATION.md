# Technical Documentation — Sentinel-2 Change Analysis

Engineering reference for the change-analysis pipeline over an open-pit mining
site in Zambia, comparing two Sentinel-2 acquisitions (**2023-08-12** →
**2023-09-02**).

For a quick start see [README.md](README.md). For the write-up and interpretation
see [report.md](report.md). This document covers architecture, each module,
the algorithms with their maths, data specs, configuration, design decisions,
and troubleshooting.

---

## Table of contents
1. [Overview](#1-overview)
2. [Architecture & data flow](#2-architecture--data-flow)
3. [Repository layout](#3-repository-layout)
4. [Installation](#4-installation)
5. [Running the pipeline](#5-running-the-pipeline)
6. [Configuration reference](#6-configuration-reference)
7. [Input data specification](#7-input-data-specification)
8. [Module reference](#8-module-reference)
9. [Algorithms in depth](#9-algorithms-in-depth)
10. [Output specification](#10-output-specification)
11. [Database schema & queries](#11-database-schema--queries)
12. [The diagonal artifact](#12-the-diagonal-artifact)
13. [Results summary](#13-results-summary)
14. [Design decisions & trade-offs](#14-design-decisions--trade-offs)
15. [Extending the pipeline](#15-extending-the-pipeline)
16. [Troubleshooting](#16-troubleshooting)
17. [Limitations & future work](#17-limitations--future-work)

---

## 1. Overview

The pipeline takes two co-registered 3-band (Blue/Green/Red) Sentinel-2 scenes,
finds where the surface changed between them, turns the change mask into vector
polygons with attributes, stores them in a spatial database, and produces static
and interactive figures.

It maps to five assignment parts:

| Part | Stage | Module |
|------|-------|--------|
| 1 | Data preparation | [`data_preparation.py`](src/data_preparation.py) |
| 2 | Change detection | [`change_detection.py`](src/change_detection.py) |
| 3 | Feature extraction & storage | [`feature_extraction.py`](src/feature_extraction.py) |
| 4 | Visualisation | [`visualize.py`](src/visualize.py) |
| 5 | Analysis & interpretation | [`report.md`](report.md) |

Supporting modules:
- [`config.py`](src/config.py) — all paths and parameters in one place
- [`pipeline.py`](src/pipeline.py) — runs Parts 1–4 in sequence
- [`artifact_diagnostics.py`](src/artifact_diagnostics.py) — seam artifact analysis

Standalone threshold comparison scripts (demonstrate why CVA was chosen):
- [`otsu_threshold.py`](src/otsu_threshold.py) — shows Otsu flagging 45.75% on a unimodal histogram
- [`mean_std_threshold.py`](src/mean_std_threshold.py) — shows mean/std sensitivity to outliers
- [`threshold_comparison.py`](src/threshold_comparison.py) — all three methods on one figure

**Design principles:**
- Single source of truth — every path and parameter lives in `config.py`.
- Each stage reads files and writes files, so any stage can be run on its own.
- Deterministic — a clean run produces identical outputs every time.
- Artifacts and limitations are documented rather than hidden.

---

## 2. Architecture & data flow

```
            inputs/aoi.geojson
                    |
  data/sentinel2_20230812/{B02,B03,B04}.tif  |
  data/sentinel2_20230902/{B02,B03,B04}.tif  |
                    |
        +-----------v-----------+
        | PART 1  data_prep     |  read, verify grid, stack
        +-----------+-----------+
                    |  data/processed/sentinel2_*_stack.tif
        +-----------v-----------+
        | PART 2  change_detect |  reflectance, CVA magnitude, threshold
        +-----------+-----------+
                    |  change_map.tif, change_binary.tif, change_map_example.tif
        +-----------v-----------+
        | PART 3  feature_extr  |  polygonise, area + confidence, store
        +-----------+-----------+
                    |  data/processed/changes.gpkg
        +-----------v-----------+
        | PART 4  visualize     |  static PNG, interactive HTML
        +-----------+-----------+
                    |  outputs/change_overview.png, change_map.html
                    v
              report.md  (Part 5, human interpretation)
```

Each arrow is a file on disk, so stages are independently runnable.

---

## 3. Repository layout

```
.
|-- README.md                   Quick start, approach, assumptions
|-- DOCUMENTATION.md            This file
|-- report.md                   Part 5 — method / results / interpretation
|-- requirements.txt            Python dependencies
|-- inputs/
|   |-- aoi.geojson             Area of interest (WGS84 polygon)
|   `-- example_change_detection.py   Provided baseline algorithm
|-- data/
|   |-- sentinel2_20230812/     B02.tif B03.tif B04.tif  (before)
|   |-- sentinel2_20230902/     B02.tif B03.tif B04.tif  (after)
|   `-- processed/              Generated outputs
|       |-- sentinel2_20230812_stack.tif
|       |-- sentinel2_20230902_stack.tif
|       |-- change_map.tif
|       |-- change_binary.tif
|       |-- change_map_example.tif
|       `-- changes.gpkg
|-- outputs/
|   |-- change_overview.png
|   |-- change_map.html
|   |-- artifact_diagnostics.png
|   |-- otsu_threshold.png
|   |-- mean_std_threshold.png
|   `-- threshold_comparison.png
`-- src/
    |-- config.py               Paths + parameters
    |-- data_preparation.py     Part 1
    |-- change_detection.py     Part 2
    |-- feature_extraction.py   Part 3
    |-- visualize.py            Part 4
    |-- artifact_diagnostics.py Artifact analysis (standalone)
    |-- otsu_threshold.py       Otsu failure demonstration (standalone)
    |-- mean_std_threshold.py   Mean/std fragility demonstration (standalone)
    |-- threshold_comparison.py All three methods side by side (standalone)
    `-- pipeline.py             Runs Parts 1–4
```

---

## 4. Installation

Python 3.10+ required. The geospatial packages ship binary wheels so no system
GDAL install is needed on macOS/Linux/Windows.

```bash
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

| Package | Used for |
|---------|----------|
| `rasterio` | raster I/O, features.shapes (polygonisation) |
| `geopandas` / `shapely` | vector features, GeoPackage write |
| `numpy` | array maths — CVA, thresholding |
| `matplotlib` | static figures |
| `folium` | interactive Leaflet map |
| `scipy` | Gaussian background filter (optional RRN and diagnostics only) |

`scipy` is only needed for the optional RRN step and `artifact_diagnostics.py`.
The core pipeline and the three threshold scripts run without it.

---

## 5. Running the pipeline

**Full pipeline (Parts 1–4):**
```bash
python src/pipeline.py
```

**Individual stages:**
```bash
python src/data_preparation.py
python src/change_detection.py
python src/feature_extraction.py
python src/visualize.py
python src/artifact_diagnostics.py
```

**Threshold comparison scripts** (run `data_preparation.py` first):
```bash
python src/otsu_threshold.py        # outputs/otsu_threshold.png
python src/mean_std_threshold.py    # outputs/mean_std_threshold.png
python src/threshold_comparison.py  # outputs/threshold_comparison.png
```

Expected console output (default config):
```
Robust threshold (reflectance units): 0.1174
Changed pixels: 23,208 of 2,645,712 valid (0.88%)
Stored 156 features in changes.gpkg (layer 'change_features')
Total changed area: 185.8 ha
```

---

## 6. Configuration reference

Everything in [`src/config.py`](src/config.py).

| Name | Default | Meaning |
|------|---------|---------|
| `DATE_BEFORE` / `DATE_AFTER` | `"20230812"` / `"20230902"` | Scene date stamps; order = before → after |
| `BANDS` | `["B02","B03","B04"]` | Bands loaded and stacked, in order |
| `REFLECTANCE_SCALE` | `10000.0` | DN ÷ this = reflectance (Sentinel-2 L2A convention) |
| `THRESHOLD_K` | `3.0` | Multiplier in `median + k·1.4826·MAD` |
| `REMOVE_BACKGROUND` | `False` | Enable Gaussian background subtraction (RRN) |
| `BACKGROUND_SIGMA` | `100` | Gaussian sigma in pixels (~1 km) for the RRN step |
| `MIN_POLYGON_AREA_M2` | `2000.0` | Drop polygons smaller than this (speckle filter) |
| `CHANGE_TABLE` | `"change_features"` | Layer/table name in the GeoPackage |

Tuning:
- **More detections:** lower `THRESHOLD_K` (try 2). Fewer: raise it (try 4).
- **Remove the diagonal seam from the intensity picture:** set
  `REMOVE_BACKGROUND = True` and raise `THRESHOLD_K` to ~5.
- **Larger/smaller minimum polygon:** change `MIN_POLYGON_AREA_M2`.

---

## 7. Input data specification

| Property | Value |
|----------|-------|
| Bands | B02 Blue, B03 Green, B04 Red (10 m optical) |
| CRS | EPSG:32735 (UTM zone 35S) |
| Pixel size | 10 m × 10 m |
| Dimensions | 1673 × 1597 pixels |
| Dtype | uint16 |
| Nodata | 0 |
| Encoding | Sentinel-2 L2A surface reflectance, DN = reflectance × 10000 |

Both dates share an identical grid (same CRS, affine transform and size).
Part 1 asserts this before doing any arithmetic.

**AOI** (`inputs/aoi.geojson`): a single WGS84 polygon over the mine, used only
as a visual overlay (~25.79–25.94°E, −12.32 to −12.18°S).

---

## 8. Module reference

### 8.1 `config.py`
Constants only. Every other module imports from here so paths and parameters are
defined once. All paths are computed relative to the repo root so the project
works from any location.

### 8.2 `data_preparation.py` — Part 1

| Function | What it does |
|----------|-------------|
| `load_and_check_scene(date)` | Reads B02/B03/B04 for one date; checks all three bands share the same CRS, transform and dimensions; returns the 3-band stack |
| `write_stack(stack, profile, path)` | Writes a compressed 3-band GeoTIFF |
| `prepare()` | Runs both dates, checks inter-date co-registration, writes the stacks |

Raises `ValueError` on any grid mismatch so misaligned inputs are caught before
the change maths run.

### 8.3 `change_detection.py` — Part 2

| Function | What it does |
|----------|-------------|
| `_read_stack(path)` | Read a stack as float32 + profile |
| `_valid_mask(before, after)` | True where DN > 0 in all bands of both dates |
| `remove_background(diff, valid, sigma)` | Optional RRN — subtracts a large-sigma Gaussian from each band difference |
| `robust_threshold(values, k)` | `median + k·1.4826·MAD` |
| `detect_change()` | Full Part 2 pipeline; writes `change_map.tif`, `change_binary.tif`, `change_map_example.tif` |
| `_write(...)` | Single-band GeoTIFF writer |

### 8.4 `feature_extraction.py` — Part 3

| Function | What it does |
|----------|-------------|
| `extract_features()` | Polygonise the binary raster, drop small polygons, compute confidence, write GeoPackage |
| `_zonal_mean(polygons, intensity, transform)` | Average change intensity inside each polygon |
| `_fmt_date(yyyymmdd)` | `"20230812"` → `"2023-08-12"` |

Polygons are built with `rasterio.features.shapes`. Because the CRS is metric
UTM, `shapely`'s `.area` already gives square metres. Features are sorted by
area and given a 1-based `id`.

### 8.5 `visualize.py` — Part 4

| Function | What it does |
|----------|-------------|
| `_rgb(path)` | Read a band stack and stretch contrast to 2–98 percentile |
| `_rgb_overlay_4326(path, ...)` | Reproject to WGS84, encode as data-URI PNG for Leaflet |
| `static_overview(gdf)` | 4-panel figure: before/after RGB, intensity map, polygons |
| `interactive_map(gdf)` | Folium map with before/after swipe slider and polygon overlay |
| `visualize()` | Calls both of the above |

The before/after swipe map uses the `leaflet-side-by-side` plugin. That plugin
calls `getContainer()` on layers, which `ImageOverlay` exposes as `getElement()`.
A one-line patch aliasing the method is injected before the plugin loads:
```js
L.ImageOverlay.prototype.getContainer = L.ImageOverlay.prototype.getElement;
```

### 8.6 `artifact_diagnostics.py`
Standalone seam analysis. Prints per-band difference stats and the
threshold-vs-seam ratio, and writes `outputs/artifact_diagnostics.png`.

### 8.7 `otsu_threshold.py`
Standalone. Implements Otsu from scratch with numpy (no skimage). Produces a
5-panel figure: full histogram, between-class variance curve, zoomed histogram,
CVA binary map (green, 0.88%), Otsu binary map (red, 45.75%). Shows concretely
why Otsu fails on a unimodal histogram.

### 8.8 `mean_std_threshold.py`
Standalone. Shows how the mean is pulled upward by outlier pixels, how removing
just the top 0.1% of pixels shifts the threshold, and compares the two binary
maps side by side. Demonstrates that mean/std gives an unstable threshold.

### 8.9 `threshold_comparison.py`
Standalone. Puts all three methods (Otsu, mean/std, CVA) on one figure: the
histogram with all three threshold lines marked, a stats summary table, and a
binary map for each method.

### 8.10 `pipeline.py`
Calls `prepare → detect_change → extract_features → visualize` in order with
banner logging. The single entry point for a full reproducible run.

---

## 9. Algorithms in depth

### 9.1 Change Vector Analysis (CVA)

For each pixel with before reflectance vector **b** and after vector **a**:

```
diff = a - b                               # per-band change, shape (3, h, w)
magnitude(x, y) = sqrt(sum(diff(x,y)^2))  # Euclidean length of the change vector
```

`magnitude` is the per-pixel change intensity. Using all three bands captures
both brightness and colour shift. With only B/G/R (no NIR), a vegetation index
like NDVI is impossible, so a multi-band magnitude is the most you can get from
this dataset in an unsupervised way.

### 9.2 Robust thresholding

A pixel is *changed* when:

```
magnitude > median(magnitude) + k * 1.4826 * MAD(magnitude)

where:
  MAD = median(|magnitude - median(magnitude)|)
  k   = THRESHOLD_K = 3
```

`1.4826 * MAD` is a consistent estimate of the standard deviation for a normal
distribution, so `k = 3` behaves like a 3-sigma outlier rule. The median and
MAD are used instead of mean and std because outliers (genuine change pixels)
cannot move them — the threshold stays anchored to the background.

Why not Otsu: the histogram is unimodal (one hump). Otsu needs two humps with a
valley. Without a valley it picks the middle of the hump and flags ~46% of the
scene. See `src/otsu_threshold.py`.

Why not mean/std: the mean is pulled up by the genuine-change tail. The result
is fragile — removing 0.1% of pixels changes the threshold by 0.003 units.
See `src/mean_std_threshold.py`.

### 9.3 Otsu's method (implemented in otsu_threshold.py)

For each candidate threshold t, split pixels into class 0 (below t) and class 1
(above t). Compute the between-class variance:

```
BCV(t) = w0 * w1 * (m0 - m1)^2

where w0, w1 are the class weights and m0, m1 are the class means.
```

Choose the t with the highest BCV. On a unimodal histogram BCV has no sharp
peak — it rises and falls gradually and the chosen t ends up near the mode,
splitting roughly half the pixels on each side.

### 9.4 Intensity normalisation

```
hi = 99.9th percentile of magnitude over valid pixels
intensity = clip(magnitude / hi, 0, 1)    # float32 saved as change_map.tif
```

The 99.9th-percentile cap (not the max) is robust to a handful of extreme
pixels, and it sits above the change threshold so genuine-change pixels spread
across roughly 0.5–1.0, making per-polygon mean intensity (confidence) actually
discriminate weak from strong change (observed range 0.56–0.91).

### 9.5 Relative Radiometric Normalization (optional)

```
background_band = gaussian(diff_band * valid, sigma) / gaussian(valid, sigma)
diff_band -= background_band
```

A large-sigma (~1 km) smooth filter captures the low-frequency global offset and
detector seam while leaving compact real change untouched. Off by default — see
§12 for the trade-off.

### 9.6 Polygonisation and zonal confidence

`rasterio.features.shapes` traces the `binary == 1` pixels into polygons in the
raster CRS (UTM metres). Polygons below `MIN_POLYGON_AREA_M2` are discarded.
For each remaining polygon, `_zonal_mean` rasterises it to a pixel mask and
averages the `change_map` intensity values inside — that average is `confidence`.

---

## 10. Output specification

| File | Format | CRS | Content |
|------|--------|-----|---------|
| `sentinel2_<date>_stack.tif` | GeoTIFF, 3-band, deflate | EPSG:32735 | uint16; Blue/Green/Red |
| `change_map.tif` | GeoTIFF, 1-band | EPSG:32735 | float32 0–1 change intensity |
| `change_binary.tif` | GeoTIFF, 1-band | EPSG:32735 | uint8: 1 = change, 0 = no change (nodata 255) |
| `change_map_example.tif` | GeoTIFF, 1-band | EPSG:32735 | uint8 0–255 baseline (nodata 0) |
| `changes.gpkg` | GeoPackage (SQLite) | EPSG:32735 | layer `change_features` |
| `change_overview.png` | PNG | — | 4-panel static figure |
| `change_map.html` | HTML | EPSG:4326 overlays | before/after swipe + layers |
| `artifact_diagnostics.png` | PNG | — | seam analysis figure |
| `otsu_threshold.png` | PNG | — | Otsu failure figure |
| `mean_std_threshold.png` | PNG | — | Mean/std fragility figure |
| `threshold_comparison.png` | PNG | — | All three methods compared |

---

## 11. Database schema & queries

`changes.gpkg` is an OGC GeoPackage — a SQLite database with a true geometry
type. Open it in QGIS, GeoPandas/Fiona, the `sqlite3` CLI, or SpatiaLite.

**Table `change_features`:**

| Column | Type | Description |
|--------|------|-------------|
| `fid` | INTEGER | GeoPackage primary key (auto) |
| `id` | INTEGER | 1-based feature id, area-sorted |
| `date_before` | TEXT | `YYYY-MM-DD` of the earlier scene |
| `date_after` | TEXT | `YYYY-MM-DD` of the later scene |
| `area_m2` | REAL | Polygon area in square metres (metric UTM) |
| `confidence` | REAL | Mean change intensity 0–1 inside the polygon |
| `geom` | POLYGON | Geometry, EPSG:32735 |

**Example queries:**
```bash
# Top-5 largest changes
sqlite3 data/processed/changes.gpkg \
  "SELECT id, area_m2, confidence FROM change_features ORDER BY area_m2 DESC LIMIT 5;"

# Total changed area in hectares
sqlite3 data/processed/changes.gpkg \
  "SELECT ROUND(SUM(area_m2)/10000.0, 1) AS total_ha FROM change_features;"
```

```python
import geopandas as gpd
gdf = gpd.read_file("data/processed/changes.gpkg", layer="change_features")
print(gdf[["id", "area_m2", "confidence"]].head())
```

---

## 12. The diagonal artifact

Full treatment in [report.md §4](report.md#4-the-diagonal-artifact--what-it-is-and-why-it-does-not-matter).
Reproduce with `python src/artifact_diagnostics.py`.

**What:** a faint diagonal stripe in the change-intensity map. It is a
Sentinel-2 detector-module seam: adjacent modules view the ground at slightly
different angles, so the brightness offset between two acquisitions is not
constant across the seam boundary. Both single-date images are smooth — the
stripe only appears in the difference.

**Impact on results:** none. The seam sits at magnitude ~0.047. The robust
threshold is 0.117 (2.5× higher). The seam is excluded from binary detections.

**Removal options:** robust threshold + min-area filter (both in use) already
handle it. `REMOVE_BACKGROUND = True` flattens the seam visually but brings in
texture noise. The production fix (MSK_DETFOO detector-footprint mask from the
SAFE metadata) is not available here.

---

## 13. Results summary

| Metric | Value |
|--------|-------|
| Valid pixels compared | 2,645,712 |
| Robust threshold (reflectance) | 0.1174 |
| Changed pixels | 23,208 (0.88%) |
| Change polygons (>= 2000 m²) | 156 |
| Total changed area | 185.8 ha |
| Polygon area: median / max | 0.45 ha / 33 ha |
| Confidence: min / mean / max | 0.56 / 0.71 / 0.91 |

Change concentrates on active pit faces/benches, the tailings/processing area,
and the edges of pit lakes/ponds. Surrounding bushland is almost entirely
no-change (dry season).

---

## 14. Design decisions & trade-offs

| Decision | Reason | Trade-off |
|----------|--------|-----------|
| CVA over NDVI | No NIR band; CVA uses all 3 available bands | Not vegetation-specific |
| Reflectance (÷10000) | Physically comparable differences | Assumes L2A scaling |
| median/MAD threshold | Robust to outliers; unsupervised; no training data needed | Single global threshold |
| 99.9th-pctile intensity cap | Makes per-polygon confidence spread across 0–1 | Slightly compresses the display |
| RRN off by default | Global threshold already handles the seam; RRN adds texture noise | Diagonal visible in the intensity picture |
| GeoPackage as the DB | SQLite + true geometry type, opens in QGIS and sqlite3, no server needed | Not PostGIS (fine for this scale) |
| Min-area 2000 m² | Removes single-pixel noise and sub-feature speckle | May drop very small genuine changes |
| Embedded PNG overlays in HTML | Self-contained, single portable file | ~6.5 MB HTML |
| Otsu not used | Histogram is unimodal; Otsu flags 45.75% (mostly illumination) | — |
| Mean/std not used | Mean dragged up by outliers; threshold shifts 0.003 when top 0.1% removed | — |

---

## 15. Extending the pipeline

- **Different dates or site:** add new `data/sentinel2_<date>/` folders and
  update `DATE_BEFORE` / `DATE_AFTER` in `config.py`.
- **More bands (e.g. add NIR for NDVI):** extend `BANDS` and `BAND_NAMES`; CVA
  scales to any number of bands automatically. Add an NDVI branch in
  `detect_change()`.
- **PostGIS instead of GeoPackage:** replace `gdf.to_file(GPKG_PATH, ...)` with
  `gdf.to_postgis("change_features", engine, ...)`.
- **Cloud masking:** add a mask step using the SCL band in Part 1 and fold it
  into `_valid_mask`.
- **Adaptive threshold:** enable `REMOVE_BACKGROUND` and/or replace the global
  `robust_threshold` with a local windowed version for scenes with strong
  illumination gradients.

---

## 16. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `ModuleNotFoundError: rasterio` | Activate the venv: `source .venv/bin/activate` |
| `ValueError: Grid mismatch` | Inputs are not co-registered; re-clip to a common grid |
| `RasterioIOError: sentinel2_*_stack.tif: No such file` | Run `python src/data_preparation.py` first before the threshold scripts |
| `scipy` import error | Only needed for RRN/diagnostics: `pip install scipy` |
| Change % is ~50% | Threshold landed in the middle of the histogram — this is the Otsu failure; default median/MAD avoids it |
| `change_map.html` blank or no swipe | Open the file directly in a browser; it needs internet access for Leaflet/basemap CDNs |
| Confidence all = 1.0 | Intensity cap too low; the 99.9th-percentile cap (default) fixes this |

---

## 17. Limitations & future work

- **No cloud/shadow mask.** Any cloud or shadow edge registers as change. The
  AOI looks clear here. Adding an SCL-based mask is the main robustness upgrade.
- **Confidence is relative**, not a calibrated probability.
- **Single global threshold.** A spatially adaptive version would handle scenes
  with strong illumination gradients better.
- **Detector seam suppressed, not removed at source.** Full SAFE metadata would
  allow a proper MSK_DETFOO mask.
- **Two dates only.** Multi-temporal stacking would separate persistent change
  from transient noise and seasonal fluctuations.
- **No NIR.** NDVI and NDWI are not computable. Adding B08 would allow
  vegetation change to be separated from other land-surface change.
