from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from shapely.geometry import mapping

from .aoi import AOI
from .stac_recipe import FilterRule, STACClientConfig, SeriesRecipe, STACRecipe


@dataclass(slots=True)
class SelectedAsset:
    key: str
    href: str

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "href": self.href}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectedAsset":
        return cls(key=str(data["key"]), href=str(data["href"]))


@dataclass(slots=True)
class SelectedItem:
    item_id: str
    collection: str
    datetime: str | None
    bbox: list[float] | None
    geometry: dict[str, Any] | None
    properties: dict[str, Any]
    assets: dict[str, SelectedAsset]

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "collection": self.collection,
            "datetime": self.datetime,
            "bbox": self.bbox,
            "geometry": self.geometry,
            "properties": self.properties,
            "assets": {key: value.to_dict() for key, value in self.assets.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectedItem":
        return cls(
            item_id=str(data["item_id"]),
            collection=str(data["collection"]),
            datetime=data.get("datetime"),
            bbox=list(data["bbox"]) if data.get("bbox") else None,
            geometry=data.get("geometry"),
            properties=dict(data.get("properties", {})),
            assets={key: SelectedAsset.from_dict(value) for key, value in data.get("assets", {}).items()},
        )


@dataclass(slots=True)
class STACSelectionManifest:
    endpoint: str
    aoi_bounds: list[float]
    series: dict[str, list[SelectedItem]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "aoi_bounds": self.aoi_bounds,
            "series": {
                key: [item.to_dict() for item in items]
                for key, items in self.series.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "STACSelectionManifest":
        return cls(
            endpoint=str(data["endpoint"]),
            aoi_bounds=[float(value) for value in data.get("aoi_bounds", [])],
            series={
                key: [SelectedItem.from_dict(entry) for entry in items]
                for key, items in data.get("series", {}).items()
            },
        )


class STACClient:
    def __init__(self, config: STACClientConfig) -> None:
        self.config = config
        self._session = requests.Session()
        self._session.headers.update(config.headers)

    @property
    def search_url(self) -> str:
        return self.config.endpoint.rstrip("/") + "/search"

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "STACClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def search_items(
        self,
        *,
        collection: str,
        aoi: AOI,
        datetime_range: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "collections": [collection],
            "intersects": mapping(aoi.geometry_wgs84),
            "limit": max(1, min(limit, 500)),
        }
        if datetime_range:
            payload["datetime"] = datetime_range

        items: list[dict[str, Any]] = []
        next_request: tuple[str, str, dict[str, Any] | None, dict[str, str] | None] | None = (
            "POST",
            self.search_url,
            payload,
            None,
        )
        pages = 0
        seen_next: set[tuple[str, str]] = set()

        while next_request and pages < self.config.max_pages:
            method, url, body, headers = next_request
            response = self._session.request(
                method,
                url,
                json=body if method.upper() != "GET" else None,
                params=body if method.upper() == "GET" else None,
                headers=headers,
                timeout=self.config.timeout_s,
            )
            response.raise_for_status()
            payload_json = response.json()
            items.extend(payload_json.get("features", []))
            pages += 1

            next_request = None
            for link in payload_json.get("links", []):
                if link.get("rel") != "next":
                    continue
                href = link.get("href")
                if not href:
                    continue
                href = urljoin(url, href)
                method = str(link.get("method", "GET")).upper()
                body = link.get("body")
                headers = link.get("headers")
                signature = (method, href)
                if signature in seen_next:
                    continue
                seen_next.add(signature)
                next_request = (method, href, body, headers)
                break

        return items


class PlanetaryComputerSigner:
    def __init__(self, timeout_s: float = 120.0) -> None:
        self.timeout_s = timeout_s
        self._session = requests.Session()

    def sign(self, href: str) -> str:
        response = self._session.get(
            "https://planetarycomputer.microsoft.com/api/sas/v1/sign",
            params={"href": href},
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("href") or href)

    def close(self) -> None:
        self._session.close()


def _get_item_value(item: dict[str, Any], key: str) -> Any:
    if key == "datetime":
        return item.get("properties", {}).get("datetime") or item.get("datetime")
    current: Any
    if key.startswith("properties."):
        current = item.get("properties", {})
        parts = key.split(".")[1:]
    elif "." in key:
        current = item
        parts = key.split(".")
    else:
        props = item.get("properties", {})
        if key in props:
            return props.get(key)
        return item.get(key)

    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _normalize_alias(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _asset_matches_alias(asset_key: str, asset: dict[str, Any], alias: str) -> bool:
    alias_norm = _normalize_alias(alias)
    if _normalize_alias(asset_key) == alias_norm:
        return True

    title = asset.get("title")
    if isinstance(title, str) and alias_norm in _normalize_alias(title):
        return True

    eo_bands = asset.get("eo:bands") or asset.get("bands") or []
    if isinstance(eo_bands, list):
        for band in eo_bands:
            if not isinstance(band, dict):
                continue
            name = band.get("name")
            common_name = band.get("common_name")
            if isinstance(name, str) and _normalize_alias(name) == alias_norm:
                return True
            if isinstance(common_name, str) and _normalize_alias(common_name) == alias_norm:
                return True
    return False


def find_asset(assets: dict[str, Any], aliases: Iterable[str]) -> SelectedAsset | None:
    alias_list = [alias for alias in aliases if alias]
    if not alias_list:
        return None

    for alias in alias_list:
        if alias in assets:
            href = assets[alias].get("href")
            if href:
                return SelectedAsset(key=alias, href=str(href))

    for asset_key, asset in assets.items():
        if not isinstance(asset, dict):
            continue
        href = asset.get("href")
        if not href:
            continue
        for alias in alias_list:
            if _asset_matches_alias(asset_key, asset, alias):
                return SelectedAsset(key=str(asset_key), href=str(href))
    return None


def passes_filters(item: dict[str, Any], rules: Iterable[FilterRule]) -> bool:
    for rule in rules:
        value = _get_item_value(item, rule.property)
        if rule.eq is not None and value != rule.eq:
            return False
        if rule.ne is not None and value == rule.ne:
            return False
        if rule.contains is not None:
            if value is None or rule.contains not in str(value):
                return False
        if rule.lte is not None:
            try:
                if value is None or float(value) > rule.lte:
                    return False
            except (TypeError, ValueError):
                return False
        if rule.gte is not None:
            try:
                if value is None or float(value) < rule.gte:
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _sort_key(item: dict[str, Any], property_name: str) -> tuple[int, Any]:
    value = _get_item_value(item, property_name)
    if value is None:
        return (1, "")
    if property_name == "datetime":
        try:
            if isinstance(value, str):
                return (0, datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
    return (0, value)


def _select_items_for_series(raw_items: list[dict[str, Any]], recipe: SeriesRecipe) -> list[SelectedItem]:
    filtered = [item for item in raw_items if passes_filters(item, recipe.filters)]

    selected: list[SelectedItem] = []
    for item in filtered:
        assets = item.get("assets", {})
        picked_assets: dict[str, SelectedAsset] = {}
        for group_name, aliases in recipe.asset_groups.items():
            picked = find_asset(assets, aliases)
            if picked is None:
                break
            picked_assets[group_name] = picked
        else:
            selected.append(
                SelectedItem(
                    item_id=str(item.get("id", "unknown-item")),
                    collection=str(item.get("collection", recipe.collection)),
                    datetime=_get_item_value(item, "datetime"),
                    bbox=list(item["bbox"]) if item.get("bbox") else None,
                    geometry=item.get("geometry"),
                    properties=dict(item.get("properties", {})),
                    assets=picked_assets,
                )
            )

    selected.sort(key=lambda item: _selected_sort_key(item, recipe.sort_by), reverse=not recipe.sort_ascending)
    return selected[: recipe.max_items]


def _selected_sort_key(item: SelectedItem, property_name: str) -> tuple[int, Any]:
    if property_name == "datetime":
        value = item.datetime
        if value is None:
            return (1, "")
        try:
            return (0, datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return (0, value)
    value = item.properties.get(property_name)
    if value is None:
        return (1, "")
    return (0, value)


def build_stac_selection(aoi: AOI, recipe: STACRecipe) -> STACSelectionManifest:
    with STACClient(recipe.stac) as client:
        series_map: dict[str, list[SelectedItem]] = {}
        for name, series_recipe in (
            ("optical", recipe.optical),
            ("sar", recipe.sar),
            ("dem", recipe.dem),
            ("historical", recipe.historical),
        ):
            if not series_recipe.enabled:
                continue
            raw_items = client.search_items(
                collection=series_recipe.collection,
                aoi=aoi,
                datetime_range=series_recipe.datetime,
                limit=series_recipe.search_limit,
            )
            series_map[name] = _select_items_for_series(raw_items, series_recipe)

    return STACSelectionManifest(
        endpoint=recipe.stac.endpoint,
        aoi_bounds=list(aoi.bounds),
        series=series_map,
    )
