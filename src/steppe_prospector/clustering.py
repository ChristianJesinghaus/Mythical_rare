from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union
from pyproj import Transformer

from .aoi import AOI, local_metric_crs
from .config import GuardrailConfig
from .features import clamp01
from .guardrails import blur_coordinate
from .models import Coordinate, PermitMode, SensitivityLevel
from .scoring import confidence_band


@dataclass(slots=True)
class CandidateCluster:
    cluster_id: str
    member_ids: list[str]
    exact_location: Coordinate
    public_location: Coordinate | None
    footprint_wgs84: BaseGeometry
    dominant_landscape: str
    sensitivity: str
    cluster_score: float
    max_adjusted_score: float
    mean_adjusted_score: float
    confidence: str
    member_count: int
    area_ha: float
    top_candidate_id: str
    red_zone_names: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    source_dates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "member_ids": self.member_ids,
            "member_count": self.member_count,
            "cluster_score": round(self.cluster_score, 4),
            "max_adjusted_score": round(self.max_adjusted_score, 4),
            "mean_adjusted_score": round(self.mean_adjusted_score, 4),
            "confidence": self.confidence,
            "dominant_landscape": self.dominant_landscape,
            "sensitivity": self.sensitivity,
            "top_candidate_id": self.top_candidate_id,
            "area_ha": round(self.area_ha, 3),
            "lat": self.exact_location.lat if self.public_location is None else self.public_location.lat,
            "lon": self.exact_location.lon if self.public_location is None else self.public_location.lon,
            "location_mode": "exact" if self.public_location is None else "redacted",
            "red_zone_names": self.red_zone_names,
            "tags": self.tags,
            "reasons": self.reasons,
            "source_dates": self.source_dates,
        }


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1


def _transformer(src: str, dst: str):
    return Transformer.from_crs(src, dst, always_xy=True).transform


def _cluster_identifier(point: Coordinate, member_count: int) -> str:
    lat_code = f"{'n' if point.lat >= 0 else 's'}{abs(point.lat):08.4f}".replace(".", "")
    lon_code = f"{'e' if point.lon >= 0 else 'w'}{abs(point.lon):09.4f}".replace(".", "")
    return f"cluster-{lat_code}-{lon_code}-m{member_count:02d}"


def cluster_ranked_records(
    ranked_pairs: Iterable[tuple[object, object]],
    *,
    permit_mode: PermitMode,
    guardrails: GuardrailConfig,
    cluster_distance_m: float,
    cluster_min_members: int = 1,
) -> list[CandidateCluster]:
    items = list(ranked_pairs)
    if not items:
        return []

    all_geom = unary_union([record.footprint_wgs84 for record, _ranked in items])
    metric_crs = local_metric_crs(AOI(geometry_wgs84=all_geom.envelope))
    to_metric = _transformer("EPSG:4326", metric_crs)

    metric_geoms = [transform(to_metric, record.footprint_wgs84) for record, _ranked in items]
    metric_centroids = [geom.centroid for geom in metric_geoms]
    uf = _UnionFind(len(items))

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if metric_centroids[i].distance(metric_centroids[j]) <= cluster_distance_m:
                uf.union(i, j)

    components: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(items)):
        components[uf.find(idx)].append(idx)

    clusters: list[CandidateCluster] = []
    for indices in components.values():
        if len(indices) < max(cluster_min_members, 1):
            continue

        members = [items[idx] for idx in indices]
        member_records = [record for record, _ranked in members]
        member_ranked = [ranked for _record, ranked in members]

        union_wgs84 = unary_union([record.footprint_wgs84 for record in member_records])
        union_metric = unary_union([metric_geoms[idx] for idx in indices])
        centroid = union_wgs84.centroid
        exact_location = Coordinate(lat=float(centroid.y), lon=float(centroid.x))
        if permit_mode == PermitMode.AUTHORIZED:
            public_location = None
        elif permit_mode == PermitMode.RESTRICTED:
            public_location = blur_coordinate(exact_location, guardrails.restricted_coordinate_blur_m)
        else:
            public_location = blur_coordinate(exact_location, guardrails.public_coordinate_blur_m)

        dominant_landscape = Counter(ranked.landscape for ranked in member_ranked).most_common(1)[0][0]
        sensitivities = {ranked.sensitivity for ranked in member_ranked}
        if "sensitive" in sensitivities:
            sensitivity = SensitivityLevel.SENSITIVE.value
        elif "restricted" in sensitivities:
            sensitivity = SensitivityLevel.RESTRICTED.value
        else:
            sensitivity = SensitivityLevel.NORMAL.value

        sorted_ranked = sorted(member_ranked, key=lambda item: item.adjusted_score, reverse=True)
        top = sorted_ranked[0]
        mean_adjusted = sum(item.adjusted_score for item in member_ranked) / max(len(member_ranked), 1)
        support_bonus = clamp01((len(member_ranked) - 1) / 4.0)
        cluster_score = clamp01(0.65 * top.adjusted_score + 0.25 * mean_adjusted + 0.10 * support_bonus)

        reasons: list[str] = []
        seen_reason: set[str] = set()
        default_reason = f"cluster supported by {len(member_ranked)} adjacent tile(s)"
        for reason in [default_reason] + [reason for ranked in sorted_ranked[:3] for reason in ranked.reasons]:
            if reason not in seen_reason:
                reasons.append(reason)
                seen_reason.add(reason)
            if len(reasons) >= 8:
                break

        red_zone_names = sorted({name for record in member_records for name in record.red_zone_names})
        tags = sorted({tag for ranked in member_ranked for tag in ranked.tags})[:12]
        source_dates = sorted({date for ranked in member_ranked for date in ranked.source_dates})
        cluster_id = _cluster_identifier(exact_location, len(member_ranked))

        clusters.append(
            CandidateCluster(
                cluster_id=cluster_id,
                member_ids=[ranked.candidate_id for ranked in sorted_ranked],
                exact_location=exact_location,
                public_location=public_location,
                footprint_wgs84=union_wgs84,
                dominant_landscape=dominant_landscape,
                sensitivity=sensitivity,
                cluster_score=round(cluster_score, 4),
                max_adjusted_score=round(top.adjusted_score, 4),
                mean_adjusted_score=round(mean_adjusted, 4),
                confidence=confidence_band(cluster_score),
                member_count=len(member_ranked),
                area_ha=float(union_metric.area / 10_000.0),
                top_candidate_id=top.candidate_id,
                red_zone_names=red_zone_names,
                tags=tags,
                reasons=reasons,
                source_dates=source_dates,
            )
        )

    clusters.sort(key=lambda item: item.cluster_score, reverse=True)
    return clusters


__all__ = ["CandidateCluster", "cluster_ranked_records"]
