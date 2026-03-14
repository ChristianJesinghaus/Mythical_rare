from __future__ import annotations

from pathlib import Path

import json
import numpy as np
import rasterio
from rasterio.transform import from_origin


DEMO_BOUNDS = {
    "min_lon": 91.00,
    "min_lat": 47.00,
    "max_lon": 91.032,
    "max_lat": 47.032,
}


def _write_tif(path: Path, data: np.ndarray, transform, crs: str = "EPSG:4326") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=None,
    ) as dst:
        dst.write(data.astype("float32"), 1)


def _rectangle_mask(xx: np.ndarray, yy: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> np.ndarray:
    return ((xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1)).astype("float32")


def _ring_mask(xx: np.ndarray, yy: np.ndarray, cx: float, cy: float, r_outer: float, r_inner: float) -> np.ndarray:
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    return ((rr <= r_outer) & (rr >= r_inner)).astype("float32")


def create_demo_dataset(output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    pack_dir = root / "demo_pack"
    optical_dir = pack_dir / "optical"
    sar_dir = pack_dir / "sar"
    historical_dir = pack_dir / "historical"

    rng = np.random.default_rng(42)
    size = 128
    pixel_deg = (DEMO_BOUNDS["max_lon"] - DEMO_BOUNDS["min_lon"]) / size
    transform = from_origin(DEMO_BOUNDS["min_lon"], DEMO_BOUNDS["max_lat"], pixel_deg, pixel_deg)

    yy, xx = np.mgrid[0:size, 0:size]
    gradient = (xx / size) * 0.08 + (yy / size) * 0.04
    noise = rng.normal(0.0, 0.03, size=(size, size)).astype("float32")

    candidate_rect = _rectangle_mask(xx, yy, 48, 72, 44, 66)
    candidate_ring = _ring_mask(xx, yy, 96, 28, 11, 7)
    road = ((np.abs(yy - (0.55 * xx + 12)) <= 1.3)).astype("float32")
    gully = ((xx < 24) & (yy < 34)).astype("float32")

    optical_1 = 0.20 + gradient + noise + 0.55 * candidate_rect + 0.28 * candidate_ring + 0.10 * road
    optical_2 = 0.18 + gradient + rng.normal(0.0, 0.03, size=(size, size)) + 0.50 * candidate_rect + 0.24 * candidate_ring + 0.08 * road
    sar_1 = 0.10 + 0.8 * noise + 0.42 * candidate_rect + 0.18 * candidate_ring + 0.15 * road
    sar_2 = 0.11 + rng.normal(0.0, 0.03, size=(size, size)) + 0.38 * candidate_rect + 0.16 * candidate_ring + 0.13 * road

    mound = np.exp(-(((xx - 60) ** 2) + ((yy - 55) ** 2)) / (2.0 * 7.5 ** 2))
    mound_secondary = np.exp(-(((xx - 96) ** 2) + ((yy - 28) ** 2)) / (2.0 * 5.0 ** 2))
    dem = 1500.0 + 0.7 * xx + 0.35 * yy + 3.2 * mound + 1.5 * mound_secondary + 0.4 * gully

    historical_1 = 0.16 + gradient + rng.normal(0.0, 0.02, size=(size, size)) + 0.42 * candidate_rect + 0.22 * candidate_ring

    disturbance = np.clip(0.05 + 0.75 * road + 0.08 * rng.random((size, size)), 0.0, 1.0)
    confounder = np.clip(0.08 + 0.55 * gully + 0.08 * rng.random((size, size)), 0.0, 1.0)
    stream_y = 104.0
    water_proximity = np.clip(1.0 - np.abs(yy - stream_y) / 52.0, 0.0, 1.0)
    quality = np.clip(0.88 - 0.35 * (((xx - 20) ** 2 + (yy - 96) ** 2) < 12 ** 2).astype("float32"), 0.0, 1.0)
    forest = np.zeros((size, size), dtype="float32")

    _write_tif(optical_dir / "2025-06-12.tif", optical_1, transform)
    _write_tif(optical_dir / "2025-09-03.tif", optical_2, transform)
    _write_tif(sar_dir / "2025-06-14.tif", sar_1, transform)
    _write_tif(sar_dir / "2025-09-05.tif", sar_2, transform)
    _write_tif(historical_dir / "1968-corona.tif", historical_1, transform)
    _write_tif(pack_dir / "dem.tif", dem, transform)
    _write_tif(pack_dir / "disturbance.tif", disturbance, transform)
    _write_tif(pack_dir / "confounder.tif", confounder, transform)
    _write_tif(pack_dir / "water_proximity.tif", water_proximity, transform)
    _write_tif(pack_dir / "quality.tif", quality, transform)
    _write_tif(pack_dir / "forest.tif", forest, transform)

    aoi = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [DEMO_BOUNDS["min_lon"] + 0.001, DEMO_BOUNDS["min_lat"] + 0.001],
                [DEMO_BOUNDS["max_lon"] - 0.001, DEMO_BOUNDS["min_lat"] + 0.001],
                [DEMO_BOUNDS["max_lon"] - 0.001, DEMO_BOUNDS["max_lat"] - 0.001],
                [DEMO_BOUNDS["min_lon"] + 0.001, DEMO_BOUNDS["max_lat"] - 0.001],
                [DEMO_BOUNDS["min_lon"] + 0.001, DEMO_BOUNDS["min_lat"] + 0.001],
            ]],
        },
        "properties": {"name": "Demo AOI"},
    }
    aoi_path = root / "demo_aoi.geojson"
    aoi_path.write_text(json.dumps(aoi, indent=2), encoding="utf-8")

    red_zone = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [91.0205, 47.0225],
                        [91.0285, 47.0225],
                        [91.0285, 47.0295],
                        [91.0205, 47.0295],
                        [91.0205, 47.0225],
                    ]],
                },
                "properties": {
                    "name": "demo-sensitive-zone",
                    "category": "protected-demo",
                },
            }
        ],
    }
    red_zone_path = root / "demo_red_zones.geojson"
    red_zone_path.write_text(json.dumps(red_zone, indent=2), encoding="utf-8")

    return {
        "aoi": aoi_path,
        "red_zones": red_zone_path,
        "pack_dir": pack_dir,
    }
