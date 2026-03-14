# Mongolia Prospection Toolkit

A safe-by-design starter project for a **non-invasive archaeological prospection and heritage-monitoring workflow** optimized for **Mongolian steppe and mountain-foothill landscapes**.

This project is intentionally **not** a grave finder and is **not** optimized to locate any specific burial place or sacred tomb. It is designed for:

- authorized cultural-heritage prospection,
- remote prioritization of landscape anomalies,
- manual review by trained researchers,
- field verification only under local permits and site-protection rules.

Exact coordinates are **redacted by default** unless the user runs in `authorized` mode.

## What is implemented now

Version `0.3.0` adds a first **open-data ingestion layer** on top of the earlier scoring MVP and local raster-pack analyzer.

You can now:

1. define an AOI as GeoJSON,
2. query a STAC endpoint for optical / DEM / optional SAR items,
3. select usable assets per item with client-side filtering,
4. build a local raster pack automatically,
5. run the analyzer on that pack,
6. export redaction-aware JSON, GeoJSON, and an HTML review map.

## Repository layout

- `src/steppe_prospector/aoi.py` — AOI loading and tiling
- `src/steppe_prospector/stac_recipe.py` — STAC recipe loader
- `src/steppe_prospector/stac.py` — STAC search, asset selection, manifest building
- `src/steppe_prospector/ingest.py` — raster-pack preparation from STAC items
- `src/steppe_prospector/datapack.py` — local raster pack loader
- `src/steppe_prospector/raster_features.py` — tile feature extraction
- `src/steppe_prospector/analysis.py` — end-to-end AOI workflow
- `src/steppe_prospector/outputs.py` — JSON / GeoJSON / HTML exports
- `src/steppe_prospector/demo.py` — synthetic demo dataset generator
- `config/default.toml` — scoring, tiling, feature, and guardrail defaults
- `config/stac_recipe.template.toml` — editable STAC recipe template
- `config/stac_recipe.planetary_computer.landsat.toml` — ready-to-adapt example recipe
- `examples/mongolia_steppe_aoi.example.geojson` — generic example AOI
- `tests/` — pipeline, demo, and STAC-ingestion tests

## Install

Python 3.11+ is recommended.

```bash
pip install -e .
```

## Core command groups

### 1. Legacy rank-only mode

This keeps the original MVP behavior for precomputed feature JSON:

```bash
python -m steppe_prospector.cli sample_input.json ranked_output.json --permit-mode public
```

### 2. Full AOI analysis on an existing local raster pack

```bash
python -m steppe_prospector.cli analyze \
  --aoi path/to/aoi.geojson \
  --data-pack path/to/my_pack \
  --output-dir path/to/output \
  --permit-mode restricted \
  --red-zones-geojson path/to/red_zones.geojson
```

### 3. Search a STAC endpoint and save a selection manifest

```bash
python -m steppe_prospector.cli stac-search \
  --aoi examples/mongolia_steppe_aoi.example.geojson \
  --recipe config/stac_recipe.planetary_computer.landsat.toml \
  --output ./run/selection_manifest.json
```

### 4. Build a local raster pack from the STAC selection

```bash
python -m steppe_prospector.cli prepare-pack \
  --aoi examples/mongolia_steppe_aoi.example.geojson \
  --recipe config/stac_recipe.planetary_computer.landsat.toml \
  --output-dir ./run/data_pack
```

Or, if you already have a selection manifest:

```bash
python -m steppe_prospector.cli prepare-pack \
  --aoi examples/mongolia_steppe_aoi.example.geojson \
  --recipe config/stac_recipe.planetary_computer.landsat.toml \
  --selection-manifest ./run/selection_manifest.json \
  --output-dir ./run/data_pack
```

### 5. End-to-end STAC → raster pack → analysis

```bash
python -m steppe_prospector.cli analyze-stac \
  --aoi examples/mongolia_steppe_aoi.example.geojson \
  --recipe config/stac_recipe.planetary_computer.landsat.toml \
  --work-dir ./run_open_data \
  --permit-mode public
```

This creates:

- `./run_open_data/data_pack/selection_manifest.json`
- `./run_open_data/data_pack/pack_manifest.json`
- `./run_open_data/data_pack/dem.tif`
- `./run_open_data/data_pack/optical/*.tif`
- `./run_open_data/data_pack/quality.tif` (when optical or SAR outputs exist)
- `./run_open_data/analysis_outputs/raw_candidates.json`
- `./run_open_data/analysis_outputs/ranked_candidates.json`
- `./run_open_data/analysis_outputs/ranked_candidates.geojson`
- `./run_open_data/analysis_outputs/review_map.html`
- `./run_open_data/analysis_outputs/analysis_summary.json`

### 6. Generate and run the synthetic demo

```bash
python -m steppe_prospector.cli demo ./demo_run --permit-mode public
```

## STAC recipe format

Recipes are TOML files describing:

- the STAC endpoint,
- optional asset-URL signing mode,
- target grid resolution,
- one optical recipe,
- optional SAR recipe,
- one DEM recipe,
- optional historical recipe.

The current builder supports:

- `optical.output_kind = "ndvi"` using `asset_groups.red` + `asset_groups.nir`
- `sar.output_kind = "single-band"` using `asset_groups.primary`
- `dem.output_kind = "single-band"` using `asset_groups.primary`
- `historical.output_kind = "single-band"` using `asset_groups.primary`

### Example optical block

```toml
[optical]
enabled = true
collection = "landsat-c2-l2"
datetime = "2024-05-01T00:00:00Z/2024-09-30T23:59:59Z"
max_items = 6
search_limit = 60
output_kind = "ndvi"
sort_by = "eo:cloud_cover"
sort_ascending = true

[[optical.filters]]
property = "eo:cloud_cover"
lte = 25.0

[optical.asset_groups]
red = ["red"]
nir = ["nir08", "nir"]
```

## Local raster pack format

The analyzer still expects a local directory structured like this:

```text
my_pack/
  dem.tif
  disturbance.tif          # optional, normalized 0..1
  confounder.tif           # optional, normalized 0..1
  water_proximity.tif      # optional, normalized 0..1 (1 = favorable access)
  quality.tif              # optional, normalized 0..1
  forest.tif               # optional, binary/normalized forest cover
  optical/
    2025-06-12_scene-1.tif
  sar/
    2025-06-14_scene-2.tif
  historical/
    1968-corona.tif
```

The STAC builder now produces this format automatically for the layers it knows how to derive.

## What the feature engine currently computes

Per tile, the analyzer derives:

- optical anomaly strength,
- SAR anomaly strength,
- DEM microrelief,
- enclosure-like compactness,
- linearity from edge segments,
- temporal persistence across the optical / SAR stacks,
- historical support,
- contextual fit,
- modern disturbance penalty,
- natural confounder risk,
- data quality.

These signals feed the existing Mongolia-specific ranking model.

## Guardrails

The project enforces three principles:

- detect anomalies, not treasures,
- rank candidates, don’t assert discoveries,
- protect sensitive heritage by default.

Red-zone polygons can be loaded from GeoJSON. In the default config, red-zone candidates are only unredacted in `authorized` mode.

## What still needs to be built

The toolkit is now functional for:

- synthetic demo packs,
- local raster packs,
- basic STAC-driven pack generation when the STAC assets are public or pre-signed.

Still missing or incomplete:

1. provider-specific auth flows beyond the Planetary Computer HREF signer,
2. official protected-area / heritage-zone layers for Mongolia,
3. derived disturbance / forest / hydrology context layers from open data,
4. calibration against a permitted validation set in Mongolia,
5. reviewer feedback capture and active learning,
6. a dedicated browser review app instead of static HTML.

## Tests

```bash
pytest -q
```

The suite covers:

- the original scoring/redaction unit test,
- a public-mode end-to-end demo run,
- an authorized-mode demo export test,
- STAC item selection with asset matching,
- raster-pack generation from local STAC-like assets.
