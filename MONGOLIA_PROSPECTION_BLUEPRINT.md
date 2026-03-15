# Mongolia Prospection Blueprint

## Scope

This project is a **non-invasive, authorization-based prospection and review tool** for Mongolian archaeological landscapes. It is designed to identify and prioritize **anomalous landscape zones** for expert review, not to claim discoveries or to target a specific grave or sacred tomb.

## Product goal

Build a workflow that lets a researcher:

1. define an AOI,
2. collect open remote-sensing data,
3. derive a local raster pack,
4. compute anomaly evidence tile by tile,
5. group nearby hits into stable candidate zones,
6. review those zones under redaction-aware guardrails.

## Architecture phases

### Phase 1: scoring MVP

- flat candidate schema,
- simple ranking model,
- basic redaction and permit modes.

### Phase 2: local raster-pack analyzer

- AOI tiling,
- DEM / optical / SAR / historical feature extraction,
- JSON / GeoJSON / HTML outputs.

### Phase 3: open-data ingestion

- STAC search and item selection,
- automatic raster-pack creation,
- provider-specific HREF signing where needed.

### Phase 4: reviewer workflow

- automatic context-layer generation,
- candidate clustering,
- red-zone normalization/import,
- richer review outputs.

## Phase 4 details

### 1. Context layers

Generate reviewer-friendly risk/context layers from the raster pack when they are missing:

- `disturbance.tif` — heuristics for modern linear disturbance and abrupt edge/variance patterns,
- `confounder.tif` — ruggedness / slope / concavity proxy for natural false positives,
- `water_proximity.tif` — valley-floor / wetness-distance proxy,
- `forest.tif` — optical vegetation proxy,
- `quality.tif` — finite-data coverage proxy.

These layers improve `contextual_fit`, `modern_disturbance`, `natural_confounder_risk`, and `data_quality`.

### 2. Candidate clustering

Tiles are useful for extraction, but clusters are better for human review.

Phase 4 introduces:

- spatial grouping of nearby ranked tiles,
- deterministic cluster IDs,
- aggregated cluster score and reasons,
- cluster area and member count,
- cluster-level GeoJSON/JSON export.

### 3. Red-zone import

External protected-area or heritage GeoJSON often arrives in inconsistent form.

Phase 4 normalizes it by:

- choosing a stable `name` field,
- optional category filtering,
- optional point/line buffering,
- optional simplify,
- optional dissolve by name/category/all,
- standardized `FeatureCollection` export.

### 4. Review outputs

Each analysis bundle now includes:

- ranked candidate tiles,
- ranked candidate clusters,
- HTML map with AOI, clusters, candidate tiles, and red zones,
- markdown analysis report,
- summary JSON.

## Recommended field workflow

1. Choose a permitted AOI.
2. Run `stac-search`.
3. Run `prepare-pack`.
4. Build or refresh context layers.
5. Run `analyze` with overlap for cluster-friendly review.
6. Review clusters first, tiles second.
7. Only escalate to field follow-up under valid permissions.

## Phase 5 candidates

Natural next extensions after Phase 4:

- additional optical indices beyond NDVI,
- stronger SAR products and time-series recipes,
- official Mongolia protection layers,
- reviewer labeling and feedback capture,
- active-learning loop,
- richer browser review app.
