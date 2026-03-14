from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis import AOIAnalyzer
from .aoi import load_aoi
from .config import load_settings
from .datapack import LocalRasterPack
from .demo import create_demo_dataset
from .guardrails import demo_red_zones, load_red_zones_geojson
from .ingest import load_selection_manifest, prepare_raster_pack, write_selection_manifest
from .io import load_candidates, save_ranked
from .models import PermitMode
from .outputs import write_analysis_bundle
from .pipeline import MongoliaProspectionPipeline
from .stac import build_stac_selection
from .stac_recipe import load_stac_recipe


def _legacy_rank_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank precomputed Mongolia prospection candidates.")
    parser.add_argument("input", help="Path to candidate JSON")
    parser.add_argument("output", help="Path to ranked output JSON")
    parser.add_argument(
        "--permit-mode",
        default="public",
        choices=[mode.value for mode in PermitMode],
        help="public | restricted | authorized",
    )
    parser.add_argument(
        "--use-demo-red-zones",
        action="store_true",
        help="Enable placeholder red-zone masking for testing.",
    )
    parser.add_argument("--config", help="Optional path to a TOML config.")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mongolia steppe prospection toolkit")
    subparsers = parser.add_subparsers(dest="command")

    rank = subparsers.add_parser("rank", help="Rank precomputed candidate features")
    rank.add_argument("input", help="Path to candidate JSON")
    rank.add_argument("output", help="Path to ranked output JSON")
    rank.add_argument(
        "--permit-mode",
        default="public",
        choices=[mode.value for mode in PermitMode],
    )
    rank.add_argument("--use-demo-red-zones", action="store_true")
    rank.add_argument("--config", help="Optional path to a TOML config.")

    analyze = subparsers.add_parser("analyze", help="Run tile extraction and ranking on a local raster pack")
    analyze.add_argument("--aoi", required=True, help="Path to AOI GeoJSON")
    analyze.add_argument("--data-pack", required=True, help="Directory containing the local raster pack")
    analyze.add_argument("--output-dir", required=True, help="Directory for JSON/GeoJSON/HTML outputs")
    analyze.add_argument(
        "--permit-mode",
        default="public",
        choices=[mode.value for mode in PermitMode],
    )
    analyze.add_argument("--red-zones-geojson", help="Optional GeoJSON file with red-zone polygons")
    analyze.add_argument("--use-demo-red-zones", action="store_true")
    analyze.add_argument("--config", help="Optional path to a TOML config.")
    analyze.add_argument("--tile-size-m", type=float, help="Override tile size in meters")
    analyze.add_argument("--tile-step-m", type=float, help="Override tile step in meters")
    analyze.add_argument("--min-adjusted-score", type=float, help="Minimum adjusted score to keep")
    analyze.add_argument("--max-candidates", type=int, help="Maximum number of candidates to export")

    stac_search = subparsers.add_parser("stac-search", help="Search a STAC endpoint and save the selected items")
    stac_search.add_argument("--aoi", required=True, help="Path to AOI GeoJSON")
    stac_search.add_argument("--recipe", required=True, help="Path to STAC recipe TOML")
    stac_search.add_argument("--output", required=True, help="Path to selection_manifest.json")

    prepare_pack = subparsers.add_parser("prepare-pack", help="Build a local raster pack from STAC items")
    prepare_pack.add_argument("--aoi", required=True, help="Path to AOI GeoJSON")
    prepare_pack.add_argument("--recipe", required=True, help="Path to STAC recipe TOML")
    prepare_pack.add_argument("--output-dir", required=True, help="Directory where the raster pack will be written")
    prepare_pack.add_argument(
        "--selection-manifest",
        help="Optional existing selection manifest JSON. If omitted, STAC search is performed first.",
    )

    analyze_stac = subparsers.add_parser(
        "analyze-stac",
        help="Run STAC search, prepare a raster pack, and analyze it in one command",
    )
    analyze_stac.add_argument("--aoi", required=True, help="Path to AOI GeoJSON")
    analyze_stac.add_argument("--recipe", required=True, help="Path to STAC recipe TOML")
    analyze_stac.add_argument("--work-dir", required=True, help="Directory for manifests, raster pack, and outputs")
    analyze_stac.add_argument(
        "--permit-mode",
        default="public",
        choices=[mode.value for mode in PermitMode],
    )
    analyze_stac.add_argument("--red-zones-geojson", help="Optional GeoJSON file with red-zone polygons")
    analyze_stac.add_argument("--use-demo-red-zones", action="store_true")
    analyze_stac.add_argument("--config", help="Optional path to a TOML config.")
    analyze_stac.add_argument("--tile-size-m", type=float, help="Override tile size in meters")
    analyze_stac.add_argument("--tile-step-m", type=float, help="Override tile step in meters")
    analyze_stac.add_argument("--min-adjusted-score", type=float, help="Minimum adjusted score to keep")
    analyze_stac.add_argument("--max-candidates", type=int, help="Maximum number of candidates to export")

    demo = subparsers.add_parser("demo", help="Generate a synthetic demo pack and run the analyzer")
    demo.add_argument("output_dir", help="Directory where demo data and outputs will be written")
    demo.add_argument(
        "--permit-mode",
        default="public",
        choices=[mode.value for mode in PermitMode],
    )
    demo.add_argument("--config", help="Optional path to a TOML config.")

    make_demo = subparsers.add_parser("make-demo", help="Generate only the synthetic demo data pack")
    make_demo.add_argument("output_dir", help="Directory where demo data will be written")

    return parser


def _load_red_zones(args: argparse.Namespace):
    zones = []
    if getattr(args, "use_demo_red_zones", False):
        zones.extend(demo_red_zones())
    red_zone_path = getattr(args, "red_zones_geojson", None)
    if red_zone_path:
        zones.extend(load_red_zones_geojson(red_zone_path))
    return zones


def run_rank(args: argparse.Namespace) -> Path:
    settings = load_settings(args.config) if getattr(args, "config", None) else load_settings()
    pipeline = MongoliaProspectionPipeline(
        settings=settings,
        red_zones=_load_red_zones(args),
    )
    candidates = load_candidates(args.input)
    ranked = pipeline.evaluate(candidates, PermitMode(args.permit_mode))
    output_path = Path(args.output)
    save_ranked(output_path, [item.to_dict() for item in ranked])
    return output_path


def run_analyze(args: argparse.Namespace) -> dict[str, Path]:
    settings = load_settings(args.config) if getattr(args, "config", None) else load_settings()
    analyzer = AOIAnalyzer(settings=settings, red_zones=_load_red_zones(args))
    aoi = load_aoi(args.aoi)
    pack = LocalRasterPack.from_directory(args.data_pack)
    result = analyzer.analyze(
        aoi=aoi,
        pack=pack,
        permit_mode=PermitMode(args.permit_mode),
        tile_size_m=args.tile_size_m,
        tile_step_m=args.tile_step_m,
        min_adjusted_score=args.min_adjusted_score,
        max_candidates=args.max_candidates,
    )
    return write_analysis_bundle(args.output_dir, aoi, result, red_zones=list(analyzer.red_zones))


def run_stac_search(args: argparse.Namespace) -> Path:
    aoi = load_aoi(args.aoi)
    recipe = load_stac_recipe(args.recipe)
    selection = build_stac_selection(aoi, recipe)
    return write_selection_manifest(args.output, selection)


def run_prepare_pack(args: argparse.Namespace) -> dict[str, Path]:
    aoi = load_aoi(args.aoi)
    recipe = load_stac_recipe(args.recipe)
    selection = load_selection_manifest(args.selection_manifest) if args.selection_manifest else build_stac_selection(aoi, recipe)
    prepared = prepare_raster_pack(
        aoi,
        recipe=recipe,
        pack_dir=args.output_dir,
        selection=selection,
        selection_manifest_path=Path(args.output_dir) / "selection_manifest.json",
    )
    return {
        "pack_dir": prepared.pack_dir,
        "selection_manifest": prepared.selection_manifest,
        "pack_manifest": prepared.pack_manifest,
    }


def run_analyze_stac(args: argparse.Namespace) -> dict[str, Path]:
    work_dir = Path(args.work_dir)
    pack_dir = work_dir / "data_pack"
    output_dir = work_dir / "analysis_outputs"

    prepared_outputs = run_prepare_pack(
        argparse.Namespace(
            aoi=args.aoi,
            recipe=args.recipe,
            output_dir=pack_dir,
            selection_manifest=None,
        )
    )

    analyze_outputs = run_analyze(
        argparse.Namespace(
            aoi=args.aoi,
            data_pack=prepared_outputs["pack_dir"],
            output_dir=output_dir,
            permit_mode=args.permit_mode,
            red_zones_geojson=args.red_zones_geojson,
            use_demo_red_zones=args.use_demo_red_zones,
            config=args.config,
            tile_size_m=args.tile_size_m,
            tile_step_m=args.tile_step_m,
            min_adjusted_score=args.min_adjusted_score,
            max_candidates=args.max_candidates,
        )
    )

    outputs = dict(prepared_outputs)
    outputs.update(analyze_outputs)
    return outputs


def run_demo(args: argparse.Namespace) -> dict[str, Path]:
    root = Path(args.output_dir)
    assets = create_demo_dataset(root)
    settings = load_settings(args.config) if getattr(args, "config", None) else load_settings()
    analyzer = AOIAnalyzer(settings=settings, red_zones=load_red_zones_geojson(assets["red_zones"]))
    result = analyzer.analyze(
        aoi=load_aoi(assets["aoi"]),
        pack=LocalRasterPack.from_directory(assets["pack_dir"]),
        permit_mode=PermitMode(args.permit_mode),
    )
    outputs = write_analysis_bundle(root / "demo_outputs", load_aoi(assets["aoi"]), result, red_zones=list(analyzer.red_zones))
    outputs.update(assets)
    return outputs


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] not in {"rank", "analyze", "stac-search", "prepare-pack", "analyze-stac", "demo", "make-demo", "-h", "--help"}:
        args = _legacy_rank_parser().parse_args(argv)
        output_path = run_rank(args)
        print(output_path)
        return

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "rank":
        print(run_rank(args))
        return
    if args.command == "analyze":
        outputs = run_analyze(args)
        for path in outputs.values():
            print(path)
        return
    if args.command == "stac-search":
        print(run_stac_search(args))
        return
    if args.command == "prepare-pack":
        outputs = run_prepare_pack(args)
        for path in outputs.values():
            print(path)
        return
    if args.command == "analyze-stac":
        outputs = run_analyze_stac(args)
        for path in outputs.values():
            print(path)
        return
    if args.command == "demo":
        outputs = run_demo(args)
        for path in outputs.values():
            print(path)
        return
    if args.command == "make-demo":
        assets = create_demo_dataset(args.output_dir)
        for path in assets.values():
            print(path)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
