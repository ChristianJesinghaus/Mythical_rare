from __future__ import annotations

import json
from pathlib import Path

from steppe_prospector.analysis import AOIAnalyzer
from steppe_prospector.aoi import load_aoi
from steppe_prospector.datapack import LocalRasterPack
from steppe_prospector.demo import create_demo_dataset
from steppe_prospector.guardrails import load_red_zones_geojson
from steppe_prospector.models import PermitMode
from steppe_prospector.outputs import ranked_geojson, write_analysis_bundle


def test_demo_analysis_public_redacts_and_filters_sensitive(tmp_path: Path) -> None:
    assets = create_demo_dataset(tmp_path)
    analyzer = AOIAnalyzer(red_zones=load_red_zones_geojson(assets["red_zones"]))
    result = analyzer.analyze(
        aoi=load_aoi(assets["aoi"]),
        pack=LocalRasterPack.from_directory(assets["pack_dir"]),
        permit_mode=PermitMode.PUBLIC,
    )

    assert result.ranked, "Expected at least one ranked candidate"
    assert all(item.exact_location is None for item in result.ranked)
    assert all(item.public_location is not None for item in result.ranked)
    assert all(item.sensitivity != "sensitive" for item in result.ranked)
    assert result.ranked[0].adjusted_score >= 0.3

    geojson = ranked_geojson(result)
    assert geojson["features"]
    assert all(feature["geometry"]["type"] == "Point" for feature in geojson["features"])


def test_demo_analysis_authorized_exports_polygons_and_sensitive_hits(tmp_path: Path) -> None:
    assets = create_demo_dataset(tmp_path)
    red_zones = load_red_zones_geojson(assets["red_zones"])
    analyzer = AOIAnalyzer(red_zones=red_zones)
    aoi = load_aoi(assets["aoi"])
    result = analyzer.analyze(
        aoi=aoi,
        pack=LocalRasterPack.from_directory(assets["pack_dir"]),
        permit_mode=PermitMode.AUTHORIZED,
    )

    assert result.ranked
    assert any(item.sensitivity == "sensitive" for item in result.ranked)
    assert all(item.exact_location is not None for item in result.ranked)

    outputs = write_analysis_bundle(tmp_path / "bundle", aoi, result, red_zones=red_zones)
    geojson = json.loads(Path(outputs["geojson"]).read_text(encoding="utf-8"))
    assert any(feature["geometry"]["type"] == "Polygon" for feature in geojson["features"])
    assert Path(outputs["review_map"]).exists()
