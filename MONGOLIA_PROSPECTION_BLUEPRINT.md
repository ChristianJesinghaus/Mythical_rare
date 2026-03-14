# Blueprint: Mongolia Steppe Prospection Tool

## 1. Product goal

Build a remote-sensing tool that helps an authorized researcher review **possible archaeological landscape anomalies in Mongolia** without exposing sensitive heritage locations to casual use.

The product should:

- accept a user-defined AOI,
- ingest open satellite and terrain data,
- compute Mongolia-appropriate features,
- generate and rank candidates,
- redact exact coordinates unless permissions are present,
- support manual review and later field verification.

## 2. Current implementation status

### Already implemented in the repository

- AOI loading from GeoJSON
- AOI tiling in local metric CRS
- local raster-pack ingestion
- optical / SAR / DEM / historical tile feature extraction
- Mongolia-specific candidate scoring
- red-zone-aware redaction and withholding
- JSON + GeoJSON + HTML review export
- synthetic end-to-end demo pack and tests
- STAC recipe parsing
- live STAC item search and selection manifest export
- automatic raster-pack preparation from selected STAC assets
- optional Planetary Computer HREF signing for asset access
- end-to-end `analyze-stac` CLI orchestration

### Implemented, but still narrow

- optical STAC ingestion currently derives **NDVI** only
- SAR / DEM / historical ingestion currently supports **single-band** outputs
- provider auth beyond public or pre-signed URLs is still limited
- no official Mongolia heritage/protection layers are bundled yet

### Not yet implemented

- official protected-area / heritage-zone datasets
- reviewer labeling loop
- calibration against a permitted validation corpus
- dedicated browser workstation
- richer context layers such as water access, forest cover, and disturbance surfaces built automatically from open data

## 3. What the tool should optimize for in Mongolia

The first serious deployment version should focus on landscapes where open remote sensing has the best signal-to-noise ratio:

- open **steppe / semi-arid plains**,
- **river valleys and terraces**,
- **mountain foothills** with visible topographic structure.

The first version should explicitly **down-weight**:

- dense forest,
- unstable dune or sand-cover zones,
- zones with poor high-resolution imagery,
- sacred / protected / funerary landscapes lacking permits.

## 4. Detection philosophy

The tool should never directly output “archaeological site confirmed”.

It should output:

- a **candidate score**,
- a **confidence band**,
- an **evidence trace** explaining why the candidate was ranked,
- a **sensitivity status** that controls whether coordinates are shown.

## 5. System architecture

### 5.1 AOI manager

Inputs:

- polygon AOI,
- user role / permission mode,
- research objective.

Responsibilities:

- tile AOI into processing units,
- intersect AOI with red-zone layers,
- block or blur high-sensitivity outputs,
- attach provenance metadata.

### 5.2 Data ingestion layer

Implemented now:

- local raster packs with:
  - optical time series,
  - SAR time series,
  - DEM,
  - historical imagery,
  - optional disturbance / confounder / water / forest / quality layers.
- STAC recipe loader with:
  - endpoint selection,
  - asset-group rules,
  - client-side filters,
  - target grid configuration,
  - optional Planetary Computer asset signing.
- pack builder with:
  - STAC item selection manifests,
  - AOI crop + reprojection,
  - NDVI derivation for optical scenes,
  - single-band ingestion for DEM / SAR / historical layers,
  - local raster-pack export.

Planned providers / upgrades:

- Copernicus Data Space with provider-specific auth,
- openEO back-end,
- optional Google Earth Engine for research deployments,
- USGS EarthExplorer / declassified imagery catalogs,
- additional derived context layers.

### 5.3 Feature engine

Implemented per tile:

- spectral anomaly features,
- SAR contrast features,
- local DEM microrelief,
- enclosure-like compactness,
- line-segment linearity,
- multitemporal persistence,
- historical support,
- disturbance and confounder penalties,
- contextual fit.

### 5.4 Candidate generator

Current strategy:

1. tile the AOI,
2. compute anomaly features,
3. score candidates with landscape-specific weights,
4. redact or withhold according to sensitivity and permission mode.

Planned upgrade:

- learned anomaly proposal stage,
- reviewer-in-the-loop calibration,
- landscape-specific retraining.

### 5.5 Review application

Implemented now:

- static HTML review map,
- redaction-aware GeoJSON,
- ranked JSON export.

Planned later:

- browser map,
- candidate cards,
- reviewer decisions,
- annotation storage,
- active-learning feedback.

## 6. Mongolia-specific scoring logic

A global model is a bad starting point. Use region presets.

### Preset A — Steppe monument / enclosure mode

High weight on:

- microrelief,
- enclosure regularity,
- linearity / ring-ness,
- historical persistence,
- contextual fit near terraces / passes / water access.

Penalty on:

- livestock tracks,
- modern vehicle scars,
- recent construction / mining,
- dune migration / wash features.

### Preset B — Valley settlement / route mode

High weight on:

- terrace-edge placement,
- repeated linear traces,
- soil / moisture anomaly persistence,
- relation to water and movement corridors.

Penalty on:

- recent irrigation,
- modern field edges,
- erosion gullies.

### Preset C — Mountain / forest caution mode

- reduce confidence by default,
- prioritize drone / LiDAR follow-up where permitted,
- require stronger multitemporal evidence.

## 7. Guardrails

This is a core feature, not a legal afterthought.

The tool should:

- mask or blur sensitive landscapes,
- never publish exact coordinates for potentially funerary or sacred candidates in public mode,
- require explicit authorization to unredact coordinates,
- log every export in production deployments,
- store provenance for every candidate,
- keep a “withheld” state for candidates that may need handoff to authorities rather than field visitation.

## 8. Proposed phases

### Phase 0 — Safe scope and architecture

Delivered:

- risk model,
- protected-output logic,
- starter codebase,
- synthetic ranking demo.

### Phase 1 — Offline scoring MVP

Delivered:

- ingest precomputed candidate features,
- score / rank / redact,
- export review-ready JSON / GeoJSON.

### Phase 2 — Offline AOI analysis on local raster packs

Delivered:

- AOI tiling,
- raster feature extraction,
- HTML review map,
- demo raster pack generator,
- end-to-end tests.

### Phase 3 — Real open-data ingestion

Partially delivered:

- STAC search,
- client-side item filtering,
- selection-manifest export,
- raster-pack building from live STAC asset HREFs,
- a combined `analyze-stac` command,
- Planetary Computer HREF signing support.

Still needed in this phase:

- provider-specific auth for non-public assets,
- richer optical derivations beyond NDVI,
- automatic disturbance / water / forest / confounder layers,
- declassified historical imagery recipes,
- robust retry / resume support for long runs.

### Phase 4 — Human review workstation

Next:

- browser map,
- candidate cards,
- review labels,
- redaction-aware export,
- reviewer notes.

### Phase 5 — Learning loop

Next:

- reviewer feedback dataset,
- landscape-specific retraining,
- calibration and error analysis.

## 9. Evaluation plan

Measure:

- precision@k for reviewer usefulness,
- false-positive classes by landscape,
- robustness by season,
- degradation in sand / forest / rugged terrain,
- redaction correctness,
- reproducibility of exported candidate sets.

## 10. Immediate next engineering targets

1. add Mongolia-specific protection layers and a red-zone builder,
2. add a second optical derivation recipe such as NDMI or SWIR contrast,
3. add optional historical-image recipes,
4. benchmark on a permitted reference AOI,
5. move HTML review into a richer browser UI.
