from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import folium
import json
from shapely.geometry import mapping

from .analysis import AOIAnalysisResult, CandidateRecord
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


def save_raw_candidates(path: str | Path, result: AOIAnalysisResult) -> None:
    path = Path(path)
    payload: list[dict[str, Any]] = []
    for record, ranked in result.ranked_record_pairs():
        item = record.to_feature_dict()
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


def save_geojson(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_analysis_summary(path: str | Path, result: AOIAnalysisResult) -> None:
    path = Path(path)
    payload = {
        "permit_mode": result.permit_mode.value,
        "total_tiles": result.total_tiles,
        "processed_tiles": result.processed_tiles,
        "ranked_candidates": len(result.ranked),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _popup_html(properties: dict[str, Any]) -> str:
    reasons = properties.get("reasons") or []
    reasons_html = "<br>".join(f"• {reason}" for reason in reasons)
    return (
        f"<b>{properties['candidate_id']}</b><br>"
        f"Score: {properties['adjusted_score']} ({properties['confidence']})<br>"
        f"Landscape: {properties['landscape']}<br>"
        f"Sensitivity: {properties['sensitivity']}<br>"
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

    geojson = ranked_geojson(result)
    for feature in geojson.get("features", []):
        props = feature["properties"]
        color = CONFIDENCE_COLORS.get(props["confidence"], "blue")
        geometry = feature["geometry"]
        if geometry["type"] == "Point":
            lon, lat = geometry["coordinates"]
            folium.CircleMarker(
                location=[lat, lon],
                radius=6,
                color=color,
                fill=True,
                fill_opacity=0.9,
                popup=folium.Popup(_popup_html(props), max_width=450),
                tooltip=f"{props['candidate_id']} · {props['adjusted_score']}",
            ).add_to(m)
        else:
            folium.GeoJson(
                data=feature,
                style_function=lambda _feature, c=color: {"color": c, "weight": 2, "fillOpacity": 0.15},
                popup=folium.Popup(_popup_html(props), max_width=450),
                tooltip=f"{props['candidate_id']} · {props['adjusted_score']}",
            ).add_to(m)

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
    map_path = output_root / "review_map.html"
    summary_path = output_root / "analysis_summary.json"

    save_raw_candidates(raw_path, result)
    save_ranked(ranked_json_path, [item.to_dict() for item in result.ranked])
    save_geojson(geojson_path, ranked_geojson(result))
    save_review_map(map_path, aoi, result, red_zones=red_zones)
    save_analysis_summary(summary_path, result)

    return {
        "raw_candidates": raw_path,
        "ranked_json": ranked_json_path,
        "geojson": geojson_path,
        "review_map": map_path,
        "summary": summary_path,
    }
