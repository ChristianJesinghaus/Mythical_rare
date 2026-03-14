from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import rasterio
from rasterio.io import DatasetReader


SUPPORTED_SUFFIXES = (".tif", ".tiff")


@dataclass(slots=True)
class RasterAsset:
    path: Path
    label: str


@dataclass(slots=True)
class LocalRasterPack:
    root: Path
    dem: Path
    optical: list[RasterAsset] = field(default_factory=list)
    sar: list[RasterAsset] = field(default_factory=list)
    historical: list[RasterAsset] = field(default_factory=list)
    disturbance: Path | None = None
    confounder: Path | None = None
    water_proximity: Path | None = None
    quality: Path | None = None
    forest: Path | None = None

    @classmethod
    def from_directory(cls, root: str | Path) -> "LocalRasterPack":
        root_path = Path(root)
        if not root_path.exists():
            raise FileNotFoundError(f"Raster pack directory does not exist: {root_path}")

        dem = root_path / "dem.tif"
        if not dem.exists():
            raise FileNotFoundError(f"Expected DEM at {dem}")

        def collect(folder_name: str) -> list[RasterAsset]:
            folder = root_path / folder_name
            if not folder.exists():
                return []
            assets: list[RasterAsset] = []
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                    assets.append(RasterAsset(path=path, label=path.stem))
            return assets

        def optional_file(name: str) -> Path | None:
            path = root_path / name
            return path if path.exists() else None

        return cls(
            root=root_path,
            dem=dem,
            optical=collect("optical"),
            sar=collect("sar"),
            historical=collect("historical"),
            disturbance=optional_file("disturbance.tif"),
            confounder=optional_file("confounder.tif"),
            water_proximity=optional_file("water_proximity.tif"),
            quality=optional_file("quality.tif"),
            forest=optional_file("forest.tif"),
        )

    def source_labels(self) -> list[str]:
        labels = [asset.label for asset in self.optical]
        labels.extend(asset.label for asset in self.sar)
        labels.extend(asset.label for asset in self.historical)
        return labels


@dataclass(slots=True)
class OpenRasterAsset:
    path: Path
    label: str
    dataset: DatasetReader


@dataclass(slots=True)
class OpenLocalRasterPack:
    dem: DatasetReader
    optical: list[OpenRasterAsset]
    sar: list[OpenRasterAsset]
    historical: list[OpenRasterAsset]
    disturbance: DatasetReader | None
    confounder: DatasetReader | None
    water_proximity: DatasetReader | None
    quality: DatasetReader | None
    forest: DatasetReader | None


class LocalRasterPackSession:
    def __init__(self, pack: LocalRasterPack):
        self.pack = pack
        self._stack = ExitStack()
        self._open: OpenLocalRasterPack | None = None

    def __enter__(self) -> OpenLocalRasterPack:
        def open_series(series: Iterable[RasterAsset]) -> list[OpenRasterAsset]:
            return [
                OpenRasterAsset(
                    path=asset.path,
                    label=asset.label,
                    dataset=self._stack.enter_context(rasterio.open(asset.path)),
                )
                for asset in series
            ]

        def open_optional(path: Path | None) -> DatasetReader | None:
            if path is None:
                return None
            return self._stack.enter_context(rasterio.open(path))

        self._open = OpenLocalRasterPack(
            dem=self._stack.enter_context(rasterio.open(self.pack.dem)),
            optical=open_series(self.pack.optical),
            sar=open_series(self.pack.sar),
            historical=open_series(self.pack.historical),
            disturbance=open_optional(self.pack.disturbance),
            confounder=open_optional(self.pack.confounder),
            water_proximity=open_optional(self.pack.water_proximity),
            quality=open_optional(self.pack.quality),
            forest=open_optional(self.pack.forest),
        )
        return self._open

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stack.close()
        self._open = None


def open_local_raster_pack(pack: LocalRasterPack) -> LocalRasterPackSession:
    return LocalRasterPackSession(pack)
