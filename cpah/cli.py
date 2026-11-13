from __future__ import annotations

import argparse
import json
import os
import pathlib
from typing import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cyberpunk 2077 breach puzzle solver")
    parser.add_argument("--version", action="store_true", help="show the CPAH version")
    parser.add_argument("--analyze-screenshot", type=pathlib.Path, metavar="PATH")
    parser.add_argument("--json", action="store_true", help="emit machine-readable analysis")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.version:
        from .constants import VERSION
        print(VERSION)
        return 0
    if args.analyze_screenshot:
        # This mode must never initialize file logging, focus the game, or write
        # a migrated configuration back to disk.
        os.environ["CPAH_READ_ONLY"] = "1"
        from . import logic
        result = logic.analyze_screenshot(
            logic.load_config(read_only=True), args.analyze_screenshot
        )
        puzzle = result.puzzle
        payload = {
            "profile_version": result.profile_version,
            "source_resolution": result.screenshot_data.source_resolution,
            "hud_mode": result.hud_mode,
            "confidence": result.confidence,
            "bounds": {
                "matrix": result.screen_bounds.code_matrix,
                "buffer": result.screen_bounds.buffer_box,
                "sequences": result.screen_bounds.sequences,
                "objectives": result.screen_bounds.objectives,
            },
            "matrix": puzzle.matrix,
            "buffer_size": puzzle.buffer_size,
            "objectives": [
                {"codes": item.codes, "label": item.label, "kind": item.kind}
                for item in puzzle.objectives
            ],
        }
        print(json.dumps(payload, indent=2 if args.json else None))
        return 0
    from .ui import start
    start()
    return 0
