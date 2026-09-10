"""Command-line entry point for the bounded Darkest Journey event tracer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
PARSER_DIR = REPO_ROOT / "02_parsing"
if str(PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(PARSER_DIR))

from database_parser import parse_ldb  # noqa: E402
from event_trace import (  # noqa: E402
    CharacterState,
    EventTraceRunner,
    TraceContext,
    TraceOptions,
)
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


def _common_event_records(database: Mapping[str, object]) -> list[dict]:
    common_events = database.get("commonevents", {})
    if not isinstance(common_events, Mapping):
        return []
    records = common_events.get("records", [])
    return [record for record in records if isinstance(record, dict)]


def _find_common_event(records: list[dict], event_id: int) -> dict:
    for record in records:
        if record.get("id") == event_id:
            return record
    raise ValueError(f"common event {event_id} does not exist")


def _map_events(map_data: Mapping[str, object]) -> list[dict]:
    events_data = map_data.get("events", {})
    if not isinstance(events_data, Mapping):
        return []
    events = events_data.get("events", [])
    return [event for event in events if isinstance(event, dict)]


def _find_map_event(events: list[dict], event_id: int) -> dict:
    for event in events:
        if event.get("id") == event_id:
            return event
    raise ValueError(f"map event {event_id} does not exist")


def _find_page(event: Mapping[str, object], page_index: int) -> dict:
    pages_data = event.get("pages", {})
    if not isinstance(pages_data, Mapping):
        raise ValueError("map event has no pages")
    pages = pages_data.get("pages", [])
    for page in pages:
        if isinstance(page, dict) and page.get("index") == page_index:
            return page
    raise ValueError(f"map event page {page_index} does not exist")


def _map_characters(events: list[dict]) -> dict[int, CharacterState]:
    characters = {}
    for event in events:
        event_id = event.get("id")
        x = event.get("x")
        y = event.get("y")
        if not isinstance(event_id, int) or not isinstance(x, int) or not isinstance(y, int):
            continue
        facing = 2
        pages_data = event.get("pages", {})
        pages = pages_data.get("pages", []) if isinstance(pages_data, Mapping) else []
        if pages and isinstance(pages[0], Mapping) and isinstance(pages[0].get("character_direction"), int):
            facing = pages[0]["character_direction"]
        characters[event_id] = CharacterState(x=x, y=y, facing=facing)
    return characters


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one bounded RPG Maker event trace and emit JSON diagnostics."
    )
    parser.add_argument("project_dir", type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--common-event", type=int, metavar="ID")
    target.add_argument("--map", dest="map_filename", metavar="MAP.lmu")
    parser.add_argument("--event-id", type=int, help="map event to trace")
    parser.add_argument("--page-index", type=int, default=0)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--stop-index", type=int)
    parser.add_argument("--variable", action="append", default=[], type=lambda value: _assignment(value, name="--variable"), metavar="ID=value")
    parser.add_argument("--switch", action="append", default=[], type=_switch_assignment, metavar="ID=on|off")
    parser.add_argument("--facing", type=int, choices=range(4), default=2)
    parser.add_argument("--screen-x", type=int)
    parser.add_argument("--screen-y", type=int)
    parser.add_argument("--player-x", type=int, default=0)
    parser.add_argument("--player-y", type=int, default=0)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--stop-after-wait", action="store_true")
    parser.add_argument("--out", type=Path, help="write JSON to this explicit path")
    return parser


def run_from_args(args: argparse.Namespace) -> dict:
    project_dir = args.project_dir
    database = parse_ldb(project_dir / "RPG_RT.ldb")["database"]
    records = _common_event_records(database)
    common_events = {record.get("id"): record for record in records}
    runner = EventTraceRunner(common_events)
    characters: dict[int, CharacterState] = {}

    if args.common_event is not None:
        record = _find_common_event(records, args.common_event)
        commands = record
        source = {"kind": "common_event", "id": args.common_event}
    else:
        if args.event_id is None:
            raise ValueError("--event-id is required with --map")
        map_path = project_dir / args.map_filename
        map_data = parse_lmu(map_path)["map"]
        events = _map_events(map_data)
        event = _find_map_event(events, args.event_id)
        page = _find_page(event, args.page_index)
        commands = page
        characters.update(_map_characters(events))
        source = {
            "kind": "map_event",
            "map": args.map_filename,
            "event_id": args.event_id,
            "page_index": args.page_index,
        }

    characters[10001] = CharacterState(
        x=args.player_x,
        y=args.player_y,
        facing=args.facing,
        screen_x=args.screen_x,
        screen_y=args.screen_y,
    )
    variables = dict(args.variable)
    switches = dict(args.switch)
    context = TraceContext(
        switches=switches,
        variables=variables,
        characters=characters,
        fps=args.fps,
    )
    result = runner.run(
        commands,
        context,
        source=source,
        start_index=args.start_index,
        stop_index=args.stop_index,
        options=TraceOptions(stop_after_wait=args.stop_after_wait),
    )
    return result.to_dict()


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
