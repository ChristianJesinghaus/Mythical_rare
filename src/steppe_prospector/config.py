from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import tomllib


@dataclass(slots=True)
class LandscapeWeights:
    optical_anomaly: float
    sar_anomaly: float
    microrelief: float
    enclosure_shape: float
    linearity: float
    temporal_persistence: float
    historical_match: float
    contextual_fit: float


@dataclass(slots=True)
class ScoringConfig:
    penalty_strength: float
    uncertainty_strength: float


@dataclass(slots=True)
class AnalysisConfig:
    tile_size_m: float = 500.0
    tile_step_m: float = 500.0
    min_tile_coverage: float = 0.2
    min_valid_pixel_fraction: float = 0.3
    min_adjusted_score: float = 0.3
    max_candidates: int = 500


@dataclass(slots=True)
class FeatureEngineConfig:
    anomaly_sigma_px: float = 2.0
    dem_sigma_px: float = 3.0
    anomaly_z_cap: float = 6.0
    temporal_anomaly_z: float = 2.5
    edge_sigma: float = 1.2
    mask_quantile: float = 0.85


@dataclass(slots=True)
class GuardrailConfig:
    public_coordinate_blur_m: float
    restricted_coordinate_blur_m: float
    block_in_red_zones: bool
    withhold_sensitive_candidates: bool
    red_zone_access: str = "authorized-only"


@dataclass(slots=True)
class Settings:
    scoring: ScoringConfig
    analysis: AnalysisConfig
    features: FeatureEngineConfig
    guardrails: GuardrailConfig
    landscape_weights: dict[str, LandscapeWeights]


DEFAULT_ANALYSIS = AnalysisConfig()
DEFAULT_FEATURES = FeatureEngineConfig()
DEFAULT_GUARDRAILS = GuardrailConfig(
    public_coordinate_blur_m=5000.0,
    restricted_coordinate_blur_m=1000.0,
    block_in_red_zones=True,
    withhold_sensitive_candidates=True,
    red_zone_access="authorized-only",
)


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge_defaults(raw: dict[str, Any], defaults: Any) -> dict[str, Any]:
    values = dict(raw)
    for field in fields(defaults):
        values.setdefault(field.name, getattr(defaults, field.name))
    return values


def load_settings(path: str | Path | None = None) -> Settings:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "default.toml"
    else:
        path = Path(path)

    raw = _read_toml(path)

    scoring = ScoringConfig(**raw["scoring"])
    analysis = AnalysisConfig(**_merge_defaults(raw.get("analysis", {}), DEFAULT_ANALYSIS))
    features = FeatureEngineConfig(**_merge_defaults(raw.get("feature_engine", {}), DEFAULT_FEATURES))
    guardrails = GuardrailConfig(**_merge_defaults(raw.get("guardrails", {}), DEFAULT_GUARDRAILS))

    landscape_weights = {
        key: LandscapeWeights(**value)
        for key, value in raw["landscape_weights"].items()
    }

    return Settings(
        scoring=scoring,
        analysis=analysis,
        features=features,
        guardrails=guardrails,
        landscape_weights=landscape_weights,
    )
