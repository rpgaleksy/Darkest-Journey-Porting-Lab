#!/usr/bin/env python3
"""Command-line entry point for read-only RPG Maker resource analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from lcf_reader import LcfParseError
from project_parser import DEFAULT_ENCODING
from resource_scanner import markdown_report, scan_resources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan known RPG Maker 2000/2003 resource references and resolve "
            "them against a project directory and optional RTP directories "
            "without changing either source."
        )
    )
    parser.add_argument(
        "project_dir",
        type=Path,
        help="path to the read-only RPG Maker project directory",
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
        "--encoding",
        default=DEFAULT_ENCODING,
        help=f"text encoding used by the project (default: {DEFAULT_ENCODING})",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--out",
        type=Path,
        help="write JSON to this explicit output path instead of stdout",
    )
    output.add_argument(
        "--out-dir",
        type=Path,
        help="write resources.json and resources.md to this explicit directory",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        report = scan_resources(
            args.project_dir,
            rtp_dirs=args.rtp_dirs,
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
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        json_path = args.out_dir / "resources.json"
        markdown_path = args.out_dir / "resources.md"
        json_path.write_text(serialized + "\n", encoding="utf-8")
        markdown_path.write_text(markdown_report(report), encoding="utf-8")
        print(f"Wrote {json_path}")
        print(f"Wrote {markdown_path}")
    elif args.out is None:
        print(serialized)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
