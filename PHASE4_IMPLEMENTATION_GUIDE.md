# Phase 4 implementation guide

This guide describes the Phase-4 additions on top of the Phase-3 repo.

## New files

Create these files under the repo root:

- `src/steppe_prospector/context_layers.py`
- `src/steppe_prospector/clustering.py`
- `src/steppe_prospector/redzone_import.py`
- `tests/test_phase4_context.py`
- `tests/test_phase4_redzones.py`
- `PHASE4_IMPLEMENTATION_GUIDE.md`

## Files updated

Replace or update these existing files:

- `src/steppe_prospector/analysis.py`
- `src/steppe_prospector/cli.py`
- `src/steppe_prospector/config.py`
- `src/steppe_prospector/outputs.py`
- `src/steppe_prospector/raster_features.py`
- `config/default.toml`
- `README.md`
- `MONGOLIA_PROSPECTION_BLUEPRINT.md`
- `pyproject.toml`

## What each new module does

### `context_layers.py`

Adds a local, provider-agnostic context-layer builder for raster packs.

It can create or refresh:

- `disturbance.tif`
- `confounder.tif`
- `water_proximity.tif`
- `forest.tif`
- `quality.tif`

It also writes `context_manifest.json` and updates `pack_manifest.json`.

### `clustering.py`

Groups nearby ranked candidate tiles into review clusters and computes:

- `cluster_id`
- `member_ids`
- `cluster_score`
- `dominant_landscape`
- `member_count`
- `area_ha`
- aggregated reasons, tags, red-zone names, and source dates

### `redzone_import.py`

Normalizes external red-zone GeoJSON files with options for:

- category include/exclude filters,
- point/line buffering,
- simplify,
- minimum area threshold,
- dissolve by name/category/all.

## New CLI commands

### Build context layers

```bash
python -m steppe_prospector.cli build-context --data-pack ./run/data_pack
```

To overwrite existing context layers:

```bash
python -m steppe_prospector.cli build-context --data-pack ./run/data_pack --overwrite
```

### Import red zones

```bash
python -m steppe_prospector.cli import-red-zones --input ./raw_red_zones.geojson --output ./red_zones.geojson --name-field name --category-field category --dissolve-by category
```

## Updated analysis workflow

### 1. Search STAC items

```bash
python -m steppe_prospector.cli stac-search --aoi examples/mongolia_steppe_aoi.example.geojson --recipe config/stac_recipe.planetary_computer.landsat.toml --output ./run/selection_manifest.json
```

### 2. Prepare a pack and auto-build missing context

```bash
python -m steppe_prospector.cli prepare-pack --aoi examples/mongolia_steppe_aoi.example.geojson --recipe config/stac_recipe.planetary_computer.landsat.toml --output-dir ./run/data_pack --context-mode auto
```

### 3. Analyze with overlap so clusters become useful

```bash
python -m steppe_prospector.cli analyze --aoi examples/mongolia_steppe_aoi.example.geojson --data-pack ./run/data_pack --output-dir ./run/analysis_overlap --permit-mode public --tile-size-m 500 --tile-step-m 250 --cluster-distance-m 250
```

### 4. Review outputs

Look at these files first:

- `ranked_clusters.json`
- `ranked_clusters.geojson`
- `review_map.html`
- `analysis_report.md`

## What still remains after Phase 4

Phase 4 makes the repo much more useful, but a few high-value pieces still remain:

- official Mongolia protected-area / heritage-zone layers,
- stronger multi-index optical recipes,
- stronger SAR recipes,
- reviewer feedback capture and active learning,
- a dedicated interactive web review app.
