from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
class GuardrailConfig:
    public_coordinate_blur_m: float
    restricted_coordinate_blur_m: float
    block_in_red_zones: bool
    withhold_sensitive_candidates: bool


@dataclass(slots=True)
class Settings:
    scoring: ScoringConfig
    guardrails: GuardrailConfig
    landscape_weights: dict[str, LandscapeWeights]


def _read_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_settings(path: str | Path | None = None) -> Settings:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "default.toml"
    else:
        path = Path(path)

    raw = _read_toml(path)
    scoring = ScoringConfig(**raw["scoring"])
    guardrails = GuardrailConfig(**raw["guardrails"])
    landscape_weights = {
        key: LandscapeWeights(**value)
        for key, value in raw["landscape_weights"].items()
    }
    return Settings(
        scoring=scoring,
        guardrails=guardrails,
        landscape_weights=landscape_weights,
    )
