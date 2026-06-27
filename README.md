# Sentinel-2 Change Analysis — Open-Pit Mine, Zambia

A geospatial pipeline that detects land-surface change between two Sentinel-2
acquisitions (**2023-08-12** → **2023-09-02**) over an open-pit mining site in
Zambia. It stores results in a spatial database and produces static and
interactive figures.

| Part | Stage | Module | Output |
|------|-------|--------|--------|
| 1 | Data preparation | [`src/data_preparation.py`](src/data_preparation.py) | `data/processed/sentinel2_*_stack.tif` |
| 2 | Change detection | [`src/change_detection.py`](src/change_detection.py) | `change_map.tif`, `change_binary.tif` |
| 3 | Feature extraction + storage | [`src/feature_extraction.py`](src/feature_extraction.py) | `changes.gpkg` (SQLite/GeoPackage) |
| 4 | Visualisation | [`src/visualize.py`](src/visualize.py) | `outputs/change_overview.png`, `change_map.html` |
| 5 | Analysis & interpretation | [`report.md`](report.md) | — |

Three extra scripts show **why CVA was chosen** over other threshold methods:

| Script | What it shows | Output |
|--------|--------------|--------|
| [`src/otsu_threshold.py`](src/otsu_threshold.py) | Otsu flags 45.75% — fails on unimodal histogram | `outputs/otsu_threshold.png` |
| [`src/mean_std_threshold.py`](src/mean_std_threshold.py) | Mean/std shifts when outliers change | `outputs/mean_std_threshold.png` |
| [`src/threshold_comparison.py`](src/threshold_comparison.py) | All three methods on one figure | `outputs/threshold_comparison.png` |

Full engineering reference: [DOCUMENTATION.md](DOCUMENTATION.md)

---

## How to run

```bash
# 1. Create environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Run the full pipeline (Parts 1–4)
python src/pipeline.py

# 3. Run the threshold comparison scripts (optional)
python src/otsu_threshold.py
python src/mean_std_threshold.py
python src/threshold_comparison.py
```

Note: the threshold scripts need the stacks from Part 1. If you skip the full
pipeline, run `python src/data_preparation.py` first.

Each stage can also be run on its own. All paths and parameters are in
[`src/config.py`](src/config.py).

### Inputs expected

```
inputs/
  aoi.geojson                       # Area of interest (WGS84)
  example_change_detection.py       # Provided baseline algorithm
data/
  sentinel2_20230812/  B02.tif B03.tif B04.tif   # Blue, Green, Red (date 1)
  sentinel2_20230902/  B02.tif B03.tif B04.tif   # date 2
```

### Outputs produced

```
data/processed/
  sentinel2_20230812_stack.tif      # 3-band stack, date 1
  sentinel2_20230902_stack.tif      # 3-band stack, date 2
  change_map.tif                    # continuous change intensity (float32, 0-1)
  change_binary.tif                 # change / no-change mask (uint8)
  change_map_example.tif            # provided baseline, for comparison
  changes.gpkg                      # SQLite/GeoPackage DB
outputs/
  change_overview.png               # 4-panel static figure
  change_map.html                   # interactive Folium map with swipe slider
  artifact_diagnostics.png          # seam artifact analysis
  otsu_threshold.png                # Otsu failure demonstration
  mean_std_threshold.png            # mean/std fragility demonstration
  threshold_comparison.png          # all three methods side by side
```

---

## Approach

### Part 1 — Data preparation
Reads Bands 2/3/4 for both dates. Before stacking, checks that CRS, affine
transform and dimensions are identical across all six rasters (EPSG:32735 / UTM
35S, 10 m, 1673×1597). Both dates must be on the same grid — co-registration is
required for change detection and is verified here. Each date is written as a
3-band stack GeoTIFF.

### Part 2 — Change detection
Method: **Change Vector Analysis (CVA)**

1. Convert DN → reflectance (`DN / 10000`).
2. Per-pixel change magnitude = Euclidean distance between the after and before
   reflectance vectors across all 3 bands.
3. Binary mask: flag a pixel as changed if its magnitude exceeds
   `median + 3 · 1.4826 · MAD` of all valid pixel magnitudes.

Pixels with DN = 0 in any band of either date are excluded.

### Why CVA — not Otsu or mean/std

The change magnitude histogram has one hump (unimodal), not two. Otsu needs two
humps to find a split point. Without them it picks the middle of the single hump
and flags **45.75%** of the scene — nearly half the image.

Mean/std puts the threshold at `mean + 3*std`. The problem is that the mean gets
pulled upward by the pixels that have genuine change (the outliers). By removing just
the top 0.1% of pixels and the threshold shifts by 0.003 which is not stable.

Median/MAD is not affected by outliers. The threshold stays at the true
background noise level and flags only **0.88%** of the scene — consistent with
mining activity over three weeks.

| Method | % flagged | Verdict                            |
|--------|-----------|------------------------------------|
| Otsu | 45.75% | Failed — needs two histogram peaks |
| Mean + 3·std | 0.82% | Unreliable — shifts with outliers  |
| CVA (median + 3·MAD) | 0.88% | Better — anchored to background    |

### Why not NDVI?
Only Blue, Green and Red bands are available. NDVI requires the NIR band (B08),
which is not in this dataset. CVA uses all three available bands simultaneously,
so it captures brightness and colour change.

### Part 3 — Feature extraction & storage
The binary mask is polygonised (`rasterio.features.shapes`). Polygons smaller
than 2000 m² are dropped as speckle. Each polygon gets a `confidence` score =
mean change intensity of the pixels inside it.

Features are written to **`changes.gpkg`**, a GeoPackage file. GeoPackage is a
SQLite database with a true geometry column — it opens in QGIS, GeoPandas, the
`sqlite3` CLI, or any SpatiaLite tool.

Table `change_features`:

| id | date_before | date_after | area_m2 | confidence | geom |
|----|-------------|------------|---------|------------|------|
| 1  | 2023-08-12  | 2023-09-02 | …       | 0–1        | POLYGON (EPSG:32735) |

```bash
sqlite3 data/processed/changes.gpkg \
  "SELECT id, area_m2, confidence FROM change_features ORDER BY area_m2 DESC LIMIT 5;"
```

### Part 4 — Visualisation
`change_overview.png` — 4-panel static figure: before RGB, after RGB, change
intensity map, detected polygons on the AOI.

`change_map.html` — interactive Folium map with a **before/after swipe slider**,
change polygons shaded by confidence, and a layer toggle control.

---

## Artifact — diagonal detector seam
The intensity map has a faint diagonal stripe. This is a Sentinel-2
detector-module seam: adjacent modules image the same ground at slightly
different angles so their brightness offset changes between acquisitions,
creating a stripe in the difference image.

It does not affect results. The stripe has a magnitude of ~0.047 reflectance
units; the threshold is 0.117 (2.5× higher), so the stripe never enters the
binary detections or the polygon output. Run `python src/artifact_diagnostics.py`
for the full analysis.

A Gaussian background subtraction step is available via
`config.REMOVE_BACKGROUND = True` to flatten the stripe visually, but it also
lowers the detection threshold enough to add false positives on vegetation
texture — off by default.

## Assumptions
- Bands are Sentinel-2 L2A surface reflectance scaled by 10000.
- DN = 0 means nodata.
- Both scenes are co-registered (confirmed in Part 1).
- "Confidence" is a relative score, not a calibrated probability.

## Project layout
```
src/            pipeline modules, config, and threshold comparison scripts
inputs/         AOI geojson and provided baseline algorithm
data/           raw input scenes and generated processed outputs
outputs/        PNG figures and interactive HTML map
report.md       Part 5 — method, results, interpretation
DOCUMENTATION.md  Full engineering reference
```
