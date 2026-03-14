from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class LandscapeClass(str, Enum):
    STEPPE = "steppe"
    VALLEY = "valley"
    MOUNTAIN = "mountain"
    FOREST = "forest"
    UNKNOWN = "unknown"


class PermitMode(str, Enum):
    PUBLIC = "public"
    RESTRICTED = "restricted"
    AUTHORIZED = "authorized"


class SensitivityLevel(str, Enum):
    NORMAL = "normal"
    RESTRICTED = "restricted"
    SENSITIVE = "sensitive"


@dataclass(slots=True)
class Coordinate:
    lat: float
    lon: float


@dataclass(slots=True)
class CandidateEvidence:
    optical_anomaly: float = 0.0
    sar_anomaly: float = 0.0
    microrelief: float = 0.0
    enclosure_shape: float = 0.0
    linearity: float = 0.0
    temporal_persistence: float = 0.0
    historical_match: float = 0.0
    contextual_fit: float = 0.0
    modern_disturbance: float = 0.0
    natural_confounder_risk: float = 0.0
    data_quality: float = 1.0
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Candidate:
    candidate_id: str
    location: Coordinate
    landscape: LandscapeClass
    evidence: CandidateEvidence
    sensitivity: SensitivityLevel = SensitivityLevel.NORMAL
    tags: list[str] = field(default_factory=list)
    source_dates: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RankedCandidate:
    candidate_id: str
    raw_score: float
    adjusted_score: float
    confidence: str
    reasons: list[str]
    landscape: str
    sensitivity: str
    exact_location: Coordinate | None
    public_location: Coordinate | None
    tags: list[str]
    source_dates: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
