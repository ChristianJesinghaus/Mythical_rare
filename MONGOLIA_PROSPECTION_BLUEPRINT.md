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

## 2. What the tool should optimize for in Mongolia

The first working version should focus on the landscapes where open remote sensing has the best signal-to-noise ratio:

- open **steppe / semi-arid plains**,
- **river valleys and terraces**,
- **mountain foothills** with visible topographic structure.

The first version should explicitly **down-weight**:

- dense forest,
- unstable dune or sand-cover zones,
- zones with poor high-resolution imagery,
- sacred / protected / funerary landscapes lacking permits.

## 3. Detection philosophy

The tool should never directly output “archaeological site confirmed”.

It should output:

- a **candidate score**,
- a **confidence band**,
- an **evidence trace** explaining why the candidate was ranked,
- a **sensitivity status** that controls whether coordinates are shown.

## 4. System architecture

### 4.1 AOI manager

Input:
- polygon AOI
- user role / permission mode
- research objective

Responsibilities:
- tile AOI into processing units
- intersect AOI with red-zone layers
- block or blur high-sensitivity outputs
- attach provenance metadata

### 4.2 Data ingestion layer

Planned providers:
- Copernicus Data Space / STAC
- openEO back-end
- optional Google Earth Engine for research deployments
- USGS EarthExplorer / declassified imagery catalogs

Data groups:
- Sentinel-2 L2A
- Sentinel-1 GRD / SAR
- Copernicus DEM
- historical imagery
- modern disturbance layers
- hydrology / land cover / slope context

### 4.3 Feature engine

Per tile or per candidate polygon, compute:

- spectral anomaly features
- SAR roughness / moisture contrast features
- terrain derivatives (slope, curvature, local relief)
- geometric regularity features
- multitemporal persistence
- historical persistence
- disturbance and confounder penalties

### 4.4 Candidate generator

Use a hybrid strategy:

1. rules to surface strong anomalies,
2. anomaly detection for unusual but unexplained patterns,
3. a ranking model that learns from reviewed examples.

### 4.5 Review application

Each candidate card should show:

- score
- redacted or exact location depending on permissions
- reasons for ranking
- quicklooks from multiple dates / modalities
- reviewer decision buttons:
  - dismiss
  - low priority
  - monitor
  - field-check (authorized)
  - sensitive / withhold

## 5. Mongolia-specific scoring logic

A global model is a bad starting point. Use region presets.

### Preset A — Steppe monument / enclosure mode

Useful when the surface is open and geometry is visible.

High weight on:
- microrelief
- enclosure regularity
- linearity / ring-ness
- historical persistence
- contextual fit near terraces / passes / water access

Penalty on:
- livestock tracks
- modern vehicle scars
- recent construction / mining
- dune migration / wash features

### Preset B — Valley settlement / route mode

High weight on:
- terrace-edge placement
- repeated linear traces
- soil / moisture anomaly persistence
- relation to water and movement corridors

Penalty on:
- recent irrigation
- modern field edges
- erosion gullies

### Preset C — Mountain / forest caution mode

Do not overclaim.

- reduce confidence by default
- prioritize drone / LiDAR follow-up where permitted
- require stronger multitemporal evidence

## 6. Guardrails

This is a core feature, not a legal afterthought.

The tool should:

- mask or blur sensitive landscapes,
- never publish exact coordinates for potentially funerary or sacred candidates in public mode,
- require explicit authorization to unredact coordinates,
- log every export,
- store provenance for every candidate,
- keep a “withheld” state for candidates that may need handoff to authorities rather than field visitation.

## 7. Proposed phases

### Phase 0 — Safe scope and architecture

Deliverables:
- risk model
- protected-area policy
- starter codebase
- synthetic end-to-end run

### Phase 1 — Offline scoring MVP

Deliverables:
- ingest precomputed candidate features
- score / rank / redact
- export review-ready JSON / GeoJSON

### Phase 2 — Real open-data ingestion

Deliverables:
- STAC search
- cloud masks
- terrain derivatives
- seasonal composites
- basic anomaly maps

### Phase 3 — Human review workstation

Deliverables:
- browser map
- candidate cards
- review labels
- redaction-aware export

### Phase 4 — Learning loop

Deliverables:
- reviewer feedback dataset
- landscape-specific retraining
- calibration and error analysis

## 8. Evaluation plan

Measure:

- precision@k for reviewer usefulness
- false-positive rate by landscape class
- agreement between reviewers
- sensitivity-redaction compliance
- recall against a permitted, non-sensitive validation set

The central KPI for the first version is:

> “Does this tool cut manual review time while keeping sensitive heritage protected?”

## 9. Recommended first pilot geography

Start outside the most sensitive sacred-core landscapes.

Best first pilot characteristics:
- open steppe or valley terrain,
- known but non-sensitive comparison data available,
- manageable AOI size,
- realistic field-verification path through local partners.

## 10. Immediate build order

1. keep the safe-by-design policy fixed,
2. wire in the scoring engine,
3. produce redacted ranked outputs,
4. then attach real remote-sensing ingestion,
5. only later add higher-resolution local validation workflows.
