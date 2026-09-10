"""Deterministic execution of a bounded RPG Maker event trace.

The trace runner is intentionally smaller than a game engine.  It executes
the stateful command subset needed by Darkest Journey's first runtime slice,
records every decision, and stops explicitly at external input, unsupported
semantics, malformed data, or a configured budget.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


RENDERING_DIR = Path(__file__).resolve().parents[1] / "03_rendering"
if str(RENDERING_DIR) not in sys.path:
    sys.path.insert(0, str(RENDERING_DIR))

from picture_state import PictureState  # noqa: E402


SHOW_MESSAGE = 10110
SHOW_MESSAGE_CONTINUATION = 20110
SHOW_CHOICE = 10140
SHOW_CHOICE_OPTION = 20140
SHOW_CHOICE_END = 20141
CONTROL_SWITCHES = 10210
CONTROL_VARIABLES = 10220
SHOW_PICTURE = 11110
MOVE_PICTURE = 11120
ERASE_PICTURE = 11130
MOVE_EVENT = 11330
PROCEED_WITH_MOVEMENT = 11340
WAIT = 11410
PLAY_SOUND = 11550
KEY_INPUT = 11610
CONDITIONAL_BRANCH = 12010
LABEL = 12110
JUMP_TO_LABEL = 12120
LOOP = 12210
BREAK_LOOP = 12220
END_EVENT_PROCESSING = 12310
ERASE_EVENT = 12320
CALL_EVENT = 12330
END = 10
ELSE_BRANCH = 22010
END_BRANCH = 22011
END_LOOP = 22210
COMMENT = 12410
COMMENT_CONTINUATION = 22410

PICTURE_COMMANDS = {SHOW_PICTURE, MOVE_PICTURE, ERASE_PICTURE}
COMMENT_COMMANDS = {COMMENT, COMMENT_CONTINUATION}
EXTERNAL_INPUT_COMMANDS = {
    SHOW_MESSAGE,
    SHOW_MESSAGE_CONTINUATION,
    SHOW_CHOICE,
    SHOW_CHOICE_OPTION,
    SHOW_CHOICE_END,
    KEY_INPUT,
    MOVE_EVENT,
    PROCEED_WITH_MOVEMENT,
}
FACING_TO_KEYPAD = {0: 8, 1: 6, 2: 2, 3: 4}


class TraceValidationError(ValueError):
    """Raised when a command list has malformed control-flow structure."""


@dataclass(frozen=True)
class CharacterState:
    """Explicit character snapshot used by ControlVariables and branches."""

    map_id: int = 0
    x: int = 0
    y: int = 0
    facing: int = 2
    screen_x: Optional[int] = None
    screen_y: Optional[int] = None

    def value(self, field_id: int) -> Optional[int]:
        """Return the classic RPG Maker character value for one field."""

        if field_id == 0:
            return self.map_id
        if field_id == 1:
            return self.x
        if field_id == 2:
            return self.y
        if field_id == 3:
            return FACING_TO_KEYPAD.get(self.facing)
        if field_id == 4:
            return self.screen_x if self.screen_x is not None else self.x * 16 + 8
        if field_id == 5:
            return self.screen_y if self.screen_y is not None else self.y * 16 + 16
        return None


@dataclass
class TraceContext:
    """All mutable state a trace is allowed to read or change."""

    switches: MutableMapping[int, bool] = field(default_factory=dict)
    variables: MutableMapping[int, int] = field(default_factory=dict)
    characters: MutableMapping[int, CharacterState] = field(default_factory=dict)
    picture_state: PictureState = field(default_factory=PictureState)
    fps: int = 60
    frame: int = 0
    actions: List[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.fps < 1:
            raise ValueError("fps must be positive")
        if self.frame < 0:
            raise ValueError("frame must not be negative")

    def copy(self) -> "TraceContext":
        """Return an isolated context suitable for a speculative trace."""

        return TraceContext(
            switches=dict(self.switches),
            variables=dict(self.variables),
            characters=dict(self.characters),
            picture_state=self.picture_state.copy(),
            fps=self.fps,
            frame=self.frame,
            actions=list(self.actions),
        )


@dataclass(frozen=True)
class TraceLimits:
    """Safety budgets for deterministic traces."""

    max_commands: int = 10_000
    max_frames: int = 60_000
    max_loop_iterations: int = 1_000
    max_call_depth: int = 32

    def __post_init__(self) -> None:
        if any(
            value < 1
            for value in (
                self.max_commands,
                self.max_frames,
                self.max_loop_iterations,
                self.max_call_depth,
            )
        ):
            raise ValueError("trace limits must be positive")


@dataclass(frozen=True)
class TraceOptions:
    """Per-run controls that do not belong to the emulated game state."""

    stop_after_wait: bool = False


@dataclass
class TraceResult:
    """Result and diagnostics of one trace execution."""

    status: str
    reason: str
    commands_executed: int
    frames_elapsed: int
    context: TraceContext
    path: List[dict] = field(default_factory=list)
    next_index: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "commands_executed": self.commands_executed,
            "frames_elapsed": self.frames_elapsed,
            "next_index": self.next_index,
            "path": list(self.path),
            "state": {
                "frame": self.context.frame,
                "fps": self.context.fps,
                "switches": [
                    {"id": identifier, "value": value}
                    for identifier, value in sorted(self.context.switches.items())
                ],
                "variables": [
                    {"id": identifier, "value": value}
                    for identifier, value in sorted(self.context.variables.items())
                ],
                "characters": [
                    {
                        "id": identifier,
                        "map_id": character.map_id,
                        "x": character.x,
                        "y": character.y,
                        "facing": character.facing,
                        "screen_x": character.screen_x,
                        "screen_y": character.screen_y,
                    }
                    for identifier, character in sorted(self.context.characters.items())
                ],
                "pictures": [
                    _picture_slot_to_dict(self.context.picture_state.slots[picture_id])
                    for picture_id in sorted(self.context.picture_state.slots)
                ],
                "picture_operations": list(self.context.picture_state.operations),
                "actions": list(self.context.actions),
            },
        }


@dataclass(frozen=True)
class _ControlFlow:
    else_by_branch: Mapping[int, int]
    branch_by_else: Mapping[int, int]
    end_by_branch: Mapping[int, int]
    branch_by_end: Mapping[int, int]
    end_by_loop: Mapping[int, int]
    loop_by_end: Mapping[int, int]
    break_target: Mapping[int, int]
    labels: Mapping[int, int]


@dataclass
class _Frame:
    commands: Tuple[Mapping[str, object], ...]
    source: Mapping[str, object]
    flow: _ControlFlow
    index: int = 0
    stop_index: Optional[int] = None
    loop_iterations: MutableMapping[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _Outcome:
    terminal_status: Optional[str] = None
    reason: str = "command executed"
    action: Optional[str] = None
    detail: Mapping[str, object] = field(default_factory=dict)


def _commands_from(value: object) -> Tuple[Mapping[str, object], ...]:
    if isinstance(value, Mapping):
        event_commands = value.get("event_commands")
        if isinstance(event_commands, Mapping):
            value = event_commands.get("commands")
        elif "commands" in value:
            value = value.get("commands")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TraceValidationError("event command list is missing")
    commands = []
    for index, command in enumerate(value):
        if not isinstance(command, Mapping):
            raise TraceValidationError(f"command {index} is not an object")
        commands.append(command)
    return tuple(commands)


def _code(command: Mapping[str, object]) -> int:
    value = command.get("code")
    if not isinstance(value, int) or isinstance(value, bool):
        raise TraceValidationError(f"command has invalid code {value!r}")
    return value


def _indent(command: Mapping[str, object]) -> int:
    value = command.get("indent", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TraceValidationError(f"command has invalid indent {value!r}")
    return value


def _parameters(command: Mapping[str, object], minimum: int = 0) -> Optional[List[int]]:
    values = command.get("parameters", [])
    if not isinstance(values, list):
        return None
    if len(values) < minimum:
        return None
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return None
    return values


def _build_control_flow(commands: Sequence[Mapping[str, object]]) -> _ControlFlow:
    branch_stack: List[Tuple[int, int]] = []
    loop_stack: List[Tuple[int, int]] = []
    else_by_branch: dict[int, int] = {}
    branch_by_else: dict[int, int] = {}
    end_by_branch: dict[int, int] = {}
    branch_by_end: dict[int, int] = {}
    end_by_loop: dict[int, int] = {}
    loop_by_end: dict[int, int] = {}
    labels: dict[int, int] = {}

    for index, command in enumerate(commands):
        code = _code(command)
        indent = _indent(command)
        if code == CONDITIONAL_BRANCH:
            branch_stack.append((indent, index))
        elif code == ELSE_BRANCH:
            matching = next(
                (position for position in range(len(branch_stack) - 1, -1, -1)
                 if branch_stack[position][0] == indent),
                None,
            )
            if matching is None:
                raise TraceValidationError(
                    f"ElseBranch at command {index} has no matching branch"
                )
            branch_index = branch_stack[matching][1]
            if branch_index in else_by_branch:
                raise TraceValidationError(
                    f"branch at command {branch_index} has multiple ElseBranch markers"
                )
            else_by_branch[branch_index] = index
            branch_by_else[index] = branch_index
        elif code == END_BRANCH:
            matching = next(
                (position for position in range(len(branch_stack) - 1, -1, -1)
                 if branch_stack[position][0] == indent),
                None,
            )
            if matching is None:
                raise TraceValidationError(
                    f"EndBranch at command {index} has no matching branch"
                )
            branch_index = branch_stack.pop(matching)[1]
            end_by_branch[branch_index] = index
            branch_by_end[index] = branch_index
        elif code == LOOP:
            loop_stack.append((indent, index))
        elif code == END_LOOP:
            matching = next(
                (position for position in range(len(loop_stack) - 1, -1, -1)
                 if loop_stack[position][0] == indent),
                None,
            )
            if matching is None:
                raise TraceValidationError(
                    f"EndLoop at command {index} has no matching loop"
                )
            loop_index = loop_stack.pop(matching)[1]
            end_by_loop[loop_index] = index
            loop_by_end[index] = loop_index
        elif code == LABEL:
            values = _parameters(command, 1)
            if values is None:
                raise TraceValidationError(f"Label at command {index} has invalid parameters")
            label_id = values[0]
            if label_id in labels:
                raise TraceValidationError(f"label {label_id} occurs more than once")
            labels[label_id] = index

    if branch_stack:
        raise TraceValidationError(
            f"branch at command {branch_stack[-1][1]} has no EndBranch marker"
        )
    if loop_stack:
        raise TraceValidationError(
            f"loop at command {loop_stack[-1][1]} has no EndLoop marker"
        )

    break_target: dict[int, int] = {}
    loop_ranges = tuple(end_by_loop.items())
    for index, command in enumerate(commands):
        if _code(command) != BREAK_LOOP:
            continue
        candidates = [
            (loop_index, end_index)
            for loop_index, end_index in loop_ranges
            if loop_index < index < end_index
        ]
        if not candidates:
            raise TraceValidationError(
                f"BreakLoop at command {index} has no enclosing loop"
            )
        break_target[index] = max(candidates, key=lambda item: item[0])[1]

    for branch_index, end_index in end_by_branch.items():
        if branch_index not in else_by_branch and end_index <= branch_index:
            raise TraceValidationError(f"branch at command {branch_index} has invalid end")

    return _ControlFlow(
        else_by_branch=else_by_branch,
        branch_by_else=branch_by_else,
        end_by_branch=end_by_branch,
        branch_by_end=branch_by_end,
        end_by_loop=end_by_loop,
        loop_by_end=loop_by_end,
        break_target=break_target,
        labels=labels,
    )


def _picture_slot_to_dict(slot: object) -> dict:
    def number(value: object) -> object:
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    return {
        "picture_id": slot.picture_id,
        "raw_picture_id": slot.raw_picture_id,
        "name": slot.name,
        "target_position": [slot.x, slot.y],
        "current_position": [number(slot.current_x), number(slot.current_y)],
        "position_mode": slot.position_mode,
        "fixed_to_map": slot.fixed_to_map,
        "target_zoom": slot.zoom,
        "current_zoom": number(slot.current_zoom),
        "target_transparency": [slot.top_transparency, slot.bottom_transparency],
        "current_transparency": [
            number(slot.current_top_transparency),
            number(slot.current_bottom_transparency),
        ],
        "tone": list(slot.tone),
        "effect_mode": slot.effect_mode,
        "effect_power": slot.effect_power,
        "move_duration": slot.move_duration,
        "move_duration_frames": slot.move_duration_frames,
        "move_remaining_frames": slot.move_remaining_frames,
        "move_wait": slot.move_wait,
        "variable_ids": list(slot.variable_ids),
        "source": dict(slot.source),
        "last_operation": slot.last_operation,
    }


def _normalize_source(source: object) -> dict:
    if isinstance(source, Mapping):
        return dict(source)
    if isinstance(source, str):
        return {"name": source}
    return {"name": "trace"}


class EventTraceRunner:
    """Run bounded command lists against an explicit :class:`TraceContext`."""

    def __init__(
        self,
        common_events: Optional[object] = None,
        *,
        limits: Optional[TraceLimits] = None,
    ) -> None:
        self.limits = limits or TraceLimits()
        self.common_events = self._normalize_common_events(common_events)
        self._flow_cache: dict[
            int,
            Tuple[Tuple[Mapping[str, object], ...], _ControlFlow],
        ] = {}

    @staticmethod
    def _normalize_common_events(value: Optional[object]) -> dict[int, Tuple[Mapping[str, object], ...]]:
        if value is None:
            return {}
        result: dict[int, Tuple[Mapping[str, object], ...]] = {}
        if isinstance(value, Mapping):
            entries: Iterable[Tuple[object, object]] = value.items()
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            entries = (
                (record.get("id"), record)
                for record in value
                if isinstance(record, Mapping)
            )
        else:
            raise TraceValidationError("common_events must be a mapping or record list")
        for raw_id, record in entries:
            event_id = raw_id
            if isinstance(record, Mapping) and not isinstance(event_id, int):
                event_id = record.get("id")
            if not isinstance(event_id, int) or event_id < 1:
                raise TraceValidationError(f"common event has invalid ID {event_id!r}")
            if event_id in result:
                raise TraceValidationError(f"common event {event_id} occurs more than once")
            result[event_id] = _commands_from(record)
        return result

    def _flow(self, commands: Tuple[Mapping[str, object], ...]) -> _ControlFlow:
        key = id(commands)
        cached = self._flow_cache.get(key)
        if cached is not None and cached[0] is commands:
            return cached[1]
        flow = _build_control_flow(commands)
        self._flow_cache[key] = (commands, flow)
        return flow

    @staticmethod
    def _duration_frames(context: TraceContext, duration: int) -> int:
        if duration < 0:
            raise TraceValidationError(f"negative wait duration {duration}")
        return max(1, duration * context.fps // 10)

    @staticmethod
    def _advance(
        context: TraceContext,
        frames: int,
        *,
        start_frame: int,
        limits: TraceLimits,
    ) -> Optional[str]:
        if context.frame - start_frame + frames > limits.max_frames:
            return "trace exceeded its frame budget"
        context.picture_state.advance_frames(frames)
        context.frame += frames
        return None

    @staticmethod
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

    def _control_switches(self, command: Mapping[str, object], context: TraceContext) -> _Outcome:
        values = _parameters(command, 4)
        if values is None:
            return _Outcome("invalid_data", "ControlSwitches has invalid parameters")
        target_mode, start_id, end_id, operation = values[:4]
        if target_mode != 0:
            return _Outcome(
                "unsupported",
                f"ControlSwitches target mode {target_mode} is unsupported",
            )
        if start_id < 1 or end_id < start_id:
            return _Outcome("invalid_data", "ControlSwitches has an invalid range")
        if operation not in (0, 1, 2):
            return _Outcome(
                "unsupported",
                f"ControlSwitches operation {operation} is unsupported",
            )
        changed = []
        for switch_id in range(start_id, end_id + 1):
            before = bool(context.switches.get(switch_id, False))
            after = True if operation == 0 else False if operation == 1 else not before
            context.switches[switch_id] = after
            changed.append({"id": switch_id, "before": before, "after": after})
        return _Outcome(
            reason="switches updated",
            action="control_switches",
            detail={
                "operation": ("on", "off", "toggle")[operation],
                "changed": changed,
            },
        )

    def _character_operand(
        self,
        character_id: int,
        field_id: int,
        context: TraceContext,
    ) -> Tuple[Optional[int], Optional[_Outcome]]:
        character = context.characters.get(character_id)
        if character is None:
            return None, _Outcome(
                "invalid_data",
                f"character snapshot {character_id} is missing",
            )
        value = character.value(field_id)
        if value is None:
            return None, _Outcome(
                "unsupported",
                f"character field {field_id} is unsupported",
            )
        return value, None

    def _control_variables(self, command: Mapping[str, object], context: TraceContext) -> _Outcome:
        values = _parameters(command, 7)
        if values is None:
            return _Outcome("invalid_data", "ControlVariables has invalid parameters")
        target_mode, start_id, end_id, operation, operand_kind = values[:5]
        if target_mode != 0:
            return _Outcome(
                "unsupported",
                f"ControlVariables target mode {target_mode} is unsupported",
            )
        if start_id < 1 or end_id < start_id:
            return _Outcome("invalid_data", "ControlVariables has an invalid range")
        if operation not in (0, 1, 2):
            return _Outcome(
                "unsupported",
                f"ControlVariables operation {operation} is unsupported",
            )

        operand_id = values[5]
        if operand_kind == 0:
            operand = operand_id
            operand_detail = {"kind": "constant", "value": operand}
        elif operand_kind == 1:
            if operand_id < 1:
                return _Outcome("invalid_data", "ControlVariables references an invalid variable")
            operand = int(context.variables.get(operand_id, 0))
            operand_detail = {"kind": "variable", "id": operand_id, "value": operand}
        elif operand_kind == 2:
            if operand_id < 1:
                return _Outcome("invalid_data", "ControlVariables references an invalid variable")
            indirect_id = int(context.variables.get(operand_id, 0))
            operand = int(context.variables.get(indirect_id, 0)) if indirect_id > 0 else 0
            operand_detail = {
                "kind": "indirect_variable",
                "pointer_id": operand_id,
                "resolved_id": indirect_id,
                "value": operand,
            }
        elif operand_kind == 6:
            operand, error = self._character_operand(operand_id, values[6], context)
            if error is not None:
                return error
            assert operand is not None
            operand_detail = {
                "kind": "character",
                "character_id": operand_id,
                "field": values[6],
                "value": operand,
            }
        else:
            return _Outcome(
                "unsupported",
                f"ControlVariables operand kind {operand_kind} is unsupported",
            )

        changed = []
        for variable_id in range(start_id, end_id + 1):
            before = int(context.variables.get(variable_id, 0))
            after = (
                operand
                if operation == 0
                else before + operand
                if operation == 1
                else before - operand
            )
            context.variables[variable_id] = after
            changed.append({"id": variable_id, "before": before, "after": after})
        return _Outcome(
            reason="variables updated",
            action="control_variables",
            detail={
                "operation": ("set", "add", "subtract")[operation],
                "operand": operand_detail,
                "changed": changed,
            },
        )

    def _condition(self, command: Mapping[str, object], context: TraceContext) -> Tuple[Optional[bool], Optional[_Outcome]]:
        values = _parameters(command, 3)
        if values is None:
            return None, _Outcome("invalid_data", "ConditionalBranch has invalid parameters")
        kind = values[0]
        if kind == 0:
            switch_id = values[1]
            enabled = bool(context.switches.get(switch_id, False))
            expected = values[2] == 0
            return enabled == expected, None
        if kind == 1:
            if len(values) < 5:
                return None, _Outcome("invalid_data", "variable branch has invalid parameters")
            variable_id = values[1]
            right = values[3] if values[2] == 0 else int(context.variables.get(values[3], 0))
            result = self._compare(
                int(context.variables.get(variable_id, 0)),
                right,
                values[4],
            )
            if result is None:
                return None, _Outcome(
                    "unsupported",
                    f"variable comparison operator {values[4]} is unsupported",
                )
            return result, None
        if kind == 6:
            if len(values) < 3:
                return None, _Outcome("invalid_data", "character branch has invalid parameters")
            character = context.characters.get(values[1])
            if character is None:
                return None, _Outcome(
                    "invalid_data",
                    f"character snapshot {values[1]} is missing",
                )
            return character.facing == values[2], None
        if kind == 4:
            return None, _Outcome(
                "unsupported",
                "item conditions require an inventory provider",
            )
        return None, _Outcome(
            "unsupported",
            f"conditional branch kind {kind} is unsupported",
        )

    def _picture_command(
        self,
        command: Mapping[str, object],
        context: TraceContext,
        *,
        source: Mapping[str, object],
        start_frame: int,
    ) -> _Outcome:
        applied = context.picture_state.apply_command(
            command,
            context.variables,
            source=source,
            fps=context.fps,
        )
        if not applied:
            detail = context.picture_state.operations[-1] if context.picture_state.operations else {}
            return _Outcome(
                "invalid_data",
                str(detail.get("reason", "Picture command was not applied")),
            )
        code = _code(command)
        if code != MOVE_PICTURE:
            return _Outcome(reason="picture state updated", action="picture")
        values = _parameters(command, 16)
        assert values is not None
        wait_frames = self._duration_frames(context, max(0, values[14]))
        if values[15] <= 0:
            return _Outcome(
                reason="picture move started without waiting",
                action="picture_move",
                detail={"wait": False, "duration_frames": values[14] * context.fps // 10},
            )
        budget_error = self._advance(
            context,
            wait_frames,
            start_frame=start_frame,
            limits=self.limits,
        )
        if budget_error is not None:
            return _Outcome("budget_exhausted", budget_error)
        return _Outcome(
            reason="picture move completed after wait",
            action="picture_move",
            detail={"wait": True, "wait_frames": wait_frames},
        )

    def _step(
        self,
        command: Mapping[str, object],
        frame: _Frame,
        stack: List[_Frame],
        context: TraceContext,
        *,
        command_index: int,
        start_frame: int,
        options: TraceOptions,
    ) -> _Outcome:
        code = _code(command)
        if code in PICTURE_COMMANDS:
            return self._picture_command(
                command,
                context,
                source={**dict(frame.source), "command_index": command_index},
                start_frame=start_frame,
            )
        if code == CONTROL_SWITCHES:
            return self._control_switches(command, context)
        if code == CONTROL_VARIABLES:
            return self._control_variables(command, context)
        if code == CONDITIONAL_BRANCH:
            passed, error = self._condition(command, context)
            if error is not None:
                return error
            assert passed is not None
            if not passed:
                branch_end = frame.flow.end_by_branch.get(command_index)
                if branch_end is None:
                    return _Outcome(
                        "invalid_data",
                        f"branch at command {command_index} has no EndBranch",
                    )
                else_index = frame.flow.else_by_branch.get(command_index)
                frame.index = else_index + 1 if else_index is not None else branch_end + 1
            return _Outcome(
                reason="condition passed" if passed else "condition failed",
                action="branch",
                detail={"passed": passed},
            )
        if code == ELSE_BRANCH:
            branch_index = frame.flow.branch_by_else.get(command_index)
            if branch_index is None:
                return _Outcome("invalid_data", "ElseBranch is not indexed")
            branch_end = frame.flow.end_by_branch.get(branch_index)
            if branch_end is None:
                return _Outcome("invalid_data", "ElseBranch has no EndBranch")
            frame.index = branch_end + 1
            return _Outcome(reason="skipped completed branch alternative", action="branch")
        if code == LOOP:
            iteration = int(frame.loop_iterations.get(command_index, 0)) + 1
            frame.loop_iterations[command_index] = iteration
            if iteration > self.limits.max_loop_iterations:
                return _Outcome(
                    "budget_exhausted",
                    f"loop at command {command_index} exceeded its iteration budget",
                )
            return _Outcome(
                reason="entered loop",
                action="loop",
                detail={"iteration": iteration},
            )
        if code == END_LOOP:
            loop_index = frame.flow.loop_by_end.get(command_index)
            if loop_index is None:
                return _Outcome("invalid_data", "EndLoop is not indexed")
            frame.index = loop_index
            return _Outcome(reason="repeated loop", action="loop")
        if code == BREAK_LOOP:
            break_target = frame.flow.break_target.get(command_index)
            if break_target is None:
                return _Outcome("invalid_data", "BreakLoop is not enclosed by a loop")
            frame.index = break_target + 1
            return _Outcome(reason="left loop", action="break_loop")
        if code == LABEL:
            return _Outcome(reason="reached label", action="label")
        if code == JUMP_TO_LABEL:
            values = _parameters(command, 1)
            if values is None:
                return _Outcome("invalid_data", "JumpToLabel has invalid parameters")
            target = frame.flow.labels.get(values[0])
            if target is None:
                return _Outcome("invalid_data", f"label {values[0]} does not exist")
            frame.index = target
            return _Outcome(
                reason="jumped to label",
                action="jump",
                detail={"label": values[0]},
            )
        if code == CALL_EVENT:
            values = _parameters(command, 2)
            if values is None:
                return _Outcome("invalid_data", "CallEvent has invalid parameters")
            mode, event_id = values[:2]
            if mode != 0:
                return _Outcome(
                    "unsupported",
                    f"CallEvent mode {mode} is unsupported",
                )
            called_commands = self.common_events.get(event_id)
            if called_commands is None:
                return _Outcome("invalid_data", f"common event {event_id} does not exist")
            if len(stack) >= self.limits.max_call_depth:
                return _Outcome("budget_exhausted", "common-event call depth exceeded")
            stack.append(
                _Frame(
                    commands=called_commands,
                    source={"kind": "common_event", "id": event_id},
                    flow=self._flow(called_commands),
                )
            )
            return _Outcome(
                reason="called common event",
                action="call_event",
                detail={"common_event_id": event_id},
            )
        if code == WAIT:
            values = _parameters(command, 1)
            if values is None:
                return _Outcome("invalid_data", "Wait has invalid parameters")
            wait_frames = self._duration_frames(context, values[0])
            budget_error = self._advance(
                context,
                wait_frames,
                start_frame=start_frame,
                limits=self.limits,
            )
            if budget_error is not None:
                return _Outcome("budget_exhausted", budget_error)
            if options.stop_after_wait:
                return _Outcome(
                    "checkpoint",
                    "stopped after explicit Wait",
                    action="wait",
                    detail={"wait_frames": wait_frames},
                )
            return _Outcome(
                reason="wait completed",
                action="wait",
                detail={"wait_frames": wait_frames},
            )
        if code == PLAY_SOUND:
            context.actions.append(
                {
                    "action": "play_sound",
                    "name": command.get("string", ""),
                    "parameters": list(_parameters(command) or []),
                }
            )
            return _Outcome(reason="sound recorded without playback", action="play_sound")
        if code == ERASE_EVENT:
            context.actions.append({"action": "erase_event"})
            return _Outcome(reason="event erase recorded", action="erase_event")
        if code in COMMENT_COMMANDS or code in (END, END_BRANCH):
            return _Outcome(reason="structural marker")
        if code in EXTERNAL_INPUT_COMMANDS:
            return _Outcome(
                "awaiting_input",
                f"command {code} requires an external input or movement provider",
            )
        if code == END_EVENT_PROCESSING:
            return _Outcome("unsupported", "EndEventProcessing is not implemented")
        return _Outcome("unsupported", f"command code {code} is unsupported")

    def run(
        self,
        commands: object,
        context: Optional[TraceContext] = None,
        *,
        source: object = None,
        start_index: int = 0,
        stop_index: Optional[int] = None,
        options: Optional[TraceOptions] = None,
    ) -> TraceResult:
        """Execute one command list or an explicit half-open command segment."""

        command_list = _commands_from(commands)
        if start_index < 0 or start_index > len(command_list):
            raise ValueError("start_index is outside the command list")
        if stop_index is not None and (
            stop_index < start_index or stop_index > len(command_list)
        ):
            raise ValueError("stop_index is outside the command list")
        context = context or TraceContext()
        options = options or TraceOptions()
        start_frame = context.frame
        frame = _Frame(
            commands=command_list,
            source=_normalize_source(source),
            flow=self._flow(command_list),
            index=start_index,
            stop_index=stop_index,
        )
        stack = [frame]
        path: List[dict] = []
        commands_executed = 0

        while stack:
            current = stack[-1]
            if current is frame and current.stop_index is not None and current.index >= current.stop_index:
                return TraceResult(
                    status="checkpoint",
                    reason="reached explicit segment boundary",
                    commands_executed=commands_executed,
                    frames_elapsed=context.frame - start_frame,
                    context=context,
                    path=path,
                    next_index=current.index,
                )
            if current.index >= len(current.commands):
                stack.pop()
                continue
            if commands_executed >= self.limits.max_commands:
                return TraceResult(
                    status="budget_exhausted",
                    reason="trace exceeded its command budget",
                    commands_executed=commands_executed,
                    frames_elapsed=context.frame - start_frame,
                    context=context,
                    path=path,
                    next_index=current.index,
                )
            if context.frame - start_frame >= self.limits.max_frames:
                return TraceResult(
                    status="budget_exhausted",
                    reason="trace exceeded its frame budget",
                    commands_executed=commands_executed,
                    frames_elapsed=context.frame - start_frame,
                    context=context,
                    path=path,
                    next_index=current.index,
                )

            command_index = current.index
            command = current.commands[command_index]
            current.index += 1
            frame_before = context.frame
            commands_executed += 1
            outcome = self._step(
                command,
                current,
                stack,
                context,
                command_index=command_index,
                start_frame=start_frame,
                options=options,
            )
            path_record = {
                "source": dict(current.source),
                "command_index": command_index,
                "code": _code(command),
                "code_name": command.get("code_name", command.get("string", "")),
                "frame_before": frame_before,
                "frame_after": context.frame,
                "status": outcome.terminal_status or "executed",
                "reason": outcome.reason,
            }
            if outcome.action is not None:
                path_record["action"] = outcome.action
            if outcome.detail:
                path_record["detail"] = dict(outcome.detail)
            path.append(path_record)
            if outcome.terminal_status is not None:
                return TraceResult(
                    status=outcome.terminal_status,
                    reason=outcome.reason,
                    commands_executed=commands_executed,
                    frames_elapsed=context.frame - start_frame,
                    context=context,
                    path=path,
                    next_index=current.index,
                )

        return TraceResult(
            status="completed",
            reason="all reachable commands completed",
            commands_executed=commands_executed,
            frames_elapsed=context.frame - start_frame,
            context=context,
            path=path,
        )


__all__ = [
    "CharacterState",
    "EventTraceRunner",
    "TraceContext",
    "TraceLimits",
    "TraceOptions",
    "TraceResult",
    "TraceValidationError",
]
