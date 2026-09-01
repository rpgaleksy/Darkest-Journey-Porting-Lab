#!/usr/bin/env python3
"""Command-line entry point for a read-only static map preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from map_renderer import render_map, write_png
from lcf_reader import LcfParseError


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render one RPG Maker 2000/2003 map as a static PNG preview "
            "without changing the source project."
        )
    )
    parser.add_argument(
        "project_dir",
        type=Path,
        help="path to the read-only RPG Maker project directory",
    )
    parser.add_argument(
        "--map",
        default="Map0001.lmu",
        help="map filename to render (default: Map0001.lmu)",
    )
    parser.add_argument(
        "--rtp-dir",
        dest="rtp_dirs",
        action="append",
        type=Path,
        default=[],
        help="optional RTP directory; may be supplied more than once",
    )
    parser.add_argument(
        "--scale",
        type=_positive_int,
        default=2,
        help="nearest-neighbor output scale (default: 2)",
    )
    parser.add_argument(
        "--no-events",
        action="store_true",
        help="render tile layers without the static event-sprite overlay",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="explicit output PNG path",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="explicit JSON manifest path (default: beside the PNG)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        image, manifest = render_map(
            args.project_dir,
            args.map,
            rtp_dirs=args.rtp_dirs,
            scale=args.scale,
            show_events=not args.no_events,
        )
    except (OSError, LcfParseError, ValueError) as error:
        parser.error(str(error))
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_png(args.out, image)
    manifest_path = args.manifest or args.out.with_suffix(".json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.out}")
    print(f"Wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
