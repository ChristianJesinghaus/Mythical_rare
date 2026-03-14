from __future__ import annotations

from .config import LandscapeWeights, ScoringConfig
from .models import CandidateEvidence, LandscapeClass


def _weighted_positive_score(e: CandidateEvidence, w: LandscapeWeights) -> float:
    weighted = (
        e.optical_anomaly * w.optical_anomaly
        + e.sar_anomaly * w.sar_anomaly
        + e.microrelief * w.microrelief
        + e.enclosure_shape * w.enclosure_shape
        + e.linearity * w.linearity
        + e.temporal_persistence * w.temporal_persistence
        + e.historical_match * w.historical_match
        + e.contextual_fit * w.contextual_fit
    )
    total_weight = (
        w.optical_anomaly
        + w.sar_anomaly
        + w.microrelief
        + w.enclosure_shape
        + w.linearity
        + w.temporal_persistence
        + w.historical_match
        + w.contextual_fit
    )
    return weighted / total_weight if total_weight else 0.0


def _penalty(e: CandidateEvidence, cfg: ScoringConfig) -> float:
    return cfg.penalty_strength * (
        0.6 * e.modern_disturbance + 0.4 * e.natural_confounder_risk
    )


def _uncertainty_discount(e: CandidateEvidence, landscape: LandscapeClass, cfg: ScoringConfig) -> float:
    base = (1.0 - e.data_quality) + 0.5 * e.natural_confounder_risk
    if landscape in {LandscapeClass.MOUNTAIN, LandscapeClass.FOREST, LandscapeClass.UNKNOWN}:
        base += 0.15
    return cfg.uncertainty_strength * min(base, 1.0)


def score_candidate(
    evidence: CandidateEvidence,
    landscape: LandscapeClass,
    weights: LandscapeWeights,
    cfg: ScoringConfig,
) -> tuple[float, float]:
    raw = _weighted_positive_score(evidence, weights)
    adjusted = raw - _penalty(evidence, cfg) - _uncertainty_discount(evidence, landscape, cfg)
    adjusted = max(0.0, min(1.0, adjusted))
    return raw, adjusted


def confidence_band(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    if score >= 0.25:
        return "low"
    return "very-low"


def explain_candidate(e: CandidateEvidence, score: float) -> list[str]:
    reasons: list[str] = []

    if e.microrelief >= 0.7:
        reasons.append("microrelief signal is strong")
    if e.enclosure_shape >= 0.7:
        reasons.append("regular enclosure-like geometry detected")
    if e.linearity >= 0.7:
        reasons.append("structured linear pattern detected")
    if e.temporal_persistence >= 0.7:
        reasons.append("signal persists across multiple observations")
    if e.historical_match >= 0.7:
        reasons.append("anomaly is supported by historical imagery")
    if e.contextual_fit >= 0.7:
        reasons.append("location fits plausible landscape context")
    if e.modern_disturbance >= 0.6:
        reasons.append("modern disturbance may be creating a false positive")
    if e.natural_confounder_risk >= 0.6:
        reasons.append("natural landform risk is high")
    if score < 0.35:
        reasons.append("candidate kept for review only, not field action")

    reasons.extend(e.notes)
    return reasons
