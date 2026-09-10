"""Connect bounded event traces to the read-only map renderer.

This module is deliberately an adapter, not a second event interpreter.  It
normalizes the small JSON profile format, supplies map/common-event context to
``05_runtime.event_trace``, and returns the resulting in-memory PictureState.
The original project is only read through the parser; this adapter never
writes to it.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "05_runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from event_trace import (  # noqa: E402
    CharacterState,
    EventTraceRunner,
    TraceContext,
    TraceOptions,
)
from picture_state import PictureState  # noqa: E402


MAP_ID_PATTERN = re.compile(r"Map(\d{4})\.lmu", re.IGNORECASE)
CHARACTER_FIELDS = {"map_id", "x", "y", "facing", "screen_x", "screen_y"}


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _state_overrides(raw: object, label: str, *, boolean: bool) -> dict[str, object]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    result: dict[str, object] = {}
    for raw_id, raw_value in raw.items():
        if isinstance(raw_id, bool):
            raise ValueError(f"{label} IDs must be positive integers")
        try:
            identifier = int(raw_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} IDs must be positive integers") from error
        _positive_int(identifier, f"{label} ID")
        if boolean:
            if not isinstance(raw_value, bool):
                raise ValueError(f"{label} values must be booleans")
        elif isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise ValueError(f"{label} values must be integers")
        result[str(identifier)] = raw_value
    return dict(sorted(result.items(), key=lambda item: int(item[0])))


def _character_overrides(raw: object, label: str) -> dict[str, dict[str, int]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    result: dict[str, dict[str, int]] = {}
    for raw_id, raw_character in raw.items():
        if isinstance(raw_id, bool):
            raise ValueError(f"{label} IDs must be positive integers")
        try:
            identifier = int(raw_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} IDs must be positive integers") from error
        _positive_int(identifier, f"{label} ID")
        if not isinstance(raw_character, Mapping):
            raise ValueError(f"{label} entries must be JSON objects")
        character: dict[str, int] = {}
        for field_name, raw_value in raw_character.items():
            if field_name not in CHARACTER_FIELDS:
                raise ValueError(
                    f"{label} field {field_name!r} is not supported; "
                    f"use {sorted(CHARACTER_FIELDS)}"
                )
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError(f"{label}.{field_name} must be an integer")
            if field_name == "facing" and raw_value not in range(4):
                raise ValueError(f"{label}.facing must be between 0 and 3")
            character[field_name] = raw_value
        result[str(identifier)] = dict(sorted(character.items()))
    return dict(sorted(result.items(), key=lambda item: int(item[0])))


def normalize_trace_spec(raw: object, index: int = 1) -> dict:
    """Validate and canonicalize one renderer profile trace specification."""

    if not isinstance(raw, Mapping):
        raise ValueError(f"trace {index} must be a JSON object")
    kind = raw.get("kind")
    if kind not in {"common_event", "map_event"}:
        raise ValueError(
            f"trace {index} kind must be 'common_event' or 'map_event'"
        )

    result = {"kind": kind}
    if kind == "common_event":
        result["id"] = _positive_int(raw.get("id"), f"trace {index} common event ID")
    else:
        result["event_id"] = _positive_int(
            raw.get("event_id"), f"trace {index} map event ID"
        )
        result["page_index"] = _nonnegative_int(
            raw.get("page_index", 0), f"trace {index} page index"
        )

    result["start_index"] = _nonnegative_int(
        raw.get("start_index", 0), f"trace {index} start index"
    )
    stop_index = raw.get("stop_index")
    if stop_index is not None:
        result["stop_index"] = _nonnegative_int(
            stop_index, f"trace {index} stop index"
        )
    else:
        result["stop_index"] = None
    stop_after_wait = raw.get("stop_after_wait", False)
    if not isinstance(stop_after_wait, bool):
        raise ValueError(f"trace {index} stop_after_wait must be boolean")
    result["stop_after_wait"] = stop_after_wait
    result["fps"] = _positive_int(raw.get("fps", 60), f"trace {index} fps")
    result["switches"] = _state_overrides(
        raw.get("switches"), f"trace {index} switches", boolean=True
    )
    result["variables"] = _state_overrides(
        raw.get("variables"), f"trace {index} variables", boolean=False
    )
    result["characters"] = _character_overrides(
        raw.get("characters"), f"trace {index} characters"
    )
    return result


def normalize_trace_specs(raw: object) -> Tuple[dict, ...]:
    """Validate and canonicalize a profile's list of runtime traces."""

    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise ValueError("traces must be a JSON list")
    return tuple(
        normalize_trace_spec(item, index)
        for index, item in enumerate(raw, start=1)
    )


def _map_events(map_data: Mapping[str, object]) -> List[Mapping[str, object]]:
    events_data = map_data.get("events", {})
    events = events_data.get("events", []) if isinstance(events_data, Mapping) else []
    return [event for event in events if isinstance(event, Mapping)]


def _map_id(map_filename: str) -> int:
    match = MAP_ID_PATTERN.fullmatch(map_filename)
    return int(match.group(1)) if match else 0


def _map_characters(
    events: Sequence[Mapping[str, object]],
    map_id: int,
) -> dict[int, CharacterState]:
    characters: dict[int, CharacterState] = {}
    for event in events:
        event_id = event.get("id")
        x = event.get("x")
        y = event.get("y")
        if (
            isinstance(event_id, bool)
            or not isinstance(event_id, int)
            or isinstance(x, bool)
            or not isinstance(x, int)
            or isinstance(y, bool)
            or not isinstance(y, int)
        ):
            continue
        facing = 2
        pages_data = event.get("pages", {})
        pages = pages_data.get("pages", []) if isinstance(pages_data, Mapping) else []
        if (
            pages
            and isinstance(pages[0], Mapping)
            and isinstance(pages[0].get("character_direction"), int)
        ):
            facing = pages[0]["character_direction"]
        if facing not in range(4):
            facing = 2
        characters[event_id] = CharacterState(
            map_id=map_id,
            x=x,
            y=y,
            facing=facing,
        )
    return characters


def _common_event_records(database: Mapping[str, object]) -> list[Mapping[str, object]]:
    common_events = database.get("commonevents", {})
    if not isinstance(common_events, Mapping):
        return []
    records = common_events.get("records", [])
    return [record for record in records if isinstance(record, Mapping)]


def _apply_state_overrides(
    context: TraceContext,
    spec: Mapping[str, object],
) -> None:
    for raw_id, value in (spec.get("switches", {}) or {}).items():
        context.switches[int(raw_id)] = bool(value)
    for raw_id, value in (spec.get("variables", {}) or {}).items():
        context.variables[int(raw_id)] = int(value)

    characters = spec.get("characters", {}) or {}
    for raw_id, raw_character in characters.items():
        character_id = int(raw_id)
        previous = context.characters.get(character_id, CharacterState())
        values = {
            "map_id": previous.map_id,
            "x": previous.x,
            "y": previous.y,
            "facing": previous.facing,
            "screen_x": previous.screen_x,
            "screen_y": previous.screen_y,
        }
        values.update(raw_character)
        context.characters[character_id] = CharacterState(**values)


@dataclass
class RuntimeTraceRun:
    """Final state and JSON-ready diagnostics for a profile trace sequence."""

    context: TraceContext
    results: List[dict]

    @property
    def picture_state(self) -> PictureState:
        return self.context.picture_state


def run_runtime_traces(
    database: Mapping[str, object],
    map_data: Mapping[str, object],
    map_filename: str,
    specs: Sequence[Mapping[str, object]],
    *,
    initial_switches: Optional[Mapping[int, bool]] = None,
    initial_variables: Optional[Mapping[int, int]] = None,
) -> RuntimeTraceRun:
    """Run explicit traces against one map and return the final snapshot."""

    normalized_specs = normalize_trace_specs(specs)
    events = _map_events(map_data)
    events_by_id = {
        event.get("id"): event
        for event in events
        if isinstance(event.get("id"), int)
    }
    common_records = _common_event_records(database)
    common_by_id = {
        record.get("id"): record
        for record in common_records
        if isinstance(record.get("id"), int)
    }
    context = TraceContext(
        switches=dict(initial_switches or {}),
        variables=dict(initial_variables or {}),
        characters=_map_characters(events, _map_id(map_filename)),
    )
    runner = EventTraceRunner(common_records)
    results: List[dict] = []

    for spec in normalized_specs:
        _apply_state_overrides(context, spec)
        context.fps = int(spec["fps"])
        kind = spec["kind"]
        if kind == "common_event":
            event_id = int(spec["id"])
            commands = common_by_id.get(event_id)
            if commands is None:
                raise ValueError(f"common event {event_id} does not exist")
            source = {"kind": "common_event", "id": event_id}
        else:
            event_id = int(spec["event_id"])
            event = events_by_id.get(event_id)
            if event is None:
                raise ValueError(f"map event {event_id} does not exist")
            page_index = int(spec["page_index"])
            pages_data = event.get("pages", {})
            pages = pages_data.get("pages", []) if isinstance(pages_data, Mapping) else []
            page = next(
                (
                    page
                    for page in pages
                    if isinstance(page, Mapping) and page.get("index") == page_index
                ),
                None,
            )
            if page is None:
                raise ValueError(
                    f"map event {event_id} page {page_index} does not exist"
                )
            commands = page
            source = {
                "kind": "map_event",
                "map": map_filename,
                "event_id": event_id,
                "page_index": page_index,
            }

        result = runner.run(
            commands,
            context,
            source=source,
            start_index=int(spec["start_index"]),
            stop_index=spec["stop_index"],
            options=TraceOptions(stop_after_wait=bool(spec["stop_after_wait"])),
        )
        result_data = result.to_dict()
        result_data["source"] = source
        result_data["spec"] = dict(spec)
        results.append(result_data)

    return RuntimeTraceRun(context=context, results=results)


__all__ = [
    "RuntimeTraceRun",
    "normalize_trace_spec",
    "normalize_trace_specs",
    "run_runtime_traces",
]
