from __future__ import annotations

import argparse

from .io import load_candidates, save_ranked
from .models import PermitMode
from .pipeline import MongoliaProspectionPipeline, demo_red_zones


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank synthetic Mongolia prospection candidates.")
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
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    pipeline = MongoliaProspectionPipeline(
        red_zones=demo_red_zones() if args.use_demo_red_zones else []
    )
    candidates = load_candidates(args.input)
    ranked = pipeline.evaluate(candidates, PermitMode(args.permit_mode))
    save_ranked(args.output, [item.to_dict() for item in ranked])


if __name__ == "__main__":
    main()
