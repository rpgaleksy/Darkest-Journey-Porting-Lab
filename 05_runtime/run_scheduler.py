"""Command-line entry point for the bounded parallel-event scheduler."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
PARSER_DIR = REPO_ROOT / "02_parsing"
if str(PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(PARSER_DIR))

from database_parser import parse_ldb  # noqa: E402
from event_scheduler import ParallelScheduler, SchedulerLimits  # noqa: E402
from event_trace import CharacterState, TraceContext  # noqa: E402
from project_parser import parse_lmu  # noqa: E402


def _assignment(value: str, *, name: str) -> tuple[int, int]:
    identifier, separator, assigned = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(f"{name} must use ID=value")
    try:
        identifier_value = int(identifier)
        assigned_value = int(assigned)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name} must use integer values") from error
    if identifier_value < 1:
        raise argparse.ArgumentTypeError(f"{name} ID must be positive")
    return identifier_value, assigned_value


def _switch_assignment(value: str) -> tuple[int, bool]:
    identifier, separator, assigned = value.partition("=")
    if not separator or assigned.casefold() not in {"on", "off", "true", "false", "1", "0"}:
        raise argparse.ArgumentTypeError("--switch must use ID=on|off")
    try:
        identifier_value = int(identifier)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--switch ID must be an integer") from error
    if identifier_value < 1:
        raise argparse.ArgumentTypeError("--switch ID must be positive")
    return identifier_value, assigned.casefold() in {"on", "true", "1"}


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bounded parallel RPG Maker events and emit JSON diagnostics."
    )
    parser.add_argument("project_dir", type=Path)
    parser.add_argument(
        "--map",
        dest="map_filename",
        default="Map0001.lmu",
        metavar="MAP.lmu",
    )
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--max-total-commands", type=int, default=100_000)
    parser.add_argument("--max-commands-per-task-frame", type=int, default=1_000)
    parser.add_argument("--max-restarts-per-task", type=int, default=10_000)
    parser.add_argument(
        "--variable",
        action="append",
        default=[],
        type=lambda value: _assignment(value, name="--variable"),
        metavar="ID=value",
    )
    parser.add_argument(
        "--switch",
        action="append",
        default=[],
        type=_switch_assignment,
        metavar="ID=on|off",
    )
    parser.add_argument("--facing", type=int, choices=range(4), default=2)
    parser.add_argument("--screen-x", type=int)
    parser.add_argument("--screen-y", type=int)
    parser.add_argument("--player-x", type=int, default=0)
    parser.add_argument("--player-y", type=int, default=0)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--out", type=Path, help="write JSON to this explicit path")
    return parser


def run_from_args(args: argparse.Namespace) -> dict:
    if args.frames < 1 or args.fps < 1:
        raise ValueError("--frames and --fps must be positive")
    database = parse_ldb(args.project_dir / "RPG_RT.ldb")["database"]
    map_data = parse_lmu(args.project_dir / args.map_filename)["map"]
    switches = dict(args.switch)
    variables = dict(args.variable)
    characters = {
        10001: CharacterState(
            x=args.player_x,
            y=args.player_y,
            facing=args.facing,
            screen_x=args.screen_x,
            screen_y=args.screen_y,
        )
    }
    context = TraceContext(
        switches=switches,
        variables=variables,
        characters=characters,
        fps=args.fps,
    )
    scheduler = ParallelScheduler(
        database.get("commonevents", {}),
        map_data,
        context=context,
        limits=SchedulerLimits(
            max_frames=args.frames,
            max_total_commands=args.max_total_commands,
            max_commands_per_task_frame=args.max_commands_per_task_frame,
            max_restarts_per_task=args.max_restarts_per_task,
        ),
        strict=args.strict,
    )
    return scheduler.run(max_frames=args.frames).to_dict()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        result = run_from_args(args)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out is None:
        sys.stdout.write(rendered)
    else:
        args.out.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
