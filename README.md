# Mongolia Prospection Toolkit

A safe-by-design toolkit for **non-invasive archaeological prospection and heritage monitoring** in **Mongolian steppe, valley, and mountain-foothill landscapes**.

This project is intentionally **not** a grave finder and is **not** optimized to locate any specific burial place or sacred tomb. It is built for:

- authorized cultural-heritage prospection,
- remote prioritization of landscape anomalies,
- manual review by trained researchers,
- field verification only under local permits and site-protection rules.

Exact coordinates are **redacted by default** unless you run in `authorized` mode.

## What is implemented now

Version `0.4.0` adds a full **Phase 4 reviewer workflow** on top of the Phase-3 STAC pipeline:

- automatic **context-layer generation** (`disturbance`, `confounder`, `water_proximity`, `forest`, `quality`) for local raster packs,
- **candidate clustering** so you can review zones instead of only raw tiles,
- **normalized red-zone import** with category filtering, buffering, simplification, and dissolve options,
- richer outputs: cluster JSON, cluster GeoJSON, markdown report, improved HTML review map.

## Repository layout

- `src/steppe_prospector/aoi.py` — AOI loading and tiling
- `src/steppe_prospector/stac_recipe.py` — STAC recipe loader
- `src/steppe_prospector/stac.py` — STAC search, asset selection, manifest building
- `src/steppe_prospector/ingest.py` — raster-pack preparation from STAC items
- `src/steppe_prospector/context_layers.py` — heuristic context-layer generation for local packs
- `src/steppe_prospector/clustering.py` — cluster aggregation for ranked candidate tiles
- `src/steppe_prospector/redzone_import.py` — normalization/import pipeline for external red-zone GeoJSON
- `src/steppe_prospector/datapack.py` — local raster pack loader
- `src/steppe_prospector/raster_features.py` — tile feature extraction
- `src/steppe_prospector/analysis.py` — end-to-end AOI workflow
- `src/steppe_prospector/outputs.py` — JSON / GeoJSON / HTML / markdown exports
- `src/steppe_prospector/demo.py` — synthetic demo dataset generator
- `config/default.toml` — scoring, tiling, context, and guardrail defaults
- `config/stac_recipe.template.toml` — editable STAC recipe template
- `config/stac_recipe.planetary_computer.landsat.toml` — ready-to-adapt example recipe
- `examples/mongolia_steppe_aoi.example.geojson` — generic example AOI
- `tests/` — pipeline, demo, STAC-ingestion, context-layer, and red-zone tests

## Install

Python 3.11+ is recommended.

```bash
pip install -e .
pip install -e .[dev]
pytest -q
```

## Quick start

### 1. Synthetic end-to-end demo

```bash
python -m steppe_prospector.cli demo ./demo_run --permit-mode public
```

This creates a demo raster pack plus:

- `raw_candidates.json`
- `ranked_candidates.json`
- `ranked_candidates.geojson`
- `ranked_clusters.json`
- `ranked_clusters.geojson`
- `review_map.html`
- `analysis_summary.json`
- `analysis_report.md`

### 2. STAC -> raster pack -> analysis in one command

```bash
python -m steppe_prospector.cli analyze-stac --aoi examples/mongolia_steppe_aoi.example.geojson --recipe config/stac_recipe.planetary_computer.landsat.toml --work-dir ./run_open_data --permit-mode public
```

### 3. Review-friendly overlap run on an existing raster pack

Use overlap when you want clusters that represent persistent candidate zones instead of isolated tiles.

```bash
python -m steppe_prospector.cli analyze --aoi path/to/aoi.geojson --data-pack path/to/data_pack --output-dir path/to/output --permit-mode public --tile-size-m 500 --tile-step-m 250 --cluster-distance-m 250
```

## PowerShell note

If you use PowerShell, prefer **one-line commands** or use PowerShell backticks for multiline continuation.

Example:

```powershell
python -m steppe_prospector.cli analyze-stac `
  --aoi examples/mongolia_steppe_aoi.example.geojson `
  --recipe config/stac_recipe.planetary_computer.landsat.toml `
  --work-dir .\run_open_data `
  --permit-mode public
```

## Core command groups

### Rank precomputed candidate features

```bash
python -m steppe_prospector.cli sample_input.json ranked_output.json --permit-mode public
```

### Search a STAC endpoint and save a selection manifest

```bash
python -m steppe_prospector.cli stac-search --aoi examples/mongolia_steppe_aoi.example.geojson --recipe config/stac_recipe.planetary_computer.landsat.toml --output ./run/selection_manifest.json
```

### Build a local raster pack from the STAC selection

```bash
python -m steppe_prospector.cli prepare-pack --aoi examples/mongolia_steppe_aoi.example.geojson --recipe config/stac_recipe.planetary_computer.landsat.toml --output-dir ./run/data_pack
```

### Build or refresh context layers for an existing pack

```bash
python -m steppe_prospector.cli build-context --data-pack ./run/data_pack
```

To overwrite existing context layers:

```bash
python -m steppe_prospector.cli build-context --data-pack ./run/data_pack --overwrite
```

### Analyze an existing raster pack

```bash
python -m steppe_prospector.cli analyze --aoi path/to/aoi.geojson --data-pack path/to/data_pack --output-dir path/to/output --permit-mode restricted --red-zones-geojson path/to/red_zones.geojson --context-mode auto
```

### Import and normalize red-zone GeoJSON

```bash
python -m steppe_prospector.cli import-red-zones --input path/to/raw_red_zones.geojson --output path/to/red_zones.geojson --name-field name --category-field category --dissolve-by category
```

## Raster-pack format

The analyzer expects a local directory like this:

```text
my_pack/
  dem.tif
  disturbance.tif          # optional; Phase 4 can generate this
  confounder.tif           # optional; Phase 4 can generate this
  water_proximity.tif      # optional; Phase 4 can generate this
  quality.tif              # optional; Phase 4 can generate this
  forest.tif               # optional; Phase 4 can generate this
  optical/
    2025-06-12_scene-1.tif
  sar/
    2025-06-14_scene-2.tif
  historical/
    1968-corona.tif
  selection_manifest.json
  pack_manifest.json
  context_manifest.json    # created after Phase-4 context build
```

The STAC builder produces the base pack. Phase 4 can then add the missing context layers automatically.

## What the feature engine computes per tile

- optical anomaly strength,
- SAR anomaly strength,
- DEM microrelief,
- enclosure-like compactness,
- linearity from edge segments,
- temporal persistence across optical / SAR stacks,
- historical support,
- contextual fit,
- modern disturbance penalty,
- natural confounder risk,
- data quality.

These feed the Mongolia-specific ranking model. Phase 4 then groups nearby ranked tiles into **review clusters**.

## Recommended workflow

1. Start with a small permitted AOI.
2. Run `stac-search` and inspect the selection manifest.
3. Run `prepare-pack`.
4. Run `build-context` if you want to inspect the generated context layers explicitly.
5. Run `analyze` with overlap (`tile_step_m < tile_size_m`) when you want useful clusters.
6. Review `ranked_clusters.json` first, then `ranked_candidates.json`.
7. Open `review_map.html` for spatial triage.
8. Read `analysis_report.md` and create a shortlist for manual follow-up.

## Guardrails

The project follows three rules:

- detect anomalies, not treasures,
- rank candidates, don’t assert discoveries,
- protect sensitive heritage by default.

Red-zone polygons can be loaded from GeoJSON. In the default config, red-zone candidates are only unredacted in `authorized` mode.

## Tests

```bash
pytest -q
```

The Phase-4 test suite covers:

- the original ranking pipeline,
- demo analysis,
- STAC ingestion,
- context-layer generation,
- cluster export,
- red-zone normalization/import.
