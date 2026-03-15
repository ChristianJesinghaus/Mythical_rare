from __future__ import annotations

from pathlib import Path
from typing import Any

import folium
import json
from shapely.geometry import mapping

from .analysis import AOIAnalysisResult
from .clustering import CandidateCluster
from .aoi import AOI
from .guardrails import RedZoneRule
from .io import save_ranked
from .models import PermitMode


CONFIDENCE_COLORS = {
    "high": "darkred",
    "medium": "orange",
    "low": "blue",
    "very-low": "gray",
}


def _cluster_lookup(result: AOIAnalysisResult) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for cluster in result.clusters:
        for member_id in cluster.member_ids:
            lookup[member_id] = cluster.cluster_id
    return lookup


def save_raw_candidates(path: str | Path, result: AOIAnalysisResult) -> None:
    path = Path(path)
    payload: list[dict[str, Any]] = []
    cluster_lookup = _cluster_lookup(result)
    for record, ranked in result.ranked_record_pairs():
        item = record.to_feature_dict()
        item["cluster_id"] = cluster_lookup.get(ranked.candidate_id)
        if result.permit_mode == PermitMode.AUTHORIZED and ranked.exact_location is not None:
            item["lat"] = ranked.exact_location.lat
            item["lon"] = ranked.exact_location.lon
            item["location_mode"] = "exact"
        else:
            item["lat"] = ranked.public_location.lat if ranked.public_location is not None else None
            item["lon"] = ranked.public_location.lon if ranked.public_location is not None else None
            item["location_mode"] = "redacted"
        payload.append(item)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def ranked_geojson(result: AOIAnalysisResult) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    cluster_lookup = _cluster_lookup(result)
    for record, ranked in result.ranked_record_pairs():
        if result.permit_mode == PermitMode.AUTHORIZED:
            geometry = mapping(record.footprint_wgs84)
        else:
            location = ranked.public_location
            if location is None:
                continue
            geometry = {
                "type": "Point",
                "coordinates": [location.lon, location.lat],
            }
        properties = {
            "candidate_id": ranked.candidate_id,
            "cluster_id": cluster_lookup.get(ranked.candidate_id),
            "raw_score": ranked.raw_score,
            "adjusted_score": ranked.adjusted_score,
            "confidence": ranked.confidence,
            "reasons": ranked.reasons,
            "landscape": ranked.landscape,
            "sensitivity": ranked.sensitivity,
            "tags": ranked.tags,
            "source_dates": ranked.source_dates,
            "red_zone_names": record.red_zone_names,
            "coverage_fraction": round(record.coverage_fraction, 4),
        }
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": properties,
        })
    return {"type": "FeatureCollection", "features": features}


def clusters_geojson(result: AOIAnalysisResult) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for cluster in result.clusters:
        if result.permit_mode == PermitMode.AUTHORIZED:
            geometry = mapping(cluster.footprint_wgs84)
        else:
            location = cluster.public_location
            if location is None:
                continue
            geometry = {
                "type": "Point",
                "coordinates": [location.lon, location.lat],
            }
        properties = {
            "cluster_id": cluster.cluster_id,
            "member_ids": cluster.member_ids,
            "member_count": cluster.member_count,
            "cluster_score": cluster.cluster_score,
            "max_adjusted_score": cluster.max_adjusted_score,
            "mean_adjusted_score": cluster.mean_adjusted_score,
            "confidence": cluster.confidence,
            "dominant_landscape": cluster.dominant_landscape,
            "sensitivity": cluster.sensitivity,
            "top_candidate_id": cluster.top_candidate_id,
            "area_ha": round(cluster.area_ha, 3),
            "red_zone_names": cluster.red_zone_names,
            "tags": cluster.tags,
            "reasons": cluster.reasons,
            "source_dates": cluster.source_dates,
        }
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": properties,
        })
    return {"type": "FeatureCollection", "features": features}


def save_geojson(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_clusters_json(path: str | Path, clusters: list[CandidateCluster]) -> None:
    path = Path(path)
    payload = [cluster.to_dict() for cluster in clusters]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_analysis_summary(path: str | Path, result: AOIAnalysisResult) -> None:
    path = Path(path)
    top_cluster = result.clusters[0] if result.clusters else None
    payload = {
        "permit_mode": result.permit_mode.value,
        "total_tiles": result.total_tiles,
        "processed_tiles": result.processed_tiles,
        "ranked_candidates": len(result.ranked),
        "clusters": len(result.clusters),
        "largest_cluster_member_count": max((cluster.member_count for cluster in result.clusters), default=0),
        "top_cluster_id": top_cluster.cluster_id if top_cluster else None,
        "top_cluster_score": top_cluster.cluster_score if top_cluster else None,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _candidate_popup_html(properties: dict[str, Any]) -> str:
    reasons = properties.get("reasons") or []
    reasons_html = "<br>".join(f"• {reason}" for reason in reasons)
    return (
        f"<b>{properties['candidate_id']}</b><br>"
        f"Cluster: {properties.get('cluster_id') or '—'}<br>"
        f"Score: {properties['adjusted_score']} ({properties['confidence']})<br>"
        f"Landscape: {properties['landscape']}<br>"
        f"Sensitivity: {properties['sensitivity']}<br>"
        f"Reasons:<br>{reasons_html or '—'}"
    )


def _cluster_popup_html(properties: dict[str, Any]) -> str:
    reasons = properties.get("reasons") or []
    reasons_html = "<br>".join(f"• {reason}" for reason in reasons)
    return (
        f"<b>{properties['cluster_id']}</b><br>"
        f"Cluster score: {properties['cluster_score']} ({properties['confidence']})<br>"
        f"Members: {properties['member_count']}<br>"
        f"Top candidate: {properties['top_candidate_id']}<br>"
        f"Landscape: {properties['dominant_landscape']}<br>"
        f"Area (ha): {properties['area_ha']}<br>"
        f"Reasons:<br>{reasons_html or '—'}"
    )


def save_review_map(
    path: str | Path,
    aoi: AOI,
    result: AOIAnalysisResult,
    red_zones: list[RedZoneRule] | None = None,
) -> None:
    center = aoi.centroid
    m = folium.Map(location=[center.lat, center.lon], zoom_start=10, control_scale=True)

    folium.GeoJson(
        data={"type": "Feature", "geometry": mapping(aoi.geometry_wgs84), "properties": {"name": "AOI"}},
        name="AOI",
        style_function=lambda _feature: {"color": "black", "weight": 2, "fill": False},
    ).add_to(m)

    cluster_layer = folium.FeatureGroup(name="Clusters", show=True)
    candidate_layer = folium.FeatureGroup(name="Candidate tiles", show=(result.permit_mode == PermitMode.AUTHORIZED))

    cluster_geo = clusters_geojson(result)
    for feature in cluster_geo.get("features", []):
        props = feature["properties"]
        color = CONFIDENCE_COLORS.get(props["confidence"], "darkred")
        geometry = feature["geometry"]
        if geometry["type"] == "Point":
            lon, lat = geometry["coordinates"]
            folium.CircleMarker(
                location=[lat, lon],
                radius=max(7, 4 + int(props["member_count"])),
                color=color,
                fill=True,
                fill_opacity=0.85,
                popup=folium.Popup(_cluster_popup_html(props), max_width=500),
                tooltip=f"{props['cluster_id']} · {props['cluster_score']}",
            ).add_to(cluster_layer)
        else:
            folium.GeoJson(
                data=feature,
                style_function=lambda _feature, c=color: {"color": c, "weight": 3, "fillOpacity": 0.12},
                popup=folium.Popup(_cluster_popup_html(props), max_width=500),
                tooltip=f"{props['cluster_id']} · {props['cluster_score']}",
            ).add_to(cluster_layer)

    candidate_geo = ranked_geojson(result)
    for feature in candidate_geo.get("features", []):
        props = feature["properties"]
        color = CONFIDENCE_COLORS.get(props["confidence"], "blue")
        geometry = feature["geometry"]
        if geometry["type"] == "Point":
            lon, lat = geometry["coordinates"]
            folium.CircleMarker(
                location=[lat, lon],
                radius=5,
                color=color,
                fill=True,
                fill_opacity=0.75,
                popup=folium.Popup(_candidate_popup_html(props), max_width=450),
                tooltip=f"{props['candidate_id']} · {props['adjusted_score']}",
            ).add_to(candidate_layer)
        else:
            folium.GeoJson(
                data=feature,
                style_function=lambda _feature, c=color: {"color": c, "weight": 1.5, "fillOpacity": 0.08},
                popup=folium.Popup(_candidate_popup_html(props), max_width=450),
                tooltip=f"{props['candidate_id']} · {props['adjusted_score']}",
            ).add_to(candidate_layer)

    cluster_layer.add_to(m)
    candidate_layer.add_to(m)

    if result.permit_mode == PermitMode.AUTHORIZED:
        for zone in red_zones or []:
            if zone.geometry is None:
                continue
            folium.GeoJson(
                data={"type": "Feature", "geometry": mapping(zone.geometry), "properties": {"name": zone.name}},
                name=f"Red zone: {zone.name}",
                style_function=lambda _feature: {"color": "red", "weight": 2, "fillOpacity": 0.05},
                tooltip=zone.name,
            ).add_to(m)

    folium.LayerControl().add_to(m)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    m.save(str(path))


def save_markdown_report(path: str | Path, aoi: AOI, result: AOIAnalysisResult) -> None:
    path = Path(path)
    lines: list[str] = []
    lines.append("# Phase 4 analysis report")
    lines.append("")
    lines.append(f"- Permit mode: `{result.permit_mode.value}`")
    lines.append(f"- AOI centroid: `{aoi.centroid.lat:.5f}, {aoi.centroid.lon:.5f}`")
    lines.append(f"- Tiles processed: `{result.processed_tiles}` / `{result.total_tiles}`")
    lines.append(f"- Ranked candidate tiles: `{len(result.ranked)}`")
    lines.append(f"- Candidate clusters: `{len(result.clusters)}`")
    lines.append("")
    lines.append("## Top clusters")
    lines.append("")
    if not result.clusters:
        lines.append("No clusters were exported.")
    else:
        for cluster in result.clusters[:10]:
            lines.append(f"### {cluster.cluster_id}")
            lines.append("")
            location = cluster.exact_location if result.permit_mode == PermitMode.AUTHORIZED else cluster.public_location
            if location is not None:
                lines.append(f"- Location: `{location.lat:.5f}, {location.lon:.5f}` ({'exact' if result.permit_mode == PermitMode.AUTHORIZED else 'redacted'})")
            lines.append(f"- Cluster score: `{cluster.cluster_score:.3f}` ({cluster.confidence})")
            lines.append(f"- Members: `{cluster.member_count}`")
            lines.append(f"- Dominant landscape: `{cluster.dominant_landscape}`")
            lines.append(f"- Top candidate: `{cluster.top_candidate_id}`")
            lines.append(f"- Area: `{cluster.area_ha:.2f}` ha")
            if cluster.red_zone_names:
                lines.append(f"- Red zones: {', '.join(cluster.red_zone_names)}")
            if cluster.tags:
                lines.append(f"- Tags: {', '.join(cluster.tags)}")
            if cluster.reasons:
                lines.append("- Reasons:")
                for reason in cluster.reasons:
                    lines.append(f"  - {reason}")
            lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("Use clusters first for triage, then inspect member tiles and the underlying rasters. This output is for non-invasive remote review only.")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_analysis_bundle(
    output_dir: str | Path,
    aoi: AOI,
    result: AOIAnalysisResult,
    red_zones: list[RedZoneRule] | None = None,
) -> dict[str, Path]:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    raw_path = output_root / "raw_candidates.json"
    ranked_json_path = output_root / "ranked_candidates.json"
    geojson_path = output_root / "ranked_candidates.geojson"
    clusters_json_path = output_root / "ranked_clusters.json"
    clusters_geojson_path = output_root / "ranked_clusters.geojson"
    map_path = output_root / "review_map.html"
    summary_path = output_root / "analysis_summary.json"
    report_path = output_root / "analysis_report.md"

    save_raw_candidates(raw_path, result)
    save_ranked(ranked_json_path, [item.to_dict() for item in result.ranked])
    save_geojson(geojson_path, ranked_geojson(result))
    save_clusters_json(clusters_json_path, result.clusters)
    save_geojson(clusters_geojson_path, clusters_geojson(result))
    save_review_map(map_path, aoi, result, red_zones=red_zones)
    save_analysis_summary(summary_path, result)
    save_markdown_report(report_path, aoi, result)

    return {
        "raw_candidates": raw_path,
        "ranked_json": ranked_json_path,
        "geojson": geojson_path,
        "clusters_json": clusters_json_path,
        "clusters_geojson": clusters_geojson_path,
        "review_map": map_path,
        "summary": summary_path,
        "report": report_path,
    }
