from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians
from pathlib import Path
from typing import Any, Iterable, Protocol

import json
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from .config import GuardrailConfig
from .models import Candidate, Coordinate, PermitMode, SensitivityLevel


class RedZoneLike(Protocol):
    name: str

    def contains(self, point: Coordinate) -> bool: ...

    def intersects_geometry(self, geometry: BaseGeometry) -> bool: ...


@dataclass(slots=True)
class RedZoneRule:
    """A red-zone rule backed by a bounding box or polygon geometry in EPSG:4326."""

    name: str
    min_lat: float | None = None
    max_lat: float | None = None
    min_lon: float | None = None
    max_lon: float | None = None
    geometry: BaseGeometry | None = None
    properties: dict[str, Any] | None = None

    def contains(self, point: Coordinate) -> bool:
        if self.geometry is not None:
            return self.geometry.contains(Point(point.lon, point.lat))
        if None in {self.min_lat, self.max_lat, self.min_lon, self.max_lon}:
            return False
        return (
            self.min_lat <= point.lat <= self.max_lat
            and self.min_lon <= point.lon <= self.max_lon
        )

    def intersects_geometry(self, geometry: BaseGeometry) -> bool:
        if self.geometry is not None:
            return self.geometry.intersects(geometry)
        if None in {self.min_lat, self.max_lat, self.min_lon, self.max_lon}:
            return False
        bbox = shape(
            {
                "type": "Polygon",
                "coordinates": [[
                    [self.min_lon, self.min_lat],
                    [self.max_lon, self.min_lat],
                    [self.max_lon, self.max_lat],
                    [self.min_lon, self.max_lat],
                    [self.min_lon, self.min_lat],
                ]],
            }
        )
        return bbox.intersects(geometry)


@dataclass(slots=True)
class GeoZoneMatch:
    zone_name: str
    properties: dict[str, Any]


def load_red_zones_geojson(path: str | Path) -> list[RedZoneRule]:
    """Load polygon red zones from a GeoJSON FeatureCollection in EPSG:4326."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    features = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]
    zones: list[RedZoneRule] = []
    for idx, feature in enumerate(features):
        geom = feature.get("geometry")
        if not geom:
            continue
        props = feature.get("properties") or {}
        zones.append(
            RedZoneRule(
                name=str(props.get("name", f"red-zone-{idx+1}")),
                geometry=shape(geom),
                properties=props,
            )
        )
    return zones


def _meters_to_latlon_offset(point: Coordinate, meters: float) -> tuple[float, float]:
    # Conservative approximation adequate for coordinate redaction, not surveying.
    lat_deg = meters / 111_320.0
    lon_deg = meters / (111_320.0 * max(cos(radians(point.lat)), 0.1))
    return lat_deg, lon_deg


def blur_coordinate(point: Coordinate, meters: float) -> Coordinate:
    lat_offset, lon_offset = _meters_to_latlon_offset(point, meters)
    # Deterministic but simple public redaction shift.
    return Coordinate(lat=point.lat + lat_offset, lon=point.lon - lon_offset)


def in_red_zone(candidate: Candidate, red_zones: Iterable[RedZoneLike]) -> bool:
    return any(rule.contains(candidate.location) for rule in red_zones)


def geometry_hits_red_zone(geometry: BaseGeometry, red_zones: Iterable[RedZoneLike]) -> bool:
    return any(rule.intersects_geometry(geometry) for rule in red_zones)


def matched_red_zones(geometry: BaseGeometry, red_zones: Iterable[RedZoneLike]) -> list[GeoZoneMatch]:
    matches: list[GeoZoneMatch] = []
    for zone in red_zones:
        if zone.intersects_geometry(geometry):
            matches.append(
                GeoZoneMatch(
                    zone_name=zone.name,
                    properties=dict(getattr(zone, "properties", {}) or {}),
                )
            )
    return matches


def should_withhold(
    candidate: Candidate,
    permit_mode: PermitMode,
    config: GuardrailConfig,
    red_zones: list[RedZoneLike],
) -> bool:
    if config.block_in_red_zones and in_red_zone(candidate, red_zones):
        if config.red_zone_access == "block":
            return True
        if config.red_zone_access == "authorized-only" and permit_mode != PermitMode.AUTHORIZED:
            return True
    if (
        config.withhold_sensitive_candidates
        and candidate.sensitivity == SensitivityLevel.SENSITIVE
        and permit_mode != PermitMode.AUTHORIZED
    ):
        return True
    return False


def redact_location(
    candidate: Candidate,
    permit_mode: PermitMode,
    config: GuardrailConfig,
) -> tuple[Coordinate | None, Coordinate | None]:
    if permit_mode == PermitMode.AUTHORIZED:
        return candidate.location, candidate.location
    if permit_mode == PermitMode.RESTRICTED:
        blurred = blur_coordinate(candidate.location, config.restricted_coordinate_blur_m)
        return None, blurred
    blurred = blur_coordinate(candidate.location, config.public_coordinate_blur_m)
    return None, blurred


def demo_red_zones() -> list[RedZoneRule]:
    """Synthetic placeholder rules for testing only.

    Replace with official protected-area and heritage-zone polygons.
    """

    return [
        RedZoneRule(
            name="synthetic_red_zone",
            min_lat=48.0,
            max_lat=48.4,
            min_lon=90.0,
            max_lon=90.4,
        )
    ]
