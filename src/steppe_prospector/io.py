from __future__ import annotations

import json
from pathlib import Path

from .features import build_evidence
from .models import Candidate, Coordinate, LandscapeClass, SensitivityLevel


def _landscape(value: str) -> LandscapeClass:
    try:
        return LandscapeClass(value)
    except ValueError:
        return LandscapeClass.UNKNOWN


def _sensitivity(value: str) -> SensitivityLevel:
    try:
        return SensitivityLevel(value)
    except ValueError:
        return SensitivityLevel.NORMAL


def load_candidates(path: str | Path) -> list[Candidate]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates: list[Candidate] = []
    for item in data:
        candidates.append(
            Candidate(
                candidate_id=str(item["candidate_id"]),
                location=Coordinate(lat=float(item["lat"]), lon=float(item["lon"])),
                landscape=_landscape(str(item.get("landscape", "unknown"))),
                evidence=build_evidence(item),
                sensitivity=_sensitivity(str(item.get("sensitivity", "normal"))),
                tags=list(item.get("tags", [])),
                source_dates=list(item.get("source_dates", [])),
            )
        )
    return candidates


def save_ranked(path: str | Path, ranked: list[dict]) -> None:
    path = Path(path)
    path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")
