from __future__ import annotations

from .models import CandidateEvidence


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def build_evidence(values: dict[str, float | int | str | list[str]]) -> CandidateEvidence:
    """Create normalized evidence from a flat mapping.

    This function is intentionally lightweight so you can feed it output from a
    raster-processing stage later.
    """

    def get(name: str, default: float = 0.0) -> float:
        try:
            return clamp01(float(values.get(name, default)))
        except (TypeError, ValueError):
            return clamp01(default)

    notes_raw = values.get("notes", [])
    notes = notes_raw if isinstance(notes_raw, list) else []

    return CandidateEvidence(
        optical_anomaly=get("optical_anomaly"),
        sar_anomaly=get("sar_anomaly"),
        microrelief=get("microrelief"),
        enclosure_shape=get("enclosure_shape"),
        linearity=get("linearity"),
        temporal_persistence=get("temporal_persistence"),
        historical_match=get("historical_match"),
        contextual_fit=get("contextual_fit"),
        modern_disturbance=get("modern_disturbance"),
        natural_confounder_risk=get("natural_confounder_risk"),
        data_quality=get("data_quality", 1.0),
        notes=notes,
    )
