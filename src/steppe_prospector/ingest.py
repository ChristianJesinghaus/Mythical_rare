from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.mask import mask as rio_mask
from rasterio.transform import Affine, from_origin
from rasterio.warp import reproject
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from pyproj import Transformer

from .aoi import AOI, local_metric_crs
from .stac import PlanetaryComputerSigner, STACSelectionManifest, SelectedItem, build_stac_selection
from .stac_recipe import STACRecipe, SeriesRecipe, TargetGridConfig, load_stac_recipe


@dataclass(slots=True)
class TargetGrid:
    crs: CRS
    transform: Affine
    width: int
    height: int
    resolution: float
    nodata: float


@dataclass(slots=True)
class PreparedPackResult:
    pack_dir: Path
    selection_manifest: Path
    pack_manifest: Path


class IngestionError(RuntimeError):
    pass


def _sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "item"


def _series_filename(item: SelectedItem, recipe: SeriesRecipe, index: int) -> str:
    date = (item.datetime or f"item-{index+1}")[:10]
    safe_date = _sanitize_filename(date)
    safe_item = _sanitize_filename(item.item_id)
    return recipe.filename_template.format(date=safe_date, item_id=safe_item, index=index + 1)


def _resampling(name: str | None) -> Resampling:
    if not name:
        return Resampling.bilinear
    normalized = name.lower().strip()
    mapping_ = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
        "average": Resampling.average,
    }
    if normalized not in mapping_:
        raise ValueError(f"Unsupported resampling method: {name}")
    return mapping_[normalized]


def _transform_geometry(geometry: BaseGeometry, src: str | CRS, dst: str | CRS) -> BaseGeometry:
    transformer = Transformer.from_crs(src, dst, always_xy=True)
    return transform(transformer.transform, geometry)


def build_target_grid(aoi: AOI, cfg: TargetGridConfig) -> TargetGrid:
    target_crs = CRS.from_user_input(cfg.output_crs) if cfg.output_crs else local_metric_crs(aoi)
    geom_target = _transform_geometry(aoi.geometry_wgs84, "EPSG:4326", target_crs)
    minx, miny, maxx, maxy = geom_target.bounds
    resolution = float(cfg.resolution_m)
    if resolution <= 0:
        raise ValueError("target.resolution_m must be > 0")

    origin_x = math.floor(minx / resolution) * resolution
    origin_y = math.ceil(maxy / resolution) * resolution
    width = max(1, int(math.ceil((maxx - origin_x) / resolution)))
    height = max(1, int(math.ceil((origin_y - miny) / resolution)))
    transform_ = from_origin(origin_x, origin_y, resolution, resolution)
    return TargetGrid(
        crs=target_crs,
        transform=transform_,
        width=width,
        height=height,
        resolution=resolution,
        nodata=float(cfg.nodata),
    )


def _ensure_path(href: str) -> str:
    if href.startswith("file://"):
        return href[len("file://") :]
    return href


def _apply_signing(href: str, signer: PlanetaryComputerSigner | None) -> str:
    if signer is None:
        return href
    if href.startswith("http://") or href.startswith("https://"):
        return signer.sign(href)
    return href


def _crop_and_reproject(
    href: str,
    *,
    aoi_geometry_wgs84: BaseGeometry,
    target: TargetGrid,
    resampling: Resampling,
    signer: PlanetaryComputerSigner | None = None,
) -> np.ndarray:
    source_href = _apply_signing(_ensure_path(href), signer)

    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(source_href) as src:
            if src.crs is None:
                raise IngestionError(f"Source raster has no CRS: {href}")

            geom_src = _transform_geometry(aoi_geometry_wgs84, "EPSG:4326", src.crs)
            try:
                data, src_transform = rio_mask(
                    src,
                    [mapping(geom_src)],
                    crop=True,
                    filled=True,
                    nodata=np.nan,
                    indexes=1,
                )
            except ValueError as exc:
                raise IngestionError(f"AOI does not intersect source raster: {href}") from exc

            array = data[0] if getattr(data, "ndim", 0) == 3 else data
            array = array.astype("float32", copy=False)
            src_nodata = src.nodata
            if src_nodata is not None and np.isfinite(src_nodata):
                array = np.where(array == src_nodata, np.nan, array)

            destination = np.full((target.height, target.width), np.nan, dtype="float32")
            reproject(
                source=array,
                destination=destination,
                src_transform=src_transform,
                src_crs=src.crs,
                src_nodata=np.nan,
                dst_transform=target.transform,
                dst_crs=target.crs,
                dst_nodata=np.nan,
                resampling=resampling,
            )
            return destination


def _mask_outside_aoi(array: np.ndarray, aoi_geometry_wgs84: BaseGeometry, target: TargetGrid) -> np.ndarray:
    geom_target = _transform_geometry(aoi_geometry_wgs84, "EPSG:4326", target.crs)
    mask = geometry_mask(
        [mapping(geom_target)],
        out_shape=(target.height, target.width),
        transform=target.transform,
        invert=True,
    )
    result = array.copy()
    result[~mask] = np.nan
    return result


def _write_raster(path: Path, array: np.ndarray, target: TargetGrid, compress: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    filled = np.where(np.isfinite(array), array, target.nodata).astype("float32", copy=False)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=target.width,
        height=target.height,
        count=1,
        dtype="float32",
        crs=target.crs,
        transform=target.transform,
        nodata=target.nodata,
        compress=compress,
    ) as dst:
        dst.write(filled, 1)


def _nanmean_stack(arrays: list[np.ndarray]) -> np.ndarray:
    if not arrays:
        raise ValueError("No arrays to aggregate")
    stack = np.stack(arrays).astype("float32", copy=False)
    valid = np.isfinite(stack)
    count = valid.sum(axis=0)
    summed = np.where(valid, stack, 0.0).sum(axis=0)
    result = np.where(count > 0, summed / np.maximum(count, 1), np.nan)
    return result.astype("float32", copy=False)


def _to_db(array: np.ndarray) -> np.ndarray:
    result = array.astype("float32", copy=True)
    positive = result > 0
    result[positive] = 10.0 * np.log10(result[positive])
    result[~positive] = np.nan
    return result


def _build_optical_series(
    selection: list[SelectedItem],
    recipe: SeriesRecipe,
    *,
    aoi: AOI,
    target: TargetGrid,
    pack_dir: Path,
    compress: str,
    signer: PlanetaryComputerSigner | None,
) -> list[Path]:
    if not selection:
        return []
    outputs: list[Path] = []
    for index, item in enumerate(selection):
        red = _crop_and_reproject(
            item.assets["red"].href,
            aoi_geometry_wgs84=aoi.geometry_wgs84,
            target=target,
            resampling=_resampling(recipe.resampling),
            signer=signer,
        )
        nir = _crop_and_reproject(
            item.assets["nir"].href,
            aoi_geometry_wgs84=aoi.geometry_wgs84,
            target=target,
            resampling=_resampling(recipe.resampling),
            signer=signer,
        )
        denominator = nir + red
        with np.errstate(divide="ignore", invalid="ignore"):
            if recipe.output_kind.lower() == "ndvi":
                derived = np.where(np.abs(denominator) > 1e-6, (nir - red) / denominator, np.nan)
            else:
                raise IngestionError(f"Unsupported optical output_kind: {recipe.output_kind}")
        derived = _mask_outside_aoi(derived.astype("float32", copy=False), aoi.geometry_wgs84, target)
        output_path = pack_dir / "optical" / _series_filename(item, recipe, index)
        _write_raster(output_path, derived, target, compress)
        outputs.append(output_path)
    return outputs


def _build_single_band_series(
    selection: list[SelectedItem],
    recipe: SeriesRecipe,
    *,
    aoi: AOI,
    target: TargetGrid,
    pack_dir: Path,
    folder_name: str,
    compress: str,
    signer: PlanetaryComputerSigner | None,
) -> list[Path]:
    outputs: list[Path] = []
    for index, item in enumerate(selection):
        array = _crop_and_reproject(
            item.assets["primary"].href,
            aoi_geometry_wgs84=aoi.geometry_wgs84,
            target=target,
            resampling=_resampling(recipe.resampling),
            signer=signer,
        )
        if recipe.to_db:
            array = _to_db(array)
        array = _mask_outside_aoi(array, aoi.geometry_wgs84, target)
        output_path = pack_dir / folder_name / _series_filename(item, recipe, index)
        _write_raster(output_path, array, target, compress)
        outputs.append(output_path)
    return outputs


def _build_dem(
    selection: list[SelectedItem],
    recipe: SeriesRecipe,
    *,
    aoi: AOI,
    target: TargetGrid,
    pack_dir: Path,
    compress: str,
    signer: PlanetaryComputerSigner | None,
) -> Path:
    if not selection:
        raise IngestionError("DEM recipe is enabled but no DEM item was selected.")
    arrays = [
        _crop_and_reproject(
            item.assets["primary"].href,
            aoi_geometry_wgs84=aoi.geometry_wgs84,
            target=target,
            resampling=_resampling(recipe.resampling),
            signer=signer,
        )
        for item in selection
    ]
    dem = _mask_outside_aoi(_nanmean_stack(arrays), aoi.geometry_wgs84, target)
    output_path = pack_dir / "dem.tif"
    _write_raster(output_path, dem, target, compress)
    return output_path


def _write_quality_layer(pack_dir: Path, target: TargetGrid, source_paths: Iterable[Path], compress: str) -> Path | None:
    source_paths = list(source_paths)
    if not source_paths:
        return None
    arrays: list[np.ndarray] = []
    for path in source_paths:
        with rasterio.open(path) as src:
            arr = src.read(1).astype("float32")
            nodata = src.nodata
            if nodata is not None:
                arr = np.where(arr == nodata, np.nan, arr)
            arrays.append(arr)
    stack = np.stack(arrays)
    valid_count = np.isfinite(stack).sum(axis=0)
    quality = valid_count / max(len(arrays), 1)
    output_path = pack_dir / "quality.tif"
    _write_raster(output_path, quality.astype("float32"), target, compress)
    return output_path


def write_selection_manifest(path: str | Path, manifest: STACSelectionManifest) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return output_path


def load_selection_manifest(path: str | Path) -> STACSelectionManifest:
    return STACSelectionManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def prepare_raster_pack(
    aoi: AOI,
    *,
    recipe: STACRecipe,
    pack_dir: str | Path,
    selection: STACSelectionManifest | None = None,
    selection_manifest_path: str | Path | None = None,
) -> PreparedPackResult:
    pack_path = Path(pack_dir)
    pack_path.mkdir(parents=True, exist_ok=True)

    if selection is None:
        selection = build_stac_selection(aoi, recipe)

    target = build_target_grid(aoi, recipe.target)
    compress = recipe.target.compress
    signer = PlanetaryComputerSigner(recipe.stac.timeout_s) if recipe.stac.asset_href_signing == "planetary-computer" else None

    try:
        dem_path = _build_dem(
            selection.series.get("dem", []),
            recipe.dem,
            aoi=aoi,
            target=target,
            pack_dir=pack_path,
            compress=compress,
            signer=signer,
        )
        optical_outputs = _build_optical_series(
            selection.series.get("optical", []),
            recipe.optical,
            aoi=aoi,
            target=target,
            pack_dir=pack_path,
            compress=compress,
            signer=signer,
        )
        sar_outputs = _build_single_band_series(
            selection.series.get("sar", []),
            recipe.sar,
            aoi=aoi,
            target=target,
            pack_dir=pack_path,
            folder_name="sar",
            compress=compress,
            signer=signer,
        )
        historical_outputs = _build_single_band_series(
            selection.series.get("historical", []),
            recipe.historical,
            aoi=aoi,
            target=target,
            pack_dir=pack_path,
            folder_name="historical",
            compress=compress,
            signer=signer,
        )
        quality_path = _write_quality_layer(pack_path, target, [*optical_outputs, *sar_outputs], compress)
    finally:
        if signer is not None:
            signer.close()

    selection_manifest = write_selection_manifest(
        selection_manifest_path or (pack_path / "selection_manifest.json"),
        selection,
    )

    pack_manifest_data = {
        "target_grid": {
            "crs": str(target.crs),
            "width": target.width,
            "height": target.height,
            "resolution": target.resolution,
            "transform": list(target.transform),
        },
        "outputs": {
            "dem": str(dem_path),
            "optical": [str(path) for path in optical_outputs],
            "sar": [str(path) for path in sar_outputs],
            "historical": [str(path) for path in historical_outputs],
            "quality": str(quality_path) if quality_path else None,
        },
    }
    pack_manifest_path = pack_path / "pack_manifest.json"
    pack_manifest_path.write_text(json.dumps(pack_manifest_data, indent=2), encoding="utf-8")

    return PreparedPackResult(
        pack_dir=pack_path,
        selection_manifest=selection_manifest,
        pack_manifest=pack_manifest_path,
    )


def prepare_raster_pack_from_recipe(
    aoi: AOI,
    *,
    recipe_path: str | Path,
    pack_dir: str | Path,
    selection_manifest_path: str | Path | None = None,
) -> PreparedPackResult:
    recipe = load_stac_recipe(recipe_path)
    return prepare_raster_pack(
        aoi,
        recipe=recipe,
        pack_dir=pack_dir,
        selection_manifest_path=selection_manifest_path,
    )
