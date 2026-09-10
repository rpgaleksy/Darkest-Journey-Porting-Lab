"""Deterministic cooperative scheduling for RPG Maker parallel events.

The scheduler owns no rendering or platform services.  It advances resumable
``TraceSession`` instances in a stable order, lets them share one
``TraceContext``, and advances the global Picture clock exactly once per
logical frame.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple


RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from event_trace import (  # noqa: E402
    CharacterState,
    EventTraceRunner,
    TraceContext,
    TraceLimits,
    TraceResult,
    TraceSession,
    TraceSessionStep,
)


PARALLEL_TRIGGER = 4
CONDITION_SWITCH_A = 1
CONDITION_SWITCH_B = 2
CONDITION_VARIABLE = 4
SUPPORTED_CONDITION_FLAGS = (
    CONDITION_SWITCH_A | CONDITION_SWITCH_B | CONDITION_VARIABLE
)
_MISSING = object()


def _commands(value: object) -> Tuple[Mapping[str, object], ...]:
    if isinstance(value, Mapping):
        event_commands = value.get("event_commands")
        if isinstance(event_commands, Mapping):
            value = event_commands.get("commands")
        elif "commands" in value:
            value = value.get("commands")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(command for command in value if isinstance(command, Mapping))


def _records(value: object, label: str) -> List[Mapping[str, object]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        if "records" in value:
            value = value.get("records")
        elif "id" in value or "event_commands" in value:
            value = [value]
        else:
            normalized = []
            for raw_id, record in value.items():
                if isinstance(record, Mapping):
                    normalized.append(dict(record, id=raw_id))
                else:
                    normalized.append(
                        {
                            "id": raw_id,
                            "event_commands": {"commands": record},
                        }
                    )
            value = normalized
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a record list or mapping")
    result: List[Mapping[str, object]] = []
    seen: set[int] = set()
    for record in value:
        if not isinstance(record, Mapping):
            raise ValueError(f"{label} contains a non-object record")
        event_id = record.get("id")
        if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
            raise ValueError(f"{label} contains an invalid ID {event_id!r}")
        if event_id in seen:
            raise ValueError(f"{label} contains duplicate ID {event_id}")
        seen.add(event_id)
        result.append(record)
    return result


def _map_events(value: object) -> List[Mapping[str, object]]:
    for _ in range(2):
        if not isinstance(value, Mapping) or "events" not in value:
            break
        value = value.get("events")
    if isinstance(value, Mapping):
        value = [dict(event, id=raw_id) if isinstance(event, Mapping) else {"id": raw_id}
                 for raw_id, event in value.items()]
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("map_events must be a map event list or map data object")
    result: List[Mapping[str, object]] = []
    seen: set[int] = set()
    for event in value:
        if not isinstance(event, Mapping):
            raise ValueError("map_events contains a non-object event")
        event_id = event.get("id")
        if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
            raise ValueError(f"map_events contains an invalid ID {event_id!r}")
        if event_id in seen:
            raise ValueError(f"map_events contains duplicate ID {event_id}")
        seen.add(event_id)
        result.append(event)
    return result


def _pages(event: Mapping[str, object]) -> List[Mapping[str, object]]:
    value = event.get("pages", {})
    if isinstance(value, Mapping):
        value = value.get("pages", [])
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [page for page in value if isinstance(page, Mapping)]


def _signed_int32(value: int) -> int:
    return value - 0x100000000 if value >= 0x80000000 else value


def _compare(left: int, right: int, operator: int) -> Optional[bool]:
    if operator == 0:
        return left == right
    if operator == 1:
        return left >= right
    if operator == 2:
        return left <= right
    if operator == 3:
        return left > right
    if operator == 4:
        return left < right
    if operator == 5:
        return left != right
    return None


def _condition_result(
    page: Mapping[str, object],
    context: TraceContext,
) -> Tuple[Optional[bool], Optional[str]]:
    condition = page.get("condition", {})
    if not isinstance(condition, Mapping):
        return None, "map page condition is not an object"
    flags = condition.get("flags", 0)
    if isinstance(flags, bool) or not isinstance(flags, int) or flags < 0:
        return None, "map page condition flags are invalid"
    unsupported = flags & ~SUPPORTED_CONDITION_FLAGS
    if unsupported:
        return None, f"map page condition flags {unsupported} are unsupported"

    for flag, field in (
        (CONDITION_SWITCH_A, "switch_a_id"),
        (CONDITION_SWITCH_B, "switch_b_id"),
    ):
        if flags & flag:
            identifier = condition.get(field)
            if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 1:
                return None, f"map page condition has invalid {field}"
            if not context.switches.get(identifier, False):
                return False, None

    if flags & CONDITION_VARIABLE:
        variable_id = condition.get("variable_id")
        # LCF omits numeric fields that carry their zero default.  The
        # classic map-page comparison is greater-or-equal unless a later
        # runtime extension explicitly supplies another operator.
        threshold = condition.get("variable_value", 0)
        if (
            isinstance(variable_id, bool)
            or not isinstance(variable_id, int)
            or variable_id < 1
            or isinstance(threshold, bool)
            or not isinstance(threshold, int)
        ):
            return None, "map page variable condition is incomplete"
        threshold = _signed_int32(threshold)
        operator = condition.get("compare_operator", 1)
        if operator is None:
            operator = 1
        if isinstance(operator, bool) or not isinstance(operator, int):
            return None, "map page variable comparison operator is invalid"
        result = _compare(int(context.variables.get(variable_id, 0)), threshold, operator)
        if result is None:
            return None, f"map page comparison operator {operator} is unsupported"
        if not result:
            return False, None

    return True, None


@dataclass(frozen=True)
class SchedulerLimits:
    """Safety limits for one deterministic scheduler run."""

    max_frames: int = 60_000
    max_total_commands: int = 100_000
    max_commands_per_task_frame: int = 1_000
    max_restarts_per_task: int = 10_000

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or value < 1
            for value in (
                self.max_frames,
                self.max_total_commands,
                self.max_commands_per_task_frame,
                self.max_restarts_per_task,
            )
        ):
            raise ValueError("scheduler limits must be positive")


@dataclass
class SchedulerResult:
    """Final shared state and diagnostics of a scheduler run."""

    status: str
    reason: str
    commands_executed: int
    frames_elapsed: int
    context: TraceContext
    tasks: List[dict] = field(default_factory=list)
    timeline: List[dict] = field(default_factory=list)
    path: List[dict] = field(default_factory=list)
    activation_issues: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        state = TraceResult(
            status=self.status,
            reason=self.reason,
            commands_executed=self.commands_executed,
            frames_elapsed=self.frames_elapsed,
            context=self.context,
        ).to_dict()["state"]
        return {
            "status": self.status,
            "reason": self.reason,
            "commands_executed": self.commands_executed,
            "frames_elapsed": self.frames_elapsed,
            "tasks": list(self.tasks),
            "timeline": list(self.timeline),
            "path": list(self.path),
            "activation_issues": list(self.activation_issues),
            "state": state,
        }


@dataclass
class _Task:
    task_id: str
    kind: str
    event_id: int
    page_index: Optional[int]
    source: Mapping[str, object]
    session: TraceSession
    record: Mapping[str, object]
    not_before_frame: int
    last_status: str = "ready"
    last_reason: str = "task is ready"
    enabled: bool = True

    def snapshot(self, frame: int) -> dict:
        if not self.enabled:
            status = "paused"
        elif self.session.is_terminal:
            status = self.session.status
        elif self.session.resume_frame is not None and frame < self.session.resume_frame:
            status = "waiting"
        elif frame < self.not_before_frame:
            status = "prepared"
        else:
            status = self.last_status
        return {
            "id": self.task_id,
            "kind": self.kind,
            "event_id": self.event_id,
            "page_index": self.page_index,
            "source": dict(self.source),
            "enabled": self.enabled,
            "status": status,
            "reason": self.last_reason,
            "resume_frame": self.session.resume_frame,
            "not_before_frame": self.not_before_frame,
            "current_index": self.session.current_index,
            "stack_depth": len(self.session.stack),
            "commands_executed": self.session.commands_executed,
            "restart_count": self.session.restart_count,
        }


class ParallelScheduler:
    """Run active parallel Common Events and Map Events cooperatively."""

    def __init__(
        self,
        common_events: object = None,
        map_events: object = None,
        context: Optional[TraceContext] = None,
        *,
        limits: Optional[SchedulerLimits] = None,
        trace_limits: Optional[TraceLimits] = None,
        strict: bool = False,
    ) -> None:
        self.limits = limits or SchedulerLimits()
        self.context = context or TraceContext()
        self.common_records = sorted(
            _records(common_events, "common_events"),
            key=lambda record: int(record["id"]),
        )
        self.map_records = sorted(
            _map_events(map_events),
            key=lambda record: int(record["id"]),
        )
        self._map_by_id = {int(event["id"]): event for event in self.map_records}
        self.runner = EventTraceRunner(
            self.common_records,
            limits=trace_limits or TraceLimits(),
        )
        self.strict = strict
        self.common_tasks: List[_Task] = []
        self.map_tasks: dict[int, _Task] = {}
        self._retired_tasks: List[_Task] = []
        self._map_page_keys: dict[int, object] = {}
        self._erased_events: set[int] = set()
        self.total_commands = 0
        self.timeline: List[dict] = []
        self.path: List[dict] = []
        self.activation_issues: List[dict] = []
        self._stop_status: Optional[Tuple[str, str]] = None
        self._map_initialized = False
        self._seed_map_characters()
        self._initialize_common_tasks()

    def _seed_map_characters(self) -> None:
        """Provide map-event snapshots unless the caller supplied one."""

        for event in self.map_records:
            event_id = int(event["id"])
            if event_id in self.context.characters:
                continue
            x = event.get("x")
            y = event.get("y")
            if (
                isinstance(x, bool)
                or not isinstance(x, int)
                or isinstance(y, bool)
                or not isinstance(y, int)
            ):
                continue
            facing = 2
            pages = _pages(event)
            if pages and isinstance(pages[0].get("character_direction"), int):
                candidate = pages[0]["character_direction"]
                if candidate in range(4):
                    facing = candidate
            self.context.characters[event_id] = CharacterState(
                x=x,
                y=y,
                facing=facing,
            )

    def _initialize_common_tasks(self) -> None:
        for record in self.common_records:
            event_id = int(record["id"])
            if int(record.get("trigger", 0)) != PARALLEL_TRIGGER:
                continue
            if not _commands(record):
                continue
            source = {"kind": "common_event", "id": event_id}
            self.common_tasks.append(
                _Task(
                    task_id=f"common:{event_id}",
                    kind="common_event",
                    event_id=event_id,
                    page_index=None,
                    source=source,
                    session=self.runner.create_session(
                        record,
                        self.context,
                        source=source,
                    ),
                    record=record,
                    not_before_frame=self.context.frame,
                )
            )

    @staticmethod
    def _common_enabled(record: Mapping[str, object], context: TraceContext) -> bool:
        if not bool(record.get("switch_flag", False)):
            return True
        switch_id = record.get("switch_id")
        if isinstance(switch_id, bool) or not isinstance(switch_id, int) or switch_id < 1:
            return False
        return bool(context.switches.get(switch_id, False))

    def _active_page(
        self,
        event_id: int,
        event: Mapping[str, object],
    ) -> Tuple[Optional[Mapping[str, object]], Optional[dict]]:
        for position, page in reversed(list(enumerate(_pages(event)))):
            result, issue = _condition_result(page, self.context)
            if issue is not None:
                return None, {
                    "event_id": event_id,
                    "page_index": page.get("index", position),
                    "reason": issue,
                }
            if result:
                return page, None
        return None, None

    def _refresh_map_tasks(self, *, initial: bool) -> None:
        current_frame = self.context.frame
        for event_id, event in self._map_by_id.items():
            if event_id in self._erased_events:
                active_page = None
                issue = None
            else:
                active_page, issue = self._active_page(event_id, event)
            if issue is not None:
                if issue not in self.activation_issues:
                    self.activation_issues.append(issue)
                active_page = None

            if active_page is None:
                desired_key: object = None
            else:
                page_index = active_page.get("index")
                if isinstance(page_index, bool) or not isinstance(page_index, int):
                    page_index = _pages(event).index(active_page)
                desired_key = (page_index, int(active_page.get("trigger", 0)))

            previous_key = self._map_page_keys.get(event_id, _MISSING)
            if desired_key == previous_key:
                task = self.map_tasks.get(event_id)
                if task is not None:
                    task.enabled = True
                continue

            self._map_page_keys[event_id] = desired_key
            retired_task = self.map_tasks.pop(event_id, None)
            if retired_task is not None:
                self._retired_tasks.append(retired_task)
            if previous_key is not _MISSING:
                self.timeline.append(
                    {
                        "frame": current_frame,
                        "task_id": retired_task.task_id if retired_task is not None else None,
                        "status": "page_changed",
                        "reason": "active map page changed",
                        "commands_executed": 0,
                        "wait_frames": None,
                        "event_id": event_id,
                        "previous_page": (
                            previous_key[0] if isinstance(previous_key, tuple) else None
                        ),
                        "current_page": desired_key[0] if isinstance(desired_key, tuple) else None,
                    }
                )
            if (
                active_page is None
                or int(active_page.get("trigger", 0)) != PARALLEL_TRIGGER
                or not _commands(active_page)
            ):
                continue

            page_index = int(desired_key[0])
            source = {
                "kind": "map_event",
                "event_id": event_id,
                "page_index": page_index,
            }
            self.map_tasks[event_id] = _Task(
                task_id=f"map:{event_id}:page:{page_index}",
                kind="map_event",
                event_id=event_id,
                page_index=page_index,
                source=source,
                session=self.runner.create_session(
                    active_page,
                    self.context,
                    source=source,
                ),
                record=active_page,
                not_before_frame=current_frame if initial else current_frame + 1,
            )

    def _map_page_changed(self, task: _Task) -> bool:
        event = self._map_by_id.get(task.event_id)
        if event is None or task.event_id in self._erased_events:
            return True
        page, issue = self._active_page(task.event_id, event)
        if issue is not None or page is None:
            return True
        page_index = page.get("index")
        if not isinstance(page_index, int) or isinstance(page_index, bool):
            page_index = _pages(event).index(page)
        return (page_index, int(page.get("trigger", 0))) != self._map_page_keys.get(task.event_id)

    def _stop(self, status: str, reason: str) -> None:
        if self._stop_status is None:
            self._stop_status = (status, reason)

    def _run_task(self, task: _Task) -> None:
        frame = self.context.frame
        if frame < task.not_before_frame:
            task.last_status = "prepared"
            task.last_reason = "task is waiting for its first eligible update"
            return
        if task.kind == "common_event":
            task.enabled = self._common_enabled(task.record, self.context)
        if not task.enabled:
            task.last_status = "paused"
            task.last_reason = "activation switch is off"
            return
        if task.session.is_terminal:
            task.last_status = task.session.status
            task.last_reason = task.session.reason
            if self.strict and task.session.status in {
                "awaiting_input",
                "unsupported",
                "invalid_data",
            }:
                self._stop(task.session.status, task.session.reason)
            return

        remaining = self.limits.max_total_commands - self.total_commands
        if remaining <= 0:
            self._stop("budget_exhausted", "scheduler exceeded its total command budget")
            return
        max_commands = min(self.limits.max_commands_per_task_frame, remaining)
        callback = self._map_page_changed if task.kind == "map_event" else None
        step: TraceSessionStep = task.session.step(
            frame=frame,
            max_commands=max_commands,
            yield_after_command=(lambda: callback(task)) if callback is not None else None,
        )
        self.total_commands += step.commands_executed
        self.path.extend(step.path)
        task.last_status = step.status
        task.last_reason = step.reason
        self.timeline.append(
            {
                "frame": frame,
                "task_id": task.task_id,
                "status": step.status,
                "reason": step.reason,
                "commands_executed": step.commands_executed,
                "wait_frames": step.wait_frames,
                "event_id": task.event_id,
                "page_index": task.page_index,
            }
        )
        if task.session.restart_count > self.limits.max_restarts_per_task:
            task.session.stop(
                "budget_exhausted",
                "task exceeded its restart budget",
            )
            task.last_status = task.session.status
            task.last_reason = task.session.reason
        if self.total_commands >= self.limits.max_total_commands:
            self._stop("budget_exhausted", "scheduler exceeded its total command budget")
        if self.strict and step.status in {"awaiting_input", "unsupported", "invalid_data"}:
            self._stop(step.status, step.reason)
        if step.status == "erased":
            self._erased_events.add(task.event_id)

    def _tasks_snapshot(self) -> List[dict]:
        tasks = (
            list(self.common_tasks)
            + list(self._retired_tasks)
            + [self.map_tasks[event_id] for event_id in sorted(self.map_tasks)]
        )
        return [task.snapshot(self.context.frame) for task in tasks]

    def run(self, *, max_frames: Optional[int] = None) -> SchedulerResult:
        """Run a bounded frame window and return the shared deterministic state."""

        if max_frames is not None and (
            isinstance(max_frames, bool) or max_frames < 1
        ):
            raise ValueError("max_frames must be positive")
        requested_frames = max_frames
        frame_limit = (
            min(max_frames, self.limits.max_frames)
            if max_frames is not None
            else self.limits.max_frames
        )
        clipped_by_limit = max_frames is not None and max_frames > self.limits.max_frames
        start_frame = self.context.frame
        self._refresh_map_tasks(initial=not self._map_initialized)
        self._map_initialized = True
        while self.context.frame - start_frame < frame_limit:
            if self._stop_status is not None:
                break
            frame = self.context.frame
            for task in self.common_tasks:
                self._run_task(task)
                if self._stop_status is not None:
                    break
            if self._stop_status is not None:
                break

            self._refresh_map_tasks(initial=False)
            for event_id in sorted(list(self.map_tasks)):
                task = self.map_tasks.get(event_id)
                if task is None:
                    continue
                self._run_task(task)
                self._refresh_map_tasks(initial=False)
                if self._stop_status is not None:
                    break
            if self._stop_status is not None:
                break

            self.context.picture_state.advance_frames(1)
            self.context.frame += 1
            self.timeline.append(
                {
                    "frame": frame,
                    "task_id": None,
                    "status": "frame_completed",
                    "reason": "global Picture state advanced once",
                    "commands_executed": 0,
                    "wait_frames": None,
                }
            )

        if self._stop_status is not None:
            status, reason = self._stop_status
        elif requested_frames is not None and not clipped_by_limit:
            status, reason = "completed", "reached requested frame window"
        else:
            status, reason = "budget_exhausted", "scheduler reached its frame budget"
        return SchedulerResult(
            status=status,
            reason=reason,
            commands_executed=self.total_commands,
            frames_elapsed=self.context.frame - start_frame,
            context=self.context,
            tasks=self._tasks_snapshot(),
            timeline=list(self.timeline),
            path=list(self.path),
            activation_issues=list(self.activation_issues),
        )


__all__ = [
    "ParallelScheduler",
    "SchedulerLimits",
    "SchedulerResult",
]
