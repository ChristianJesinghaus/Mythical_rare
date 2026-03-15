from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry.base import BaseGeometry

from .aoi import AOI, AOITile, tile_aoi
from .clustering import CandidateCluster, cluster_ranked_records
from .config import GuardrailConfig, Settings, load_settings
from .datapack import LocalRasterPack, open_local_raster_pack
from .guardrails import RedZoneLike, matched_red_zones
from .models import Candidate, Coordinate, PermitMode, RankedCandidate, SensitivityLevel
from .pipeline import MongoliaProspectionPipeline
from .raster_features import RasterReadError, TileFeatureResult, extract_tile_features


@dataclass(slots=True)
class CandidateRecord:
    candidate: Candidate
    footprint_wgs84: BaseGeometry
    coverage_fraction: float
    metrics: dict[str, float] = field(default_factory=dict)
    red_zone_names: list[str] = field(default_factory=list)

    def to_feature_dict(self) -> dict[str, object]:
        evidence = self.candidate.evidence
        return {
            "candidate_id": self.candidate.candidate_id,
            "lat": self.candidate.location.lat,
            "lon": self.candidate.location.lon,
            "landscape": self.candidate.landscape.value,
            "sensitivity": self.candidate.sensitivity.value,
            "coverage_fraction": round(self.coverage_fraction, 4),
            "tags": self.candidate.tags,
            "source_dates": self.candidate.source_dates,
            "red_zone_names": self.red_zone_names,
            "metrics": {key: round(value, 4) for key, value in self.metrics.items()},
            "optical_anomaly": round(evidence.optical_anomaly, 4),
            "sar_anomaly": round(evidence.sar_anomaly, 4),
            "microrelief": round(evidence.microrelief, 4),
            "enclosure_shape": round(evidence.enclosure_shape, 4),
            "linearity": round(evidence.linearity, 4),
            "temporal_persistence": round(evidence.temporal_persistence, 4),
            "historical_match": round(evidence.historical_match, 4),
            "contextual_fit": round(evidence.contextual_fit, 4),
            "modern_disturbance": round(evidence.modern_disturbance, 4),
            "natural_confounder_risk": round(evidence.natural_confounder_risk, 4),
            "data_quality": round(evidence.data_quality, 4),
            "notes": list(evidence.notes),
        }


@dataclass(slots=True)
class AOIAnalysisResult:
    records: list[CandidateRecord]
    ranked: list[RankedCandidate]
    clusters: list[CandidateCluster]
    permit_mode: PermitMode
    guardrail_config: GuardrailConfig
    total_tiles: int
    processed_tiles: int

    def ranked_record_pairs(self) -> list[tuple[CandidateRecord, RankedCandidate]]:
        by_id = {record.candidate.candidate_id: record for record in self.records}
        pairs: list[tuple[CandidateRecord, RankedCandidate]] = []
        for ranked in self.ranked:
            record = by_id.get(ranked.candidate_id)
            if record is not None:
                pairs.append((record, ranked))
        return pairs


class AOIAnalyzer:
    def __init__(
        self,
        settings: Settings | None = None,
        red_zones: list[RedZoneLike] | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.red_zones = list(red_zones or [])
        self.pipeline = MongoliaProspectionPipeline(settings=self.settings, red_zones=self.red_zones)

    def _make_candidate(
        self,
        tile: AOITile,
        extracted: TileFeatureResult,
        source_dates: list[str],
        red_zone_names: list[str],
    ) -> Candidate:
        sensitivity = SensitivityLevel.SENSITIVE if red_zone_names else SensitivityLevel.NORMAL
        tags = [f"landscape:{extracted.landscape.value}"]
        tags.extend(f"red-zone:{name}" for name in red_zone_names)

        return Candidate(
            candidate_id=tile.tile_id,
            location=Coordinate(lat=tile.centroid.lat, lon=tile.centroid.lon),
            landscape=extracted.landscape,
            evidence=extracted.evidence,
            sensitivity=sensitivity,
            tags=tags,
            source_dates=source_dates,
        )

    def analyze(
        self,
        aoi: AOI,
        pack: LocalRasterPack,
        permit_mode: PermitMode,
        tile_size_m: float | None = None,
        tile_step_m: float | None = None,
        min_tile_coverage: float | None = None,
        min_valid_pixel_fraction: float | None = None,
        min_adjusted_score: float | None = None,
        max_candidates: int | None = None,
        cluster_distance_m: float | None = None,
    ) -> AOIAnalysisResult:
        analysis_cfg = self.settings.analysis
        tile_size_m = tile_size_m or analysis_cfg.tile_size_m
        tile_step_m = tile_step_m or analysis_cfg.tile_step_m
        min_tile_coverage = min_tile_coverage if min_tile_coverage is not None else analysis_cfg.min_tile_coverage
        min_valid_pixel_fraction = (
            min_valid_pixel_fraction if min_valid_pixel_fraction is not None else analysis_cfg.min_valid_pixel_fraction
        )
        min_adjusted_score = min_adjusted_score if min_adjusted_score is not None else analysis_cfg.min_adjusted_score
        max_candidates = max_candidates if max_candidates is not None else analysis_cfg.max_candidates
        cluster_distance_m = cluster_distance_m if cluster_distance_m is not None else analysis_cfg.cluster_distance_m

        if not pack.optical and not pack.sar:
            raise ValueError("The raster pack must include at least one optical or SAR series.")

        tiles = tile_aoi(
            aoi,
            tile_size_m=tile_size_m,
            tile_step_m=tile_step_m,
            min_tile_coverage=min_tile_coverage,
        )
        records: list[CandidateRecord] = []
        processed_tiles = 0

        with open_local_raster_pack(pack) as rasters:
            source_dates = pack.source_labels()
            for tile in tiles:
                try:
                    extracted = extract_tile_features(
                        rasters=rasters,
                        tile_geometry_wgs84=tile.geometry_wgs84,
                        centroid_lat=tile.centroid.lat,
                        cfg=self.settings.features,
                    )
                except RasterReadError:
                    continue

                if extracted.evidence.data_quality < min_valid_pixel_fraction:
                    continue

                hits = matched_red_zones(tile.geometry_wgs84, self.red_zones)
                red_zone_names = [match.zone_name for match in hits]
                candidate = self._make_candidate(tile, extracted, source_dates, red_zone_names)

                records.append(
                    CandidateRecord(
                        candidate=candidate,
                        footprint_wgs84=tile.geometry_wgs84,
                        coverage_fraction=tile.coverage_fraction,
                        metrics=extracted.metrics,
                        red_zone_names=red_zone_names,
                    )
                )
                processed_tiles += 1

        ranked_all = self.pipeline.evaluate([record.candidate for record in records], permit_mode)
        ranked = [item for item in ranked_all if item.adjusted_score >= min_adjusted_score][:max_candidates]

        allowed_ids = {item.candidate_id for item in ranked}
        filtered_records = [record for record in records if record.candidate.candidate_id in allowed_ids]
        ranked_by_id = {item.candidate_id: item for item in ranked}
        ranked_pairs = [
            (record, ranked_by_id[record.candidate.candidate_id])
            for record in filtered_records
            if record.candidate.candidate_id in ranked_by_id
        ]
        clusters = cluster_ranked_records(
            ranked_pairs,
            permit_mode=permit_mode,
            guardrails=self.settings.guardrails,
            cluster_distance_m=cluster_distance_m,
            cluster_min_members=self.settings.analysis.cluster_min_members,
        )

        return AOIAnalysisResult(
            records=filtered_records,
            ranked=ranked,
            clusters=clusters,
            permit_mode=permit_mode,
            guardrail_config=self.settings.guardrails,
            total_tiles=len(tiles),
            processed_tiles=processed_tiles,
        )
