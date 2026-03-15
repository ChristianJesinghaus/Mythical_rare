from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, radians
from pathlib import Path
from typing import Any

import json
import numpy as np
import rasterio
from rasterio.io import DatasetReader
from scipy import ndimage as ndi
from skimage.draw import line as draw_line
from skimage.feature import canny
from skimage.transform import probabilistic_hough_line

from .config import ContextLayerConfig
from .datapack import LocalRasterPack, RasterAsset


EPS = 1e-6


@dataclass(slots=True)
class ContextLayerBuildResult:
    pack_dir: Path
    outputs: dict[str, Path | None] = field(default_factory=dict)
    created: list[Path] = field(default_factory=list)
    reused: list[Path] = field(default_factory=list)
    context_manifest: Path | None = None


class ContextLayerError(RuntimeError):
    pass


def _read_raster(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float32")
        nodata = src.nodata
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)
        profile = src.profile.copy()
    return arr, profile


def _write_raster(path: Path, array: np.ndarray, profile: dict[str, Any]) -> Path:
    output = path
    output.parent.mkdir(parents=True, exist_ok=True)
    nodata = -9999.0
    data = np.where(np.isfinite(array), array, nodata).astype("float32")
    out_profile = profile.copy()
    out_profile.update(
        driver="GTiff",
        count=1,
        dtype="float32",
        nodata=nodata,
        compress=profile.get("compress") or "deflate",
    )
    with rasterio.open(output, "w", **out_profile) as dst:
        dst.write(data, 1)
    return output


def _safe_nanmedian(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    return float(np.nanmedian(finite))


def _fill_nan(array: np.ndarray) -> np.ndarray:
    if array.size == 0:
        return array.astype("float32", copy=True)
    fill = _safe_nanmedian(array)
    return np.where(np.isfinite(array), array, fill).astype("float32")


def _normalize_valid(array: np.ndarray, q_low: float = 5.0, q_high: float = 95.0) -> np.ndarray:
    values = array[np.isfinite(array)]
    if values.size < 10:
        return np.zeros(array.shape, dtype="float32")
    lo = float(np.percentile(values, q_low))
    hi = float(np.percentile(values, q_high))
    scale = max(hi - lo, EPS)
    normalized = (array - lo) / scale
    normalized = np.clip(normalized, 0.0, 1.0)
    normalized[~np.isfinite(array)] = np.nan
    return normalized.astype("float32")


def _stack_series(paths: list[Path]) -> np.ndarray | None:
    if not paths:
        return None
    arrays = []
    for path in paths:
        arr, _ = _read_raster(path)
        arrays.append(arr)
    if not arrays:
        return None
    return np.stack(arrays).astype("float32")


def _reference_profile(pack: LocalRasterPack) -> dict[str, Any]:
    with rasterio.open(pack.dem) as src:
        return src.profile.copy()


def _pixel_sizes_m(dataset: DatasetReader) -> tuple[float, float]:
    x_size = abs(dataset.transform.a)
    y_size = abs(dataset.transform.e)
    if dataset.crs and dataset.crs.is_geographic:
        bounds = dataset.bounds
        lat = (bounds.top + bounds.bottom) / 2.0
        x_size *= 111_320.0 * max(cos(radians(lat)), 0.1)
        y_size *= 111_320.0
    return max(x_size, EPS), max(y_size, EPS)


def _slope_degrees(dem: np.ndarray, dataset: DatasetReader) -> np.ndarray:
    filled = _fill_nan(dem)
    px, py = _pixel_sizes_m(dataset)
    dz_dy, dz_dx = np.gradient(filled, py, px)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype("float32")
    slope[~np.isfinite(dem)] = np.nan
    return slope


def _mean_surface(arrays: np.ndarray | None) -> np.ndarray | None:
    if arrays is None or arrays.size == 0:
        return None
    with np.errstate(invalid="ignore"):
        surface = np.nanmean(arrays.astype("float32"), axis=0)
    if np.isnan(surface).all():
        return None
    return surface.astype("float32")


def _compute_quality(pack: LocalRasterPack, reference_profile: dict[str, Any]) -> np.ndarray | None:
    series_paths: list[Path] = [asset.path for asset in pack.optical]
    series_paths.extend(asset.path for asset in pack.sar)
    series_paths.extend(asset.path for asset in pack.historical)
    if not series_paths:
        return None
    stack = _stack_series(series_paths)
    if stack is None:
        return None
    quality = np.isfinite(stack).sum(axis=0).astype("float32") / max(stack.shape[0], 1)
    quality[~np.isfinite(np.nanmean(stack, axis=0))] = np.nan
    return quality.astype("float32")


def _compute_forest(pack: LocalRasterPack, cfg: ContextLayerConfig) -> np.ndarray | None:
    optical_stack = _stack_series([asset.path for asset in pack.optical])
    if optical_stack is None:
        return None
    median_surface = np.nanmedian(optical_stack, axis=0).astype("float32")
    if np.isnan(median_surface).all():
        return None

    finite = median_surface[np.isfinite(median_surface)]
    if finite.size < 10:
        return np.zeros(median_surface.shape, dtype="float32")

    if float(np.nanmin(finite)) >= -1.2 and float(np.nanmax(finite)) <= 1.2:
        forest = np.clip((median_surface - cfg.forest_threshold) / max(1.0 - cfg.forest_threshold, 0.05), 0.0, 1.0)
    else:
        forest = _normalize_valid(median_surface)
        cutoff = float(np.nanquantile(forest[np.isfinite(forest)], 0.8))
        forest = np.clip((forest - cutoff) / max(1.0 - cutoff, 0.05), 0.0, 1.0)

    forest = ndi.gaussian_filter(np.nan_to_num(forest, nan=0.0), sigma=cfg.forest_smoothing_sigma_px)
    forest[~np.isfinite(median_surface)] = np.nan
    return forest.astype("float32")


def _compute_confounder(dem: np.ndarray, dataset: DatasetReader, cfg: ContextLayerConfig) -> np.ndarray:
    filled = _fill_nan(dem)
    slope = _slope_degrees(dem, dataset)
    slope_norm = np.clip(slope / 25.0, 0.0, 1.0)

    relief_sigma = max(cfg.relief_sigma_px, 1.0)
    local_relief = filled - ndi.gaussian_filter(filled, sigma=relief_sigma)
    roughness = _normalize_valid(np.abs(local_relief))

    curvature = ndi.gaussian_laplace(filled, sigma=max(cfg.curvature_sigma_px, 1.0)).astype("float32")
    concave = _normalize_valid(-curvature)

    confounder = 0.55 * np.nan_to_num(slope_norm, nan=0.0) + 0.30 * np.nan_to_num(roughness, nan=0.0) + 0.15 * np.nan_to_num(concave, nan=0.0)
    confounder = np.clip(confounder, 0.0, 1.0)
    confounder[~np.isfinite(dem)] = np.nan
    return confounder.astype("float32")


def _compute_water_proximity(dem: np.ndarray, dataset: DatasetReader, cfg: ContextLayerConfig) -> np.ndarray:
    filled = _fill_nan(dem)
    slope = _slope_degrees(dem, dataset)
    slope_norm = np.clip(slope / 20.0, 0.0, 1.0)

    valley_sigma = max(cfg.valley_sigma_px, 1.0)
    relative_elevation = filled - ndi.gaussian_filter(filled, sigma=valley_sigma)
    lowland = _normalize_valid(-relative_elevation)
    gentle = 1.0 - np.nan_to_num(slope_norm, nan=1.0)
    wetness = np.clip(0.65 * np.nan_to_num(lowland, nan=0.0) + 0.35 * gentle, 0.0, 1.0)

    wet_values = wetness[np.isfinite(wetness)]
    if wet_values.size < 10:
        result = np.zeros(wetness.shape, dtype="float32")
        result[~np.isfinite(dem)] = np.nan
        return result

    threshold = float(np.quantile(wet_values, np.clip(cfg.water_seed_quantile, 0.5, 0.99)))
    seed_mask = wetness >= threshold
    seed_mask = ndi.binary_opening(seed_mask, structure=np.ones((2, 2), dtype=bool))
    seed_mask = ndi.binary_closing(seed_mask, structure=np.ones((3, 3), dtype=bool))
    if seed_mask.sum() == 0:
        seed_mask = wetness >= float(np.quantile(wet_values, 0.8))

    px, py = _pixel_sizes_m(dataset)
    distance = ndi.distance_transform_edt(~seed_mask, sampling=(py, px)).astype("float32")
    proximity = np.exp(-distance / max(cfg.water_distance_scale_m, 1.0))
    proximity = np.clip(proximity, 0.0, 1.0)
    proximity[seed_mask] = 1.0
    proximity[~np.isfinite(dem)] = np.nan
    return proximity.astype("float32")


def _draw_segments(shape: tuple[int, int], segments: list[tuple[tuple[int, int], tuple[int, int]]]) -> np.ndarray:
    mask = np.zeros(shape, dtype="float32")
    for (x0, y0), (x1, y1) in segments:
        rr, cc = draw_line(int(y0), int(x0), int(y1), int(x1))
        rr = np.clip(rr, 0, shape[0] - 1)
        cc = np.clip(cc, 0, shape[1] - 1)
        mask[rr, cc] = 1.0
    return mask


def _compute_disturbance(pack: LocalRasterPack, cfg: ContextLayerConfig) -> np.ndarray | None:
    layers: list[np.ndarray] = []
    for assets in (pack.optical, pack.sar):
        stack = _stack_series([asset.path for asset in assets])
        if stack is None:
            continue
        surface = _mean_surface(stack)
        if surface is None:
            continue
        layers.append(_normalize_valid(surface))

    if not layers:
        return None

    base_surface = np.nanmean(np.stack([np.nan_to_num(layer, nan=np.nanmedian(layer[np.isfinite(layer)]) if np.isfinite(layer).any() else 0.0) for layer in layers]), axis=0)
    filled = _fill_nan(base_surface)

    gradient = ndi.gaussian_gradient_magnitude(filled, sigma=max(cfg.disturbance_sigma_px, 0.5)).astype("float32")
    gradient_norm = _normalize_valid(gradient)

    mu = ndi.gaussian_filter(filled, sigma=max(cfg.disturbance_variance_sigma_px, 1.0))
    mu2 = ndi.gaussian_filter(filled ** 2, sigma=max(cfg.disturbance_variance_sigma_px, 1.0))
    variance = np.clip(mu2 - mu ** 2, 0.0, None).astype("float32")
    variance_norm = _normalize_valid(variance)

    edges = canny(filled.astype("float32"), sigma=max(cfg.disturbance_canny_sigma, 0.5))
    min_dim = min(filled.shape)
    segments = probabilistic_hough_line(
        edges,
        threshold=5,
        line_length=max(8, min_dim // 20),
        line_gap=3,
    )
    line_mask = _draw_segments(filled.shape, segments)
    line_density = ndi.gaussian_filter(line_mask, sigma=max(cfg.disturbance_line_sigma_px, 0.5)).astype("float32")
    line_norm = _normalize_valid(line_density)

    disturbance = 0.45 * np.nan_to_num(gradient_norm, nan=0.0) + 0.25 * np.nan_to_num(variance_norm, nan=0.0) + 0.30 * np.nan_to_num(line_norm, nan=0.0)
    disturbance = np.clip(disturbance, 0.0, 1.0)
    disturbance[~np.isfinite(base_surface)] = np.nan
    return disturbance.astype("float32")


def _update_pack_manifest(pack_dir: Path, updates: dict[str, str | None]) -> None:
    manifest_path = pack_dir / "pack_manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        payload = {"outputs": {}}

    payload.setdefault("outputs", {})
    payload["outputs"].update(updates)
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_context_layers(
    pack_dir: str | Path,
    cfg: ContextLayerConfig,
    *,
    overwrite: bool = False,
) -> ContextLayerBuildResult:
    pack = LocalRasterPack.from_directory(pack_dir)
    reference_profile = _reference_profile(pack)
    result = ContextLayerBuildResult(pack_dir=Path(pack_dir))

    existing_paths = {
        "disturbance": pack.disturbance,
        "confounder": pack.confounder,
        "water_proximity": pack.water_proximity,
        "quality": pack.quality,
        "forest": pack.forest,
    }

    dem, _ = _read_raster(pack.dem)
    with rasterio.open(pack.dem) as dem_ds:
        confounder_arr = None
        water_arr = None
        for name, existing in existing_paths.items():
            if existing is not None and existing.exists() and not overwrite:
                result.outputs[name] = existing
                result.reused.append(existing)

        if overwrite or result.outputs.get("confounder") is None:
            confounder_arr = _compute_confounder(dem, dem_ds, cfg)
            path = result.pack_dir / "confounder.tif"
            result.outputs["confounder"] = _write_raster(path, confounder_arr, reference_profile)
            result.created.append(path)

        if overwrite or result.outputs.get("water_proximity") is None:
            water_arr = _compute_water_proximity(dem, dem_ds, cfg)
            path = result.pack_dir / "water_proximity.tif"
            result.outputs["water_proximity"] = _write_raster(path, water_arr, reference_profile)
            result.created.append(path)

    if overwrite or result.outputs.get("forest") is None:
        forest_arr = _compute_forest(pack, cfg)
        if forest_arr is None:
            forest_arr = np.zeros(dem.shape, dtype="float32")
            forest_arr[~np.isfinite(dem)] = np.nan
        path = result.pack_dir / "forest.tif"
        result.outputs["forest"] = _write_raster(path, forest_arr, reference_profile)
        result.created.append(path)

    if overwrite or result.outputs.get("disturbance") is None:
        disturbance_arr = _compute_disturbance(pack, cfg)
        if disturbance_arr is None:
            disturbance_arr = np.zeros(dem.shape, dtype="float32")
            disturbance_arr[~np.isfinite(dem)] = np.nan
        path = result.pack_dir / "disturbance.tif"
        result.outputs["disturbance"] = _write_raster(path, disturbance_arr, reference_profile)
        result.created.append(path)

    if overwrite or result.outputs.get("quality") is None:
        quality_arr = _compute_quality(pack, reference_profile)
        if quality_arr is not None:
            path = result.pack_dir / "quality.tif"
            result.outputs["quality"] = _write_raster(path, quality_arr, reference_profile)
            result.created.append(path)
        else:
            result.outputs["quality"] = None

    _update_pack_manifest(
        result.pack_dir,
        {
            key: str(value) if value is not None else None
            for key, value in result.outputs.items()
        },
    )

    manifest_path = result.pack_dir / "context_manifest.json"
    manifest = {
        "created": [str(path) for path in result.created],
        "reused": [str(path) for path in result.reused],
        "outputs": {
            key: str(value) if value is not None else None
            for key, value in result.outputs.items()
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    result.context_manifest = manifest_path
    return result


__all__ = [
    "ContextLayerBuildResult",
    "ContextLayerError",
    "build_context_layers",
]
