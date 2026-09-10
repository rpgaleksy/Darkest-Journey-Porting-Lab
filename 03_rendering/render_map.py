#!/usr/bin/env python3
"""Command-line entry point for a read-only static map preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from map_renderer import EventState, render_map, write_png
from lcf_reader import LcfParseError


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _state_assignment(value: str, label: str) -> tuple[int, str]:
    identifier, separator, raw_value = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(f"{label} must use ID=VALUE syntax")
    try:
        parsed_identifier = int(identifier)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} ID must be an integer") from error
    if parsed_identifier < 1:
        raise argparse.ArgumentTypeError(f"{label} ID must be at least 1")
    return parsed_identifier, raw_value


def _switch_assignment(value: str) -> tuple[int, bool]:
    switch_id, raw_value = _state_assignment(value, "switch")
    normalized = raw_value.casefold()
    if normalized in ("on", "true", "1"):
        return switch_id, True
    if normalized in ("off", "false", "0"):
        return switch_id, False
    raise argparse.ArgumentTypeError("switch value must be on or off")


def _variable_assignment(value: str) -> tuple[int, int]:
    variable_id, raw_value = _state_assignment(value, "variable")
    try:
        return variable_id, int(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("variable value must be an integer") from error


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
    picture_group = parser.add_mutually_exclusive_group()
    picture_group.add_argument(
        "--lightmap",
        action="store_true",
        help="overlay ShowPicture commands whose resource name contains 'lightmap'",
    )
    picture_group.add_argument(
        "--pictures",
        action="store_true",
        help="replay conservative parallel map-setup Picture commands",
    )
    parser.add_argument(
        "--switch",
        dest="switches",
        action="append",
        type=_switch_assignment,
        default=[],
        metavar="ID=on|off",
        help="set an event-page switch value; may be supplied more than once",
    )
    parser.add_argument(
        "--variable",
        dest="variables",
        action="append",
        type=_variable_assignment,
        default=[],
        metavar="ID=VALUE",
        help="set an event-page variable value; may be supplied more than once",
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
            show_lightmap=args.lightmap,
            show_pictures=args.pictures,
            event_state=EventState(
                switches=dict(args.switches),
                variables=dict(args.variables),
            ),
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
