from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings, load_settings
from .guardrails import RedZoneLike, demo_red_zones, redact_location, should_withhold
from .models import Candidate, LandscapeClass, PermitMode, RankedCandidate
from .scoring import confidence_band, explain_candidate, score_candidate


@dataclass(slots=True)
class MongoliaProspectionPipeline:
    settings: Settings = field(default_factory=load_settings)
    red_zones: list[RedZoneLike] = field(default_factory=list)

    def _weights_for(self, landscape: LandscapeClass):
        key = landscape.value if landscape.value in self.settings.landscape_weights else "steppe"
        return self.settings.landscape_weights[key]

    def evaluate_candidate(self, candidate: Candidate, permit_mode: PermitMode) -> RankedCandidate | None:
        if should_withhold(candidate, permit_mode, self.settings.guardrails, self.red_zones):
            return None

        weights = self._weights_for(candidate.landscape)
        raw, adjusted = score_candidate(
            evidence=candidate.evidence,
            landscape=candidate.landscape,
            weights=weights,
            cfg=self.settings.scoring,
        )
        exact_location, public_location = redact_location(candidate, permit_mode, self.settings.guardrails)
        return RankedCandidate(
            candidate_id=candidate.candidate_id,
            raw_score=round(raw, 4),
            adjusted_score=round(adjusted, 4),
            confidence=confidence_band(adjusted),
            reasons=explain_candidate(candidate.evidence, adjusted),
            landscape=candidate.landscape.value,
            sensitivity=candidate.sensitivity.value,
            exact_location=exact_location,
            public_location=public_location,
            tags=candidate.tags,
            source_dates=candidate.source_dates,
        )

    def evaluate(self, candidates: list[Candidate], permit_mode: PermitMode) -> list[RankedCandidate]:
        ranked: list[RankedCandidate] = []
        for candidate in candidates:
            result = self.evaluate_candidate(candidate, permit_mode)
            if result is not None:
                ranked.append(result)
        ranked.sort(key=lambda item: item.adjusted_score, reverse=True)
        return ranked


__all__ = ["MongoliaProspectionPipeline", "demo_red_zones"]
