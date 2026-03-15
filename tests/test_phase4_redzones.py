from __future__ import annotations

import json
from pathlib import Path

from steppe_prospector.redzone_import import RedZoneImportOptions, import_red_zones_geojson


RAW_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[91.0, 47.0], [91.02, 47.0], [91.02, 47.02], [91.0, 47.02], [91.0, 47.0]]],
            },
            "properties": {"title": "Protected core", "kind": "protected"},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[91.03, 47.0], [91.04, 47.0], [91.04, 47.01], [91.03, 47.01], [91.03, 47.0]]],
            },
            "properties": {"title": "Tourism buffer", "kind": "tourism"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [91.05, 47.01]},
            "properties": {"title": "Restricted point", "kind": "protected"},
        },
    ],
}


def test_import_red_zones_filters_categories_and_dissolves(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw_red_zones.geojson"
    raw_path.write_text(json.dumps(RAW_GEOJSON, indent=2), encoding="utf-8")

    output_path = tmp_path / "normalized_red_zones.geojson"
    summary_path = tmp_path / "red_zone_summary.json"
    summary = import_red_zones_geojson(
        raw_path,
        output_path,
        options=RedZoneImportOptions(
            name_field="title",
            category_field="kind",
            include_categories=["protected"],
            point_buffer_m=250.0,
            dissolve_by="category",
        ),
        summary_path=summary_path,
    )

    assert summary.kept_features == 2
    assert summary.dissolved_features == 1
    assert output_path.exists()
    assert summary_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(payload["features"]) == 1
    feature = payload["features"][0]
    assert feature["properties"]["name"] == "protected"
    assert feature["properties"]["source_count"] == 2
    assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
