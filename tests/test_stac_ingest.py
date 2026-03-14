from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from steppe_prospector.aoi import aoi_from_bbox
from steppe_prospector.ingest import prepare_raster_pack
from steppe_prospector.stac import STACSelectionManifest, SelectedAsset, SelectedItem, build_stac_selection
from steppe_prospector.stac_recipe import (
    FilterRule,
    STACClientConfig,
    STACRecipe,
    SeriesRecipe,
    TargetGridConfig,
)


def _write_test_raster(path: Path, array: np.ndarray, *, west: float = 90.0, north: float = 47.2, pixel_size: float = 0.002) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=array.shape[1],
        height=array.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(west, north, pixel_size, pixel_size),
        nodata=-9999.0,
    ) as dst:
        dst.write(array.astype("float32"), 1)


def test_build_stac_selection_matches_assets_and_filters(monkeypatch) -> None:
    recipe = STACRecipe(
        stac=STACClientConfig(endpoint="https://example.com/stac"),
        target=TargetGridConfig(),
        optical=SeriesRecipe(
            enabled=True,
            collection="demo-optical",
            datetime="2024-01-01T00:00:00Z/2024-12-31T23:59:59Z",
            max_items=2,
            search_limit=10,
            output_kind="ndvi",
            asset_groups={"red": ["red"], "nir": ["nir08", "nir"]},
            filters=[FilterRule(property="eo:cloud_cover", lte=20.0)],
            sort_by="eo:cloud_cover",
            sort_ascending=True,
        ),
    )

    raw_items = [
        {
            "id": "too-cloudy",
            "collection": "demo-optical",
            "properties": {"datetime": "2024-06-01T00:00:00Z", "eo:cloud_cover": 35.0},
            "assets": {
                "SR_B4": {"href": "file:///tmp/red.tif", "eo:bands": [{"common_name": "red"}]},
                "SR_B5": {"href": "file:///tmp/nir.tif", "eo:bands": [{"common_name": "nir08"}]},
            },
        },
        {
            "id": "good-scene",
            "collection": "demo-optical",
            "properties": {"datetime": "2024-06-15T00:00:00Z", "eo:cloud_cover": 8.0},
            "assets": {
                "SR_B4": {"href": "file:///tmp/red.tif", "eo:bands": [{"common_name": "red"}]},
                "SR_B5": {"href": "file:///tmp/nir.tif", "eo:bands": [{"common_name": "nir08"}]},
            },
        },
    ]

    def fake_search_items(self, *, collection, aoi, datetime_range, limit):
        assert collection == "demo-optical"
        return raw_items

    monkeypatch.setattr("steppe_prospector.stac.STACClient.search_items", fake_search_items)

    manifest = build_stac_selection(aoi_from_bbox(90.0, 47.0, 90.1, 47.1), recipe)
    assert "optical" in manifest.series
    assert len(manifest.series["optical"]) == 1
    selected = manifest.series["optical"][0]
    assert selected.item_id == "good-scene"
    assert selected.assets["red"].key == "SR_B4"
    assert selected.assets["nir"].key == "SR_B5"


def test_prepare_raster_pack_from_local_selection(tmp_path: Path) -> None:
    aoi = aoi_from_bbox(90.02, 47.02, 90.10, 47.10)

    red = np.full((100, 100), 0.2, dtype="float32")
    nir = np.full((100, 100), 0.6, dtype="float32")
    dem = np.linspace(1000, 1100, 10000, dtype="float32").reshape(100, 100)

    red_path = tmp_path / "sources" / "red.tif"
    nir_path = tmp_path / "sources" / "nir.tif"
    dem_path = tmp_path / "sources" / "dem.tif"
    _write_test_raster(red_path, red)
    _write_test_raster(nir_path, nir)
    _write_test_raster(dem_path, dem)

    selection = STACSelectionManifest(
        endpoint="https://example.com/stac",
        aoi_bounds=list(aoi.bounds),
        series={
            "optical": [
                SelectedItem(
                    item_id="scene-1",
                    collection="demo-optical",
                    datetime="2024-06-15T00:00:00Z",
                    bbox=None,
                    geometry=None,
                    properties={"eo:cloud_cover": 8.0},
                    assets={
                        "red": SelectedAsset(key="red", href=str(red_path)),
                        "nir": SelectedAsset(key="nir", href=str(nir_path)),
                    },
                )
            ],
            "dem": [
                SelectedItem(
                    item_id="dem-1",
                    collection="demo-dem",
                    datetime=None,
                    bbox=None,
                    geometry=None,
                    properties={},
                    assets={"primary": SelectedAsset(key="data", href=str(dem_path))},
                )
            ],
        },
    )

    recipe = STACRecipe(
        stac=STACClientConfig(endpoint="https://example.com/stac"),
        target=TargetGridConfig(resolution_m=1000.0),
        optical=SeriesRecipe(
            enabled=True,
            collection="demo-optical",
            output_kind="ndvi",
            asset_groups={"red": ["red"], "nir": ["nir"]},
        ),
        dem=SeriesRecipe(
            enabled=True,
            collection="demo-dem",
            output_kind="single-band",
            asset_groups={"primary": ["data"]},
        ),
    )

    prepared = prepare_raster_pack(aoi, recipe=recipe, pack_dir=tmp_path / "pack", selection=selection)

    optical_dir = prepared.pack_dir / "optical"
    optical_files = sorted(optical_dir.glob("*.tif"))
    assert optical_files
    assert (prepared.pack_dir / "dem.tif").exists()
    assert (prepared.pack_dir / "quality.tif").exists()
    assert prepared.selection_manifest.exists()
    assert prepared.pack_manifest.exists()

    with rasterio.open(optical_files[0]) as src:
        arr = src.read(1).astype("float32")
        nodata = src.nodata
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)
        finite = arr[np.isfinite(arr)]
        assert finite.size > 0
        assert np.nanmean(finite) > 0.4
        assert np.nanmean(finite) < 0.6
