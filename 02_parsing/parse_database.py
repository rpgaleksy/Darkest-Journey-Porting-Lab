#!/usr/bin/env python3
"""Command-line entry point for a read-only ``RPG_RT.ldb`` export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from database_parser import parse_ldb
from lcf_reader import LcfParseError
from project_parser import DEFAULT_ENCODING


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse an RPG Maker 2000/2003 RPG_RT.ldb without changing "
            "the source project."
        )
    )
    parser.add_argument(
        "database",
        type=Path,
        help="path to RPG_RT.ldb",
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
        report = parse_ldb(args.database, encoding=args.encoding)
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
