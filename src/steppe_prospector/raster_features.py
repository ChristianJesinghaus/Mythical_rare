from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, radians
from typing import Iterable

import numpy as np
from pyproj import Transformer
from rasterio.io import DatasetReader
from rasterio.mask import mask as rio_mask
from scipy import ndimage as ndi
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from skimage import measure
from skimage.feature import canny
from skimage.transform import probabilistic_hough_line, resize

from .config import FeatureEngineConfig
from .datapack import OpenLocalRasterPack, OpenRasterAsset
from .features import clamp01
from .models import CandidateEvidence, LandscapeClass


EPS = 1e-6


@dataclass(slots=True)
class TileFeatureResult:
    evidence: CandidateEvidence
    landscape: LandscapeClass
    metrics: dict[str, float]


@dataclass(slots=True)
class TerrainMetrics:
    microrelief: float
    terrain_ruggedness_risk: float
    median_slope_deg: float
    slope_p90_deg: float


class RasterReadError(RuntimeError):
    pass


def _reproject_geometry(geometry: BaseGeometry, dataset: DatasetReader) -> BaseGeometry:
    dataset_crs = dataset.crs or "EPSG:4326"
    if str(dataset_crs) == "EPSG:4326":
        return geometry
    transformer = Transformer.from_crs("EPSG:4326", dataset_crs, always_xy=True)
    return transform(transformer.transform, geometry)


def read_masked_array(dataset: DatasetReader, geometry_wgs84: BaseGeometry) -> np.ma.MaskedArray:
    geom = _reproject_geometry(geometry_wgs84, dataset)
    try:
        data, _ = rio_mask(dataset, [mapping(geom)], crop=True, filled=False, indexes=1)
    except ValueError:
        return np.ma.masked_all((0, 0), dtype="float32")

    array = np.ma.array(data, copy=False).astype("float32")
    if array.ndim == 3:
        array = array[0]
    if array.size == 0:
        return np.ma.masked_all((0, 0), dtype="float32")
    return array


def valid_fraction(array: np.ma.MaskedArray) -> float:
    if array.size == 0:
        return 0.0
    mask = np.ma.getmaskarray(array)
    return float(1.0 - mask.mean())


def _fill_with_median(array: np.ma.MaskedArray) -> np.ndarray:
    if array.size == 0:
        return np.zeros((1, 1), dtype="float32")
    values = array.compressed()
    fill_value = float(np.median(values)) if values.size else 0.0
    return np.where(np.ma.getmaskarray(array), fill_value, np.asarray(array, dtype="float32"))


def _robust_scale(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    scale = 1.4826 * mad if mad > EPS else float(np.std(values) + EPS)
    return median, max(scale, EPS)


def local_residual(array: np.ma.MaskedArray, sigma_px: float) -> np.ma.MaskedArray:
    if array.size == 0:
        return np.ma.masked_all((0, 0), dtype="float32")
    filled = _fill_with_median(array)
    smooth = ndi.gaussian_filter(filled, sigma=max(sigma_px, 0.5))
    residual = filled - smooth
    return np.ma.array(residual, mask=np.ma.getmaskarray(array))


def robust_anomaly_strength(array: np.ma.MaskedArray, z_cap: float) -> float:
    values = array.compressed().astype("float32")
    if values.size < 20:
        return 0.0
    median, scale = _robust_scale(values)
    z = np.abs(values - median) / scale
    return clamp01(float(np.percentile(z, 95)) / max(z_cap, EPS))


def anomaly_mask(array: np.ma.MaskedArray, z_threshold: float) -> np.ndarray:
    values = array.compressed().astype("float32")
    if values.size < 20:
        return np.zeros(array.shape, dtype=bool)
    median, scale = _robust_scale(values)
    filled = _fill_with_median(array)
    z = np.abs(filled - median) / scale
    mask = (z >= z_threshold) & ~np.ma.getmaskarray(array)
    mask = ndi.binary_opening(mask, structure=np.ones((2, 2), dtype=bool))
    mask = ndi.binary_closing(mask, structure=np.ones((3, 3), dtype=bool))
    return mask


def normalize01(array: np.ma.MaskedArray) -> np.ndarray:
    values = array.compressed().astype("float32")
    if values.size < 20:
        return np.zeros(array.shape, dtype="float32")
    lo = float(np.percentile(values, 5))
    hi = float(np.percentile(values, 95))
    scale = max(hi - lo, EPS)
    normalized = (_fill_with_median(array) - lo) / scale
    return np.clip(normalized, 0.0, 1.0)


def _resize_to(array: np.ndarray, shape: tuple[int, int], order: int = 1) -> np.ndarray:
    if array.shape == shape:
        return array
    if min(shape) < 2:
        return np.zeros(shape, dtype=array.dtype)
    return resize(
        array,
        output_shape=shape,
        order=order,
        anti_aliasing=(order > 0),
        preserve_range=True,
    ).astype(array.dtype)


def _common_shape(arrays: Iterable[np.ndarray]) -> tuple[int, int]:
    shapes = [arr.shape for arr in arrays if arr.size]
    if not shapes:
        return (0, 0)
    rows = min(shape[0] for shape in shapes)
    cols = min(shape[1] for shape in shapes)
    return rows, cols


def temporal_persistence_score(arrays: list[np.ma.MaskedArray], cfg: FeatureEngineConfig) -> float:
    if len(arrays) < 2:
        return 0.0
    masks = [anomaly_mask(local_residual(array, cfg.anomaly_sigma_px), cfg.temporal_anomaly_z) for array in arrays]
    shape = _common_shape(masks)
    if shape == (0, 0):
        return 0.0
    aligned = np.stack([_resize_to(mask.astype("float32"), shape, order=0) >= 0.5 for mask in masks])
    persistence = aligned.mean(axis=0)
    non_zero = persistence[persistence > 0]
    if non_zero.size == 0:
        return 0.0
    return clamp01(float(np.percentile(non_zero, 90)))


def _current_surface(
    optical: list[np.ma.MaskedArray],
    sar: list[np.ma.MaskedArray],
    terrain: np.ma.MaskedArray,
    cfg: FeatureEngineConfig,
) -> np.ndarray:
    layers: list[np.ndarray] = []
    for arrays in (optical, sar):
        if arrays:
            residuals = [normalize01(np.ma.abs(local_residual(array, cfg.anomaly_sigma_px))) for array in arrays]
            shape = _common_shape(residuals)
            if shape != (0, 0):
                aligned = np.stack([_resize_to(residual, shape) for residual in residuals])
                layers.append(aligned.mean(axis=0))
    if terrain.size:
        terrain_surface = normalize01(np.ma.abs(local_residual(terrain, cfg.dem_sigma_px)))
        if terrain_surface.size:
            layers.append(terrain_surface)
    if not layers:
        return np.zeros((1, 1), dtype="float32")
    shape = _common_shape(layers)
    aligned = np.stack([_resize_to(layer, shape) for layer in layers])
    return aligned.mean(axis=0)


def surface_mask(surface: np.ndarray, quantile: float) -> np.ndarray:
    if surface.size == 0:
        return np.zeros((1, 1), dtype=bool)
    values = surface[np.isfinite(surface)]
    if values.size < 20:
        return np.zeros(surface.shape, dtype=bool)
    threshold = float(np.quantile(values, np.clip(quantile, 0.5, 0.99)))
    mask = surface >= threshold
    mask = ndi.binary_opening(mask, structure=np.ones((2, 2), dtype=bool))
    mask = ndi.binary_closing(mask, structure=np.ones((3, 3), dtype=bool))
    return mask


def enclosure_score(surface: np.ndarray, mask: np.ndarray) -> float:
    if surface.size == 0 or mask.sum() < 10:
        return 0.0
    filled = ndi.binary_fill_holes(mask)
    labels = measure.label(filled)
    regions = measure.regionprops(labels)
    if not regions:
        return 0.0
    best = 0.0
    for region in regions:
        footprint_fraction = region.area / max(mask.size, 1)
        if footprint_fraction < 0.005 or footprint_fraction > 0.4:
            continue
        bbox_area = max((region.bbox[2] - region.bbox[0]) * (region.bbox[3] - region.bbox[1]), 1)
        perimeter = max(region.perimeter, 1.0)
        compactness = 4.0 * pi * region.area / (perimeter ** 2)
        extent = region.area / bbox_area
        size_pref = 1.0 - min(abs(footprint_fraction - 0.08) / 0.08, 1.0)
        candidate_score = 0.45 * clamp01(compactness) + 0.35 * clamp01(extent) + 0.20 * clamp01(size_pref)
        best = max(best, float(candidate_score))
    return clamp01(best)


def linearity_score(surface: np.ndarray, cfg: FeatureEngineConfig) -> float:
    if surface.size == 0:
        return 0.0
    edges = canny(surface.astype("float32"), sigma=max(cfg.edge_sigma, 0.5))
    if edges.sum() < 10:
        return 0.0
    min_dim = min(surface.shape)
    segments = probabilistic_hough_line(
        edges,
        threshold=5,
        line_length=max(5, min_dim // 6),
        line_gap=3,
    )
    if not segments:
        return 0.0
    total_length = 0.0
    for (x0, y0), (x1, y1) in segments:
        total_length += float(np.hypot(x1 - x0, y1 - y0))
    normalization = max(min_dim * 4.0, 1.0)
    return clamp01(total_length / normalization)


def historical_match_score(
    current_mask: np.ndarray,
    historical_arrays: list[np.ma.MaskedArray],
    cfg: FeatureEngineConfig,
) -> float:
    if current_mask.sum() < 10 or not historical_arrays:
        return 0.0
    historical_surfaces = [normalize01(np.ma.abs(local_residual(array, cfg.anomaly_sigma_px))) for array in historical_arrays]
    shape = _common_shape([current_mask.astype("float32")] + historical_surfaces)
    if shape == (0, 0):
        return 0.0
    hist_surface = np.mean(np.stack([_resize_to(surface, shape) for surface in historical_surfaces]), axis=0)
    hist_mask = surface_mask(hist_surface, cfg.mask_quantile)
    current_aligned = _resize_to(current_mask.astype("float32"), shape, order=0) >= 0.5
    intersection = float(np.logical_and(current_aligned, hist_mask).sum())
    union = float(np.logical_or(current_aligned, hist_mask).sum())
    if union <= 0:
        return 0.0
    return clamp01((intersection / union) * 2.0)


def _pixel_sizes_in_m(dataset: DatasetReader, lat: float) -> tuple[float, float]:
    x_size = abs(dataset.transform.a)
    y_size = abs(dataset.transform.e)
    if dataset.crs and dataset.crs.is_geographic:
        x_size *= 111_320.0 * max(cos(radians(lat)), 0.1)
        y_size *= 111_320.0
    return max(x_size, EPS), max(y_size, EPS)


def terrain_metrics(dem_array: np.ma.MaskedArray, dataset: DatasetReader, lat: float, cfg: FeatureEngineConfig) -> TerrainMetrics:
    if dem_array.size == 0 or dem_array.compressed().size < 20:
        return TerrainMetrics(microrelief=0.0, terrain_ruggedness_risk=0.5, median_slope_deg=0.0, slope_p90_deg=0.0)

    filled = _fill_with_median(dem_array)
    px, py = _pixel_sizes_in_m(dataset, lat)
    dz_dy, dz_dx = np.gradient(filled, py, px)
    slope_deg = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    mask = ~np.ma.getmaskarray(dem_array)
    slope_values = slope_deg[mask]
    if slope_values.size == 0:
        slope_values = np.array([0.0], dtype="float32")

    highpass = local_residual(dem_array, cfg.dem_sigma_px)
    roughness_std = float(np.std(highpass.compressed())) if highpass.compressed().size else 0.0
    dem_values = dem_array.compressed()
    terrain_relief = float(np.percentile(dem_values, 95) - np.percentile(dem_values, 5)) if dem_values.size else 0.0

    microrelief = clamp01(roughness_std / 1.5)
    ruggedness = 0.6 * clamp01(float(np.percentile(slope_values, 90)) / 20.0) + 0.4 * clamp01(terrain_relief / 30.0)
    return TerrainMetrics(
        microrelief=microrelief,
        terrain_ruggedness_risk=clamp01(ruggedness),
        median_slope_deg=float(np.median(slope_values)),
        slope_p90_deg=float(np.percentile(slope_values, 90)),
    )


def infer_landscape(
    terrain: TerrainMetrics,
    water_proximity_mean: float | None,
    forest_fraction: float | None,
) -> LandscapeClass:
    if forest_fraction is not None and forest_fraction >= 0.5:
        return LandscapeClass.FOREST
    if terrain.slope_p90_deg >= 18.0 or terrain.terrain_ruggedness_risk >= 0.65:
        return LandscapeClass.MOUNTAIN
    if water_proximity_mean is not None and water_proximity_mean >= 0.6 and terrain.median_slope_deg <= 10.0:
        return LandscapeClass.VALLEY
    if terrain.median_slope_deg <= 8.0:
        return LandscapeClass.STEPPE
    return LandscapeClass.UNKNOWN


def mean_normalized(array: np.ma.MaskedArray) -> float | None:
    values = array.compressed().astype("float32")
    if values.size < 10:
        return None
    lo = float(np.percentile(values, 5))
    hi = float(np.percentile(values, 95))
    scale = max(hi - lo, EPS)
    normalized = np.clip((values - lo) / scale, 0.0, 1.0)
    return float(np.mean(normalized))


def extract_tile_features(
    rasters: OpenLocalRasterPack,
    tile_geometry_wgs84: BaseGeometry,
    centroid_lat: float,
    cfg: FeatureEngineConfig,
) -> TileFeatureResult:
    optical_arrays = [read_masked_array(asset.dataset, tile_geometry_wgs84) for asset in rasters.optical]
    sar_arrays = [read_masked_array(asset.dataset, tile_geometry_wgs84) for asset in rasters.sar]
    historical_arrays = [read_masked_array(asset.dataset, tile_geometry_wgs84) for asset in rasters.historical]
    dem_array = read_masked_array(rasters.dem, tile_geometry_wgs84)

    if not any(array.compressed().size for array in optical_arrays + sar_arrays) and dem_array.compressed().size == 0:
        raise RasterReadError("No usable raster data intersected this tile.")

    optical_residuals = [local_residual(array, cfg.anomaly_sigma_px) for array in optical_arrays]
    sar_residuals = [local_residual(array, cfg.anomaly_sigma_px) for array in sar_arrays]

    optical_score = float(np.mean([robust_anomaly_strength(residual, cfg.anomaly_z_cap) for residual in optical_residuals])) if optical_residuals else 0.0
    sar_score = float(np.mean([robust_anomaly_strength(residual, cfg.anomaly_z_cap) for residual in sar_residuals])) if sar_residuals else 0.0

    terrain = terrain_metrics(dem_array, rasters.dem, centroid_lat, cfg)
    current_surface = _current_surface(optical_arrays, sar_arrays, dem_array, cfg)
    current_mask = surface_mask(current_surface, cfg.mask_quantile)

    enclosure = enclosure_score(current_surface, current_mask)
    linearity = linearity_score(current_surface, cfg)
    temporal_components = [
        score
        for score in [temporal_persistence_score(optical_arrays, cfg), temporal_persistence_score(sar_arrays, cfg)]
        if score > 0
    ]
    temporal = float(np.mean(temporal_components)) if temporal_components else 0.0
    historical = historical_match_score(current_mask, historical_arrays, cfg)

    disturbance_mean = mean_normalized(read_masked_array(rasters.disturbance, tile_geometry_wgs84)) if rasters.disturbance is not None else 0.0
    confounder_from_raster = mean_normalized(read_masked_array(rasters.confounder, tile_geometry_wgs84)) if rasters.confounder is not None else None
    water_proximity_mean = mean_normalized(read_masked_array(rasters.water_proximity, tile_geometry_wgs84)) if rasters.water_proximity is not None else None

    forest_fraction = None
    if rasters.forest is not None:
        forest_array = read_masked_array(rasters.forest, tile_geometry_wgs84)
        if forest_array.compressed().size:
            forest_fraction = float(np.mean(forest_array.compressed() > 0.5))

    natural_risk = terrain.terrain_ruggedness_risk if confounder_from_raster is None else clamp01(0.5 * terrain.terrain_ruggedness_risk + 0.5 * confounder_from_raster)

    slope_pref = clamp01(1.0 - max(terrain.median_slope_deg - 6.0, 0.0) / 18.0)
    water_score = 0.5 if water_proximity_mean is None else water_proximity_mean
    contextual_fit = clamp01(0.45 * slope_pref + 0.35 * water_score + 0.20 * (1.0 - natural_risk))

    quality_components = [valid_fraction(dem_array)]
    quality_components.extend(valid_fraction(array) for array in optical_arrays + sar_arrays + historical_arrays if array.size)
    if rasters.quality is not None:
        quality_mean = mean_normalized(read_masked_array(rasters.quality, tile_geometry_wgs84))
        if quality_mean is not None:
            quality_components.append(quality_mean)
    data_quality = clamp01(float(np.mean(quality_components))) if quality_components else 0.0

    notes: list[str] = []
    if len(optical_arrays) < 2 and len(sar_arrays) < 2:
        notes.append("limited multitemporal support")
    if not historical_arrays:
        notes.append("no historical layer in raster pack")
    if rasters.disturbance is None:
        notes.append("no explicit disturbance layer supplied")
    if data_quality < 0.45:
        notes.append("data quality is low; manual review should be conservative")

    landscape = infer_landscape(terrain, water_proximity_mean, forest_fraction)

    evidence = CandidateEvidence(
        optical_anomaly=clamp01(optical_score),
        sar_anomaly=clamp01(sar_score),
        microrelief=terrain.microrelief,
        enclosure_shape=clamp01(enclosure),
        linearity=clamp01(linearity),
        temporal_persistence=clamp01(temporal),
        historical_match=clamp01(historical),
        contextual_fit=clamp01(contextual_fit),
        modern_disturbance=clamp01(disturbance_mean or 0.0),
        natural_confounder_risk=clamp01(natural_risk),
        data_quality=clamp01(data_quality),
        notes=notes,
    )
    metrics = {
        "median_slope_deg": terrain.median_slope_deg,
        "slope_p90_deg": terrain.slope_p90_deg,
        "terrain_ruggedness_risk": terrain.terrain_ruggedness_risk,
        "water_proximity_mean": water_score,
    }
    return TileFeatureResult(evidence=evidence, landscape=landscape, metrics=metrics)
