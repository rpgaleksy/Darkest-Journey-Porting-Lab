#!/usr/bin/env python3
"""Command-line entry point for the read-only first-pass LCF parser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from lcf_reader import LcfParseError
from project_parser import DEFAULT_ENCODING, parse_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse RPG Maker 2000/2003 RPG_RT.lmt and one Map*.lmu "
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
        dest="map_filename",
        default="Map0001.lmu",
        help="map file to include (default: Map0001.lmu)",
    )
    parser.add_argument(
        "--encoding",
        default=DEFAULT_ENCODING,
        help=f"text encoding used by the project (default: {DEFAULT_ENCODING})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="write JSON to this explicit output path instead of stdout",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        report = parse_project(
            args.project_dir,
            map_filename=args.map_filename,
            encoding=args.encoding,
        )
    except (OSError, LcfParseError, ValueError) as error:
        parser.error(str(error))
        return 2

    serialized = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.out is None:
        print(serialized)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
