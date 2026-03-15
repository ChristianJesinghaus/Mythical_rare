from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio

from steppe_prospector.aoi import load_aoi
from steppe_prospector.analysis import AOIAnalyzer
from steppe_prospector.config import load_settings
from steppe_prospector.context_layers import build_context_layers
from steppe_prospector.datapack import LocalRasterPack
from steppe_prospector.demo import create_demo_dataset
from steppe_prospector.guardrails import load_red_zones_geojson
from steppe_prospector.models import PermitMode
from steppe_prospector.outputs import write_analysis_bundle


def test_build_context_layers_recreates_missing_files_and_analysis_uses_them(tmp_path: Path) -> None:
    assets = create_demo_dataset(tmp_path)
    pack_dir = assets["pack_dir"]

    for name in ["disturbance.tif", "confounder.tif", "water_proximity.tif", "forest.tif", "quality.tif"]:
        path = pack_dir / name
        assert path.exists()
        path.unlink()

    settings = load_settings()
    context = build_context_layers(pack_dir, settings.context_layers)

    assert context.context_manifest is not None and context.context_manifest.exists()
    assert (pack_dir / "disturbance.tif").exists()
    assert (pack_dir / "confounder.tif").exists()
    assert (pack_dir / "water_proximity.tif").exists()
    assert (pack_dir / "forest.tif").exists()
    assert (pack_dir / "quality.tif").exists()

    with rasterio.open(pack_dir / "water_proximity.tif") as src:
        arr = src.read(1).astype("float32")
        nodata = src.nodata
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)
        finite = arr[np.isfinite(arr)]
        assert finite.size > 0
        assert float(np.nanmin(finite)) >= 0.0
        assert float(np.nanmax(finite)) <= 1.0

    analyzer = AOIAnalyzer(settings=settings, red_zones=load_red_zones_geojson(assets["red_zones"]))
    result = analyzer.analyze(
        aoi=load_aoi(assets["aoi"]),
        pack=LocalRasterPack.from_directory(pack_dir),
        permit_mode=PermitMode.PUBLIC,
    )
    assert result.ranked


def test_authorized_overlap_run_writes_cluster_outputs(tmp_path: Path) -> None:
    assets = create_demo_dataset(tmp_path)
    red_zones = load_red_zones_geojson(assets["red_zones"])
    analyzer = AOIAnalyzer(red_zones=red_zones)
    aoi = load_aoi(assets["aoi"])

    result = analyzer.analyze(
        aoi=aoi,
        pack=LocalRasterPack.from_directory(assets["pack_dir"]),
        permit_mode=PermitMode.AUTHORIZED,
        tile_size_m=500,
        tile_step_m=250,
    )

    assert result.clusters
    assert len(result.clusters) < len(result.ranked)
    assert result.clusters[0].member_count >= 2

    outputs = write_analysis_bundle(tmp_path / "bundle", aoi, result, red_zones=red_zones)
    clusters = json.loads(Path(outputs["clusters_json"]).read_text(encoding="utf-8"))
    assert clusters
    geojson = json.loads(Path(outputs["clusters_geojson"]).read_text(encoding="utf-8"))
    assert any(feature["geometry"]["type"] == "Polygon" for feature in geojson["features"])
    assert Path(outputs["report"]).exists()
