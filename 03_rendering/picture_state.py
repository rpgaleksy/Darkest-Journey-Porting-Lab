"""Small, deterministic state machine for classic RPG Maker Pictures.

The real game keeps Pictures in a runtime register keyed by picture ID.  This
module models the part needed by a static map preview and the first
deterministic event trace: ShowPicture, MovePicture, ErasePicture, classic
variable coordinates, the project's Picture Pointer Patch, and linear
transition timing.  It deliberately does not implement easing, rotation, or
wave animation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Mapping, Optional, Tuple


SHOW_PICTURE = 11110
MOVE_PICTURE = 11120
ERASE_PICTURE = 11130


def _signed_int32(value: int) -> int:
    if value >= 0x80000000:
        return value - 0x100000000
    return value


def _as_integer_parameters(command: Mapping[str, object], minimum: int) -> Optional[List[int]]:
    parameters = command.get("parameters")
    if not isinstance(parameters, list) or len(parameters) < minimum:
        return None
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in parameters[:minimum]):
        return None
    return parameters


def _variable_value(variables: Mapping[int, int], variable_id: int) -> int:
    return int(variables.get(variable_id, 0))


def _replace_picture_suffix(name: str, suffix: int) -> str:
    """Apply the project's four-character numeric Picture name replacement."""

    if len(name) < 4:
        return name
    return name[:-4] + f"{suffix:04d}"


def _resolve_picture_reference(
    raw_picture_id: int,
    raw_name: str,
    variables: Mapping[int, int],
) -> Tuple[int, str, Tuple[int, ...], Optional[str]]:
    """Resolve a classic ID and the project's extended pointer convention."""

    raw_picture_id = _signed_int32(raw_picture_id)
    if raw_picture_id <= 10000:
        return raw_picture_id, raw_name, (), None

    if raw_picture_id >= 50000:
        variable_id = raw_picture_id - 50000
        resolved_id = _variable_value(variables, variable_id)
        suffix = _variable_value(variables, variable_id + 1)
        resolved_name = _replace_picture_suffix(raw_name, suffix)
        if resolved_id <= 0:
            return (
                resolved_id,
                resolved_name,
                (variable_id, variable_id + 1),
                f"picture pointer variable {variable_id} resolves to {resolved_id}",
            )
        return resolved_id, resolved_name, (variable_id, variable_id + 1), None

    variable_id = raw_picture_id - 10000
    resolved_id = _variable_value(variables, variable_id)
    if resolved_id <= 0:
        return (
            resolved_id,
            raw_name,
            (variable_id,),
            f"picture pointer variable {variable_id} resolves to {resolved_id}",
        )
    return resolved_id, raw_name, (variable_id,), None


def _resolve_coordinates(
    position_mode: int,
    raw_x: int,
    raw_y: int,
    variables: Mapping[int, int],
) -> Tuple[int, int, Tuple[int, ...], Optional[str]]:
    position_mode &= 0xFF
    if position_mode == 0:
        return _signed_int32(raw_x), _signed_int32(raw_y), (), None
    if position_mode == 1:
        x_variable = _signed_int32(raw_x)
        y_variable = _signed_int32(raw_y)
        return (
            _variable_value(variables, x_variable),
            _variable_value(variables, y_variable),
            (x_variable, y_variable),
            None,
        )
    return 0, 0, (), f"unsupported picture position mode {position_mode}"


@dataclass(frozen=True)
class PictureSlot:
    """The target and current snapshot of one active Picture slot."""

    picture_id: int
    raw_picture_id: int
    name: str
    position_mode: int
    x: int
    y: int
    fixed_to_map: bool
    zoom: int
    top_transparency: int
    bottom_transparency: int
    use_transparent_color: bool
    tone: Tuple[int, int, int, int]
    effect_mode: int
    effect_power: int
    variable_ids: Tuple[int, ...] = ()
    source: Mapping[str, object] = field(default_factory=dict)
    last_operation: str = "show"
    last_operation_source: Mapping[str, object] = field(default_factory=dict)
    move_duration: int = 0
    move_wait: bool = False
    move_duration_frames: int = 0
    move_remaining_frames: int = 0
    start_x: float = 0.0
    current_x: float = 0.0
    start_y: float = 0.0
    current_y: float = 0.0
    start_zoom: float = 100.0
    current_zoom: float = 100.0
    start_top_transparency: float = 0.0
    current_top_transparency: float = 0.0
    start_bottom_transparency: float = 0.0
    current_bottom_transparency: float = 0.0
    start_tone: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    current_tone: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    start_effect_power: float = 0.0
    current_effect_power: float = 0.0


class PictureState:
    """Mutable Picture register with diagnostic operation records."""

    def __init__(self) -> None:
        self.slots: dict[int, PictureSlot] = {}
        self.operations: List[dict] = []
        self.warnings: List[dict] = []
        self.skipped: List[dict] = []
        self.current_frame = 0

    def _source(self, source: Optional[Mapping[str, object]]) -> dict:
        return dict(source or {})

    def copy(self) -> "PictureState":
        """Return an isolated register copy for transactional trace replay."""

        result = PictureState()
        result.slots = dict(self.slots)
        result.operations = list(self.operations)
        result.warnings = list(self.warnings)
        result.skipped = list(self.skipped)
        result.current_frame = self.current_frame
        return result

    def replace_from(self, other: "PictureState") -> None:
        """Commit a successfully replayed temporary register."""

        self.slots = dict(other.slots)
        self.operations = list(other.operations)
        self.warnings = list(other.warnings)
        self.skipped = list(other.skipped)
        self.current_frame = other.current_frame

    def _record(
        self,
        operation: str,
        status: str,
        source: Optional[Mapping[str, object]],
        *,
        picture_id: Optional[int] = None,
        raw_picture_id: Optional[int] = None,
        picture_name: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> dict:
        record = {
            "operation": operation,
            "status": status,
            "source": self._source(source),
            "picture_id": picture_id,
            "raw_picture_id": raw_picture_id,
            "picture_name": picture_name,
        }
        if reason is not None:
            record["reason"] = reason
        self.operations.append(record)
        if status == "skipped":
            self.skipped.append(record)
        elif status == "warning":
            self.warnings.append(record)
        return record

    def _skip(
        self,
        operation: str,
        source: Optional[Mapping[str, object]],
        reason: str,
        *,
        picture_id: Optional[int] = None,
        raw_picture_id: Optional[int] = None,
        picture_name: Optional[str] = None,
    ) -> bool:
        self._record(
            operation,
            "skipped",
            source,
            picture_id=picture_id,
            raw_picture_id=raw_picture_id,
            picture_name=picture_name,
            reason=reason,
        )
        return False

    def apply_command(
        self,
        command: Mapping[str, object],
        variables: Mapping[int, int],
        *,
        source: Optional[Mapping[str, object]] = None,
        fps: int = 60,
    ) -> bool:
        """Apply one classic Picture command and return whether it was applied."""

        if fps < 1:
            raise ValueError("fps must be positive")

        code = command.get("code")
        if code == SHOW_PICTURE:
            return self._apply_show(command, variables, source)
        if code == MOVE_PICTURE:
            return self._apply_move(command, variables, source, fps=fps)
        if code == ERASE_PICTURE:
            return self._apply_erase(command, variables, source)
        return self._skip("unknown", source, f"unsupported picture command code {code!r}")

    def _apply_show(
        self,
        command: Mapping[str, object],
        variables: Mapping[int, int],
        source: Optional[Mapping[str, object]],
    ) -> bool:
        parameters = _as_integer_parameters(command, 14)
        raw_name = command.get("string")
        picture_name = raw_name if isinstance(raw_name, str) else ""
        raw_picture_id = parameters[0] if parameters is not None else None
        if parameters is None:
            return self._skip(
                "show",
                source,
                "ShowPicture has fewer than 14 integer parameters",
                raw_picture_id=raw_picture_id,
                picture_name=picture_name,
            )

        picture_id, picture_name, pointer_variables, pointer_error = _resolve_picture_reference(
            parameters[0], picture_name, variables
        )
        if pointer_error is not None:
            return self._skip(
                "show",
                source,
                pointer_error,
                picture_id=picture_id,
                raw_picture_id=parameters[0],
                picture_name=picture_name,
            )
        if picture_id <= 0:
            return self._skip(
                "show",
                source,
                f"picture ID resolves to {picture_id}",
                picture_id=picture_id,
                raw_picture_id=parameters[0],
                picture_name=picture_name,
            )

        position_mode = parameters[1] & 0xFF
        x, y, coordinate_variables, coordinate_error = _resolve_coordinates(
            position_mode,
            parameters[2],
            parameters[3],
            variables,
        )
        if coordinate_error is not None:
            return self._skip(
                "show",
                source,
                coordinate_error,
                picture_id=picture_id,
                raw_picture_id=parameters[0],
                picture_name=picture_name,
            )

        effect_mode = parameters[12]
        effect_power = parameters[13] if effect_mode else 0
        slot = PictureSlot(
            picture_id=picture_id,
            raw_picture_id=_signed_int32(parameters[0]),
            name=picture_name,
            position_mode=position_mode,
            x=x,
            y=y,
            fixed_to_map=parameters[4] > 0,
            zoom=max(0, min(parameters[5], 2000)),
            top_transparency=max(0, min(parameters[6], 100)),
            bottom_transparency=max(0, min(parameters[6], 100)),
            use_transparent_color=parameters[7] > 0,
            tone=tuple(_signed_int32(value) for value in parameters[8:12]),
            effect_mode=effect_mode,
            effect_power=effect_power,
            variable_ids=tuple(dict.fromkeys((*pointer_variables, *coordinate_variables))),
            source=self._source(source),
            last_operation="show",
            last_operation_source=self._source(source),
            start_x=float(x),
            current_x=float(x),
            start_y=float(y),
            current_y=float(y),
            start_zoom=float(max(0, min(parameters[5], 2000))),
            current_zoom=float(max(0, min(parameters[5], 2000))),
            start_top_transparency=float(max(0, min(parameters[6], 100))),
            current_top_transparency=float(max(0, min(parameters[6], 100))),
            start_bottom_transparency=float(max(0, min(parameters[6], 100))),
            current_bottom_transparency=float(max(0, min(parameters[6], 100))),
            start_tone=tuple(float(_signed_int32(value)) for value in parameters[8:12]),
            current_tone=tuple(float(_signed_int32(value)) for value in parameters[8:12]),
            start_effect_power=float(effect_power),
            current_effect_power=float(effect_power),
        )
        self.slots[picture_id] = slot
        self._record(
            "show",
            "applied",
            source,
            picture_id=picture_id,
            raw_picture_id=parameters[0],
            picture_name=picture_name,
        )
        return True

    def _apply_move(
        self,
        command: Mapping[str, object],
        variables: Mapping[int, int],
        source: Optional[Mapping[str, object]],
        *,
        fps: int,
    ) -> bool:
        parameters = _as_integer_parameters(command, 16)
        raw_picture_id = parameters[0] if parameters is not None else None
        if parameters is None:
            return self._skip(
                "move",
                source,
                "MovePicture has fewer than 16 integer parameters",
                raw_picture_id=raw_picture_id,
            )

        picture_id, _unused_name, pointer_variables, pointer_error = _resolve_picture_reference(
            parameters[0], "", variables
        )
        if pointer_error is not None:
            return self._skip(
                "move",
                source,
                pointer_error,
                picture_id=picture_id,
                raw_picture_id=parameters[0],
            )
        slot = self.slots.get(picture_id)
        if slot is None:
            return self._skip(
                "move",
                source,
                f"MovePicture targets inactive picture ID {picture_id}",
                picture_id=picture_id,
                raw_picture_id=parameters[0],
            )

        position_mode = parameters[1] & 0xFF
        x, y, coordinate_variables, coordinate_error = _resolve_coordinates(
            position_mode,
            parameters[2],
            parameters[3],
            variables,
        )
        if coordinate_error is not None:
            return self._skip(
                "move",
                source,
                coordinate_error,
                picture_id=picture_id,
                raw_picture_id=parameters[0],
                picture_name=slot.name,
            )

        effect_mode = parameters[12]
        effect_power = parameters[13] if effect_mode else 0
        target_zoom = max(0, min(parameters[5], 2000))
        target_top_transparency = max(0, min(parameters[6], 100))
        target_bottom_transparency = max(0, min(parameters[6], 100))
        target_tone = tuple(float(_signed_int32(value)) for value in parameters[8:12])
        target_effect_power = float(effect_power)
        move_duration = max(0, parameters[14])
        move_duration_frames = move_duration * fps // 10
        updated = replace(
            slot,
            position_mode=position_mode,
            x=x,
            y=y,
            zoom=target_zoom,
            top_transparency=target_top_transparency,
            bottom_transparency=target_bottom_transparency,
            tone=tuple(_signed_int32(value) for value in parameters[8:12]),
            effect_mode=effect_mode,
            effect_power=effect_power,
            variable_ids=tuple(dict.fromkeys((*pointer_variables, *coordinate_variables))),
            last_operation="move",
            last_operation_source=self._source(source),
            move_duration=move_duration,
            move_wait=parameters[15] > 0,
            move_duration_frames=move_duration_frames,
            move_remaining_frames=move_duration_frames,
            start_x=slot.current_x,
            current_x=slot.current_x if move_duration_frames else float(x),
            start_y=slot.current_y,
            current_y=slot.current_y if move_duration_frames else float(y),
            start_zoom=slot.current_zoom,
            current_zoom=slot.current_zoom if move_duration_frames else float(target_zoom),
            start_top_transparency=slot.current_top_transparency,
            current_top_transparency=(
                slot.current_top_transparency
                if move_duration_frames
                else float(target_top_transparency)
            ),
            start_bottom_transparency=slot.current_bottom_transparency,
            current_bottom_transparency=(
                slot.current_bottom_transparency
                if move_duration_frames
                else float(target_bottom_transparency)
            ),
            start_tone=slot.current_tone,
            current_tone=slot.current_tone if move_duration_frames else target_tone,
            start_effect_power=slot.current_effect_power,
            current_effect_power=(
                slot.current_effect_power
                if move_duration_frames
                else target_effect_power
            ),
        )
        self.slots[picture_id] = updated
        self._record(
            "move",
            "applied",
            source,
            picture_id=picture_id,
            raw_picture_id=parameters[0],
            picture_name=slot.name,
        )
        return True

    @staticmethod
    def _interpolate(start: float, target: float, progress: float) -> float:
        return start + (target - start) * progress

    def advance_frames(self, frames: int) -> None:
        """Advance active Picture transitions by a number of logical frames."""

        if frames < 0:
            raise ValueError("frames must not be negative")
        if frames == 0:
            return
        for picture_id, slot in list(self.slots.items()):
            duration = slot.move_duration_frames
            if duration <= 0 or slot.move_remaining_frames <= 0:
                continue
            elapsed_before = duration - slot.move_remaining_frames
            elapsed_after = min(duration, elapsed_before + frames)
            progress = elapsed_after / duration
            target_tone = tuple(float(value) for value in slot.tone)
            updated = replace(
                slot,
                current_x=self._interpolate(slot.start_x, float(slot.x), progress),
                current_y=self._interpolate(slot.start_y, float(slot.y), progress),
                current_zoom=self._interpolate(slot.start_zoom, float(slot.zoom), progress),
                current_top_transparency=self._interpolate(
                    slot.start_top_transparency,
                    float(slot.top_transparency),
                    progress,
                ),
                current_bottom_transparency=self._interpolate(
                    slot.start_bottom_transparency,
                    float(slot.bottom_transparency),
                    progress,
                ),
                current_tone=tuple(
                    self._interpolate(start, target, progress)
                    for start, target in zip(slot.start_tone, target_tone)
                ),
                current_effect_power=self._interpolate(
                    slot.start_effect_power,
                    float(slot.effect_power),
                    progress,
                ),
                move_remaining_frames=duration - elapsed_after,
            )
            self.slots[picture_id] = updated
        self.current_frame += frames

    def _apply_erase(
        self,
        command: Mapping[str, object],
        variables: Mapping[int, int],
        source: Optional[Mapping[str, object]],
    ) -> bool:
        parameters = _as_integer_parameters(command, 1)
        raw_picture_id = parameters[0] if parameters is not None else None
        if parameters is None:
            return self._skip(
                "erase",
                source,
                "ErasePicture has no integer picture ID",
                raw_picture_id=raw_picture_id,
            )

        picture_id, _unused_name, _pointer_variables, pointer_error = _resolve_picture_reference(
            parameters[0], "", variables
        )
        if pointer_error is not None:
            return self._skip(
                "erase",
                source,
                pointer_error,
                picture_id=picture_id,
                raw_picture_id=parameters[0],
            )
        slot = self.slots.pop(picture_id, None)
        self._record(
            "erase",
            "applied",
            source,
            picture_id=picture_id,
            raw_picture_id=parameters[0],
            picture_name=slot.name if slot is not None else None,
        )
        return True


__all__ = [
    "ERASE_PICTURE",
    "MOVE_PICTURE",
    "PictureSlot",
    "PictureState",
    "SHOW_PICTURE",
]
