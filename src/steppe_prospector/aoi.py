from __future__ import annotations

from dataclasses import dataclass
from math import floor
from pathlib import Path
from typing import Iterable

import json
from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from .models import Coordinate


@dataclass(slots=True)
class AOI:
    geometry_wgs84: BaseGeometry

    @property
    def centroid(self) -> Coordinate:
        centroid = self.geometry_wgs84.centroid
        return Coordinate(lat=float(centroid.y), lon=float(centroid.x))

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        minx, miny, maxx, maxy = self.geometry_wgs84.bounds
        return float(minx), float(miny), float(maxx), float(maxy)


@dataclass(slots=True)
class AOITile:
    tile_id: str
    geometry_wgs84: Polygon
    centroid: Coordinate
    coverage_fraction: float


def load_aoi(path: str | Path) -> AOI:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if data.get("type") == "FeatureCollection":
        geoms = [shape(feature["geometry"]) for feature in data.get("features", []) if feature.get("geometry")]
        geometry = unary_union(geoms)
    elif data.get("type") == "Feature":
        geometry = shape(data["geometry"])
    else:
        geometry = shape(data)

    if geometry.is_empty:
        raise ValueError("AOI geometry is empty.")
    return AOI(geometry_wgs84=geometry)


def aoi_from_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> AOI:
    return AOI(geometry_wgs84=box(min_lon, min_lat, max_lon, max_lat))


def _utm_epsg_for_lonlat(lon: float, lat: float) -> int:
    zone = int(floor((lon + 180.0) / 6.0) + 1)
    return (32600 if lat >= 0 else 32700) + zone


def local_metric_crs(aoi: AOI) -> CRS:
    centroid = aoi.centroid
    return CRS.from_epsg(_utm_epsg_for_lonlat(centroid.lon, centroid.lat))


def _transform_geometry(geometry: BaseGeometry, src: CRS | str, dst: CRS | str) -> BaseGeometry:
    transformer = Transformer.from_crs(src, dst, always_xy=True)
    return transform(transformer.transform, geometry)


def tile_aoi(
    aoi: AOI,
    tile_size_m: float,
    tile_step_m: float | None = None,
    min_tile_coverage: float = 0.2,
) -> list[AOITile]:
    if tile_size_m <= 0:
        raise ValueError("tile_size_m must be > 0")

    tile_step_m = tile_step_m or tile_size_m
    metric_crs = local_metric_crs(aoi)
    geom_metric = _transform_geometry(aoi.geometry_wgs84, "EPSG:4326", metric_crs)
    minx, miny, maxx, maxy = geom_metric.bounds

    tiles: list[AOITile] = []
    idx = 1
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            tile_metric = box(x, y, x + tile_size_m, y + tile_size_m)
            intersection = geom_metric.intersection(tile_metric)
            if not intersection.is_empty:
                coverage = intersection.area / max(tile_metric.area, 1.0)
                if coverage >= min_tile_coverage:
                    tile_wgs84 = _transform_geometry(tile_metric, metric_crs, "EPSG:4326")
                    centroid = tile_wgs84.centroid
                    tiles.append(
                        AOITile(
                            tile_id=f"tile-{idx:05d}",
                            geometry_wgs84=tile_wgs84,
                            centroid=Coordinate(lat=float(centroid.y), lon=float(centroid.x)),
                            coverage_fraction=float(coverage),
                        )
                    )
                    idx += 1
            y += tile_step_m
        x += tile_step_m
    return tiles
