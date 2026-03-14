from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians

from .config import GuardrailConfig
from .models import Candidate, Coordinate, PermitMode, SensitivityLevel


@dataclass(slots=True)
class RedZoneRule:
    """A simple bounding-box rule.

    Replace this with official polygon intersections in later phases.
    """

    name: str
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, point: Coordinate) -> bool:
        return (
            self.min_lat <= point.lat <= self.max_lat
            and self.min_lon <= point.lon <= self.max_lon
        )


def _meters_to_latlon_offset(point: Coordinate, meters: float) -> tuple[float, float]:
    # conservative approximation adequate for coordinate redaction, not surveying
    lat_deg = meters / 111_320.0
    lon_deg = meters / (111_320.0 * max(cos(radians(point.lat)), 0.1))
    return lat_deg, lon_deg


def blur_coordinate(point: Coordinate, meters: float) -> Coordinate:
    lat_offset, lon_offset = _meters_to_latlon_offset(point, meters)
    # deterministic but simple public redaction shift
    return Coordinate(lat=point.lat + lat_offset, lon=point.lon - lon_offset)


def in_red_zone(candidate: Candidate, red_zones: list[RedZoneRule]) -> bool:
    return any(rule.contains(candidate.location) for rule in red_zones)


def should_withhold(
    candidate: Candidate,
    permit_mode: PermitMode,
    config: GuardrailConfig,
    red_zones: list[RedZoneRule],
) -> bool:
    if config.block_in_red_zones and in_red_zone(candidate, red_zones):
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
