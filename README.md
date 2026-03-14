#Totally not AI Gen. Readme:
# Mongolia Prospection MVP

A safe-by-design starter project for a **non-invasive archaeological prospection and heritage-monitoring tool** optimized for **Mongolian steppe and mountain-foothill landscapes**.

## Scope

This project is intentionally **not** a "grave finder" and is **not** optimized to locate any specific burial place or sacred tomb. It is designed for:

- authorized cultural-heritage prospection,
- remote prioritization of landscape anomalies,
- manual review by trained researchers,
- field verification only under local permits and site-protection rules.

The code and blueprint assume that sensitive candidate locations are **redacted by default** unless the user has the appropriate authorization.

## What this MVP does

This repository does **not** download real satellite data yet. Instead, it gives you the core project structure for the first serious build phase:

1. a Mongolia-specific scoring model,
2. a protected-area / sacred-site guardrail layer,
3. a candidate-ranking pipeline,
4. a CLI that turns extracted features into a redacted review list,
5. a written build plan for the next phases.

That makes it suitable as a first implementation target before wiring in STAC, openEO, Earth Engine, PostGIS, or a browser UI.

## Suggested data stack for later integration

- **Sentinel-2** for multispectral and seasonal comparison
- **Sentinel-1** for SAR / all-weather surface signals
- **Copernicus DEM GLO-30** for terrain derivatives
- **USGS declassified imagery** (CORONA / KH-series) for historical comparison
- optional **drone orthomosaics / local LiDAR** for licensed validation zones

## Repository layout

- `MONGOLIA_PROSPECTION_BLUEPRINT.md` — system plan and phased roadmap
- `config/default.toml` — weights and guardrail defaults
- `src/steppe_prospector/` — starter code
- `tests/` — minimal tests
- `sample_input.json` — synthetic example input for the CLI

## Quickstart

Python 3.11+ is recommended.

```bash
python -m steppe_prospector.cli sample_input.json ranked_output.json
```

The output is a ranked JSON review list with:

- candidate scores,
- confidence classes,
- explanation strings,
- coordinate redaction according to guardrails.

## Next engineering steps

1. Implement a real `AOIDataProvider` using STAC or openEO.
2. Add raster feature extraction per 256×256 m or 512×512 m tile.
3. Replace synthetic red-zone rules with official protected-area and heritage-zone polygons.
4. Add a review UI (MapLibre + deck.gl or similar).
5. Add active-learning feedback from reviewer decisions.

## Safety model

The repository enforces three principles:

- **detect anomalies, not treasures**
- **rank candidates, don’t assert discoveries**
- **protect sensitive heritage by default**
