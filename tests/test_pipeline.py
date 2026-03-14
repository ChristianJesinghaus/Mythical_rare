from steppe_prospector.models import Candidate, CandidateEvidence, Coordinate, LandscapeClass, PermitMode
from steppe_prospector.pipeline import MongoliaProspectionPipeline


def test_pipeline_ranks_and_redacts() -> None:
    candidate = Candidate(
        candidate_id="A",
        location=Coordinate(lat=47.0, lon=91.0),
        landscape=LandscapeClass.STEPPE,
        evidence=CandidateEvidence(
            optical_anomaly=0.7,
            sar_anomaly=0.6,
            microrelief=0.8,
            enclosure_shape=0.75,
            linearity=0.5,
            temporal_persistence=0.8,
            historical_match=0.6,
            contextual_fit=0.8,
            modern_disturbance=0.1,
            natural_confounder_risk=0.2,
            data_quality=0.9,
        ),
    )
    pipeline = MongoliaProspectionPipeline()
    result = pipeline.evaluate([candidate], PermitMode.PUBLIC)
    assert len(result) == 1
    assert result[0].adjusted_score > 0
    assert result[0].exact_location is None
    assert result[0].public_location is not None
