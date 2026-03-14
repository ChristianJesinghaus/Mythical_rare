# Phase 3 Guide: STAC Ingestion and Open-Data Workflow

This guide describes exactly what changed in the repository for the Phase-3 step.

## 1. New files to add

Add these new files to the repository:

- `src/steppe_prospector/stac_recipe.py`
- `src/steppe_prospector/stac.py`
- `src/steppe_prospector/ingest.py`
- `tests/test_stac_ingest.py`
- `config/stac_recipe.template.toml`
- `config/stac_recipe.planetary_computer.landsat.toml`
- `examples/mongolia_steppe_aoi.example.geojson`
- `PHASE3_STAC_INGEST_GUIDE.md`

## 2. Existing files changed

Update these existing files:

- `src/steppe_prospector/cli.py`
- `README.md`
- `MONGOLIA_PROSPECTION_BLUEPRINT.md`
- `pyproject.toml`

## 3. What the new code does

### `stac_recipe.py`
Loads TOML recipes that define:

- STAC endpoint,
- optional HREF signing mode,
- target grid resolution,
- optical/SAR/DEM/historical series recipes,
- asset-group alias rules,
- client-side property filters.

### `stac.py`
Adds:

- a generic STAC `/search` client,
- pagination support via `rel=next`,
- client-side filtering and sorting,
- asset selection using key names, titles, or `eo:bands` metadata,
- JSON-serializable selection manifests,
- optional Planetary Computer HREF signing helper.

### `ingest.py`
Adds:

- AOI target-grid creation,
- AOI crop + reprojection,
- NDVI generation from optical STAC assets,
- single-band DEM/SAR/historical ingestion,
- local raster-pack writing,
- quality-layer generation,
- manifest export.

## 4. New CLI commands

After installing the package, you can use:

```bash
python -m steppe_prospector.cli stac-search --aoi ... --recipe ... --output ...
python -m steppe_prospector.cli prepare-pack --aoi ... --recipe ... --output-dir ...
python -m steppe_prospector.cli analyze-stac --aoi ... --recipe ... --work-dir ...
```

## 5. Minimum working flow

### Step A — install

```bash
pip install -e .
```

### Step B — run the tests

```bash
pytest -q
```

### Step C — edit the recipe

Start from:

- `config/stac_recipe.planetary_computer.landsat.toml`

Adapt:

- `datetime`
- `max_items`
- `eo:cloud_cover` threshold
- optional `output_crs`
- later, optional SAR and historical sections

### Step D — choose an AOI

Use the example file as a template:

- `examples/mongolia_steppe_aoi.example.geojson`

### Step E — run the end-to-end command

```bash
python -m steppe_prospector.cli analyze-stac \
  --aoi examples/mongolia_steppe_aoi.example.geojson \
  --recipe config/stac_recipe.planetary_computer.landsat.toml \
  --work-dir ./run_open_data \
  --permit-mode public
```

## 6. What is still missing

This phase is useful and working, but not complete.

Still missing:

- official Mongolia protection / red-zone layers,
- provider-specific authentication beyond public/pre-signed URLs and Planetary Computer HREF signing,
- richer optical derivations beyond NDVI,
- historical-image recipes for declassified archives,
- automatic forest / hydrology / disturbance / confounder layers,
- browser review workstation,
- calibration on a permitted Mongolian validation AOI.

## 7. Practical next file to build after this phase

The next highest-value file is probably:

- `src/steppe_prospector/context_layers.py`

Its job should be to create:

- `water_proximity.tif`
- `forest.tif`
- `disturbance.tif`
- `confounder.tif`

from openly available land-cover and hydrography sources.
