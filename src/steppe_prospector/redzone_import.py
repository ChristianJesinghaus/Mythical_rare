from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import json
from pyproj import CRS, Transformer
from shapely.geometry import shape, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from .aoi import AOI, local_metric_crs


@dataclass(slots=True)
class RedZoneImportOptions:
    name_field: str = "name"
    category_field: str | None = None
    include_categories: list[str] = field(default_factory=list)
    exclude_categories: list[str] = field(default_factory=list)
    buffer_m: float = 0.0
    point_buffer_m: float = 100.0
    line_buffer_m: float = 50.0
    simplify_m: float = 0.0
    min_area_ha: float = 0.0
    dissolve_by: str = "none"  # none | name | category | all
    default_name_prefix: str = "red-zone"


@dataclass(slots=True)
class RedZoneImportSummary:
    input_features: int
    kept_features: int
    dissolved_features: int
    output_path: Path
    summary_path: Path | None = None


class RedZoneImportError(RuntimeError):
    pass


def _transform_geometry(geometry: BaseGeometry, src: CRS | str, dst: CRS | str) -> BaseGeometry:
    transformer = Transformer.from_crs(src, dst, always_xy=True)
    return transform(transformer.transform, geometry)


def _metric_crs_for_geometry(geometry: BaseGeometry) -> CRS:
    centroid = geometry.centroid
    return local_metric_crs(AOI(geometry_wgs84=centroid.buffer(0.1).envelope))


def _category_allowed(category: str | None, options: RedZoneImportOptions) -> bool:
    category_norm = (category or "").strip().lower()
    include = {item.strip().lower() for item in options.include_categories if item.strip()}
    exclude = {item.strip().lower() for item in options.exclude_categories if item.strip()}
    if include and category_norm not in include:
        return False
    if exclude and category_norm in exclude:
        return False
    return True


def _name_for_feature(props: dict[str, Any], idx: int, options: RedZoneImportOptions) -> str:
    raw = props.get(options.name_field)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return f"{options.default_name_prefix}-{idx + 1}"


def _category_for_feature(props: dict[str, Any], options: RedZoneImportOptions) -> str | None:
    if not options.category_field:
        return None
    value = props.get(options.category_field)
    if value is None:
        return None
    return str(value)


def _prepare_geometry(geometry: BaseGeometry, options: RedZoneImportOptions) -> BaseGeometry | None:
    metric_crs = _metric_crs_for_geometry(geometry)
    geom_metric = _transform_geometry(geometry, "EPSG:4326", metric_crs)

    if geom_metric.geom_type in {"Point", "MultiPoint"}:
        geom_metric = geom_metric.buffer(max(options.point_buffer_m, 0.0))
    elif geom_metric.geom_type in {"LineString", "MultiLineString"}:
        geom_metric = geom_metric.buffer(max(options.line_buffer_m, 0.0))

    if options.buffer_m > 0:
        geom_metric = geom_metric.buffer(options.buffer_m)

    if options.simplify_m > 0:
        geom_metric = geom_metric.simplify(options.simplify_m, preserve_topology=True)

    if geom_metric.is_empty:
        return None
    if options.min_area_ha > 0 and geom_metric.area < options.min_area_ha * 10_000.0:
        return None

    geom_wgs84 = _transform_geometry(geom_metric, metric_crs, "EPSG:4326")
    if geom_wgs84.is_empty:
        return None
    return geom_wgs84


def _dissolve_key(name: str, category: str | None, options: RedZoneImportOptions) -> str:
    mode = options.dissolve_by.lower()
    if mode == "name":
        return f"name::{name}"
    if mode == "category":
        return f"category::{category or 'uncategorized'}"
    if mode == "all":
        return "all"
    return ""


def import_red_zones_geojson(
    input_path: str | Path,
    output_path: str | Path,
    *,
    options: RedZoneImportOptions | None = None,
    summary_path: str | Path | None = None,
) -> RedZoneImportSummary:
    options = options or RedZoneImportOptions()
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    features = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]

    prepared: list[dict[str, Any]] = []
    for idx, feature in enumerate(features):
        geom_data = feature.get("geometry")
        if not geom_data:
            continue
        props = dict(feature.get("properties") or {})
        geometry = shape(geom_data)
        category = _category_for_feature(props, options)
        if not _category_allowed(category, options):
            continue
        prepared_geometry = _prepare_geometry(geometry, options)
        if prepared_geometry is None:
            continue
        name = _name_for_feature(props, idx, options)
        prepared.append(
            {
                "name": name,
                "category": category,
                "geometry": prepared_geometry,
                "source_properties": props,
            }
        )

    if not prepared:
        raise RedZoneImportError("No red-zone features remained after filtering and geometry preparation.")

    grouped: dict[str, list[dict[str, Any]]] = {}
    if options.dissolve_by.lower() == "none":
        for idx, item in enumerate(prepared):
            grouped[f"feature::{idx}"] = [item]
    else:
        for item in prepared:
            key = _dissolve_key(item["name"], item["category"], options)
            grouped.setdefault(key, []).append(item)

    out_features: list[dict[str, Any]] = []
    for key, group in grouped.items():
        geometry = unary_union([item["geometry"] for item in group])
        first = group[0]
        name = first["name"]
        category = first["category"]
        if options.dissolve_by.lower() == "category":
            name = category or "uncategorized"
        elif options.dissolve_by.lower() == "all":
            name = "merged-red-zone"
            category = None

        out_features.append(
            {
                "type": "Feature",
                "geometry": mapping(geometry),
                "properties": {
                    "name": name,
                    "category": category,
                    "source_count": len(group),
                    "source_names": [item["name"] for item in group],
                },
            }
        )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "features": out_features,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    summary_payload = {
        "input_features": len(features),
        "kept_features": len(prepared),
        "dissolved_features": len(out_features),
        "options": {
            "name_field": options.name_field,
            "category_field": options.category_field,
            "include_categories": options.include_categories,
            "exclude_categories": options.exclude_categories,
            "buffer_m": options.buffer_m,
            "point_buffer_m": options.point_buffer_m,
            "line_buffer_m": options.line_buffer_m,
            "simplify_m": options.simplify_m,
            "min_area_ha": options.min_area_ha,
            "dissolve_by": options.dissolve_by,
        },
        "output": str(output),
    }

    summary_file: Path | None = None
    if summary_path is not None:
        summary_file = Path(summary_path)
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return RedZoneImportSummary(
        input_features=len(features),
        kept_features=len(prepared),
        dissolved_features=len(out_features),
        output_path=output,
        summary_path=summary_file,
    )


__all__ = [
    "RedZoneImportError",
    "RedZoneImportOptions",
    "RedZoneImportSummary",
    "import_red_zones_geojson",
]
