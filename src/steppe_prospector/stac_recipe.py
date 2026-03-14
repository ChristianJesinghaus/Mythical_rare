from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib


@dataclass(slots=True)
class FilterRule:
    property: str
    eq: str | float | int | bool | None = None
    ne: str | float | int | bool | None = None
    lte: float | None = None
    gte: float | None = None
    contains: str | None = None


@dataclass(slots=True)
class STACClientConfig:
    endpoint: str
    timeout_s: float = 120.0
    max_pages: int = 10
    asset_href_signing: str = "none"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TargetGridConfig:
    resolution_m: float = 30.0
    resampling: str = "bilinear"
    compress: str = "deflate"
    nodata: float = -9999.0
    output_crs: str | None = None


@dataclass(slots=True)
class SeriesRecipe:
    enabled: bool = False
    collection: str = ""
    datetime: str | None = None
    max_items: int = 4
    search_limit: int = 50
    output_kind: str = "single-band"
    filename_template: str = "{date}_{item_id}.tif"
    sort_by: str = "datetime"
    sort_ascending: bool = True
    asset_groups: dict[str, list[str]] = field(default_factory=dict)
    filters: list[FilterRule] = field(default_factory=list)
    resampling: str | None = None
    to_db: bool = False


@dataclass(slots=True)
class STACRecipe:
    stac: STACClientConfig
    target: TargetGridConfig
    optical: SeriesRecipe = field(default_factory=SeriesRecipe)
    sar: SeriesRecipe = field(default_factory=SeriesRecipe)
    dem: SeriesRecipe = field(default_factory=SeriesRecipe)
    historical: SeriesRecipe = field(default_factory=SeriesRecipe)


DEFAULT_TARGET = TargetGridConfig()
DEFAULT_STAC = STACClientConfig(endpoint="https://planetarycomputer.microsoft.com/api/stac/v1")
DEFAULT_SERIES = SeriesRecipe()


def _merge_defaults(raw: dict[str, Any], defaults: Any) -> dict[str, Any]:
    values = dict(raw)
    for field_name in defaults.__dataclass_fields__:  # type: ignore[attr-defined]
        values.setdefault(field_name, getattr(defaults, field_name))
    return values


def _parse_filters(raw_filters: list[dict[str, Any]] | None) -> list[FilterRule]:
    if not raw_filters:
        return []
    return [FilterRule(**entry) for entry in raw_filters]


def _parse_series(raw: dict[str, Any] | None) -> SeriesRecipe:
    if not raw:
        return SeriesRecipe()
    values = _merge_defaults(raw, DEFAULT_SERIES)
    values["filters"] = _parse_filters(raw.get("filters"))
    values["asset_groups"] = {key: list(value) for key, value in raw.get("asset_groups", {}).items()}
    return SeriesRecipe(**values)


def load_stac_recipe(path: str | Path) -> STACRecipe:
    recipe_path = Path(path)
    with recipe_path.open("rb") as f:
        raw = tomllib.load(f)

    stac = STACClientConfig(**_merge_defaults(raw.get("stac", {}), DEFAULT_STAC))
    target = TargetGridConfig(**_merge_defaults(raw.get("target", {}), DEFAULT_TARGET))
    optical = _parse_series(raw.get("optical"))
    sar = _parse_series(raw.get("sar"))
    dem = _parse_series(raw.get("dem"))
    historical = _parse_series(raw.get("historical"))
    return STACRecipe(stac=stac, target=target, optical=optical, sar=sar, dem=dem, historical=historical)
