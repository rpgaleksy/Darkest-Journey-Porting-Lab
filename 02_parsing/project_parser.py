"""Partial semantic parser for RPG Maker 2000/2003 LMT and LMU files.

This module intentionally focuses on the structures needed for a first
porting analysis: map-tree metadata, map dimensions/layers, events, event
pages and event commands.  Unknown chunks are retained as compact descriptors
so that the parser remains useful while coverage is expanded.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from lcf_reader import LcfChunk, LcfParseError, LcfReader, StructRead, read_struct_chunks


DEFAULT_ENCODING = "cp1252"
DEFAULT_MAP_CHIPSET_ID = 1
DEFAULT_MAP_WIDTH = 20
DEFAULT_MAP_HEIGHT = 15
MAX_VECTOR_ITEMS = 1_000_000


def _source_metadata(path: Path, data: bytes) -> dict:
    return {
        "name": path.name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _payload_descriptor(chunk: LcfChunk, preview_bytes: int = 96) -> dict:
    descriptor = chunk.descriptor(preview_bytes=preview_bytes)
    descriptor.pop("id", None)
    descriptor.pop("offset", None)
    return descriptor


def _decode_int(chunk: LcfChunk) -> int:
    reader = LcfReader(
        chunk.payload,
        source_name=f"chunk 0x{chunk.chunk_id:x}",
        base_offset=chunk.payload_offset,
    )
    value = reader.read_compressed_int()
    if reader.remaining:
        raise LcfParseError(
            f"chunk 0x{chunk.chunk_id:x}: {reader.remaining} trailing byte(s) "
            "after compressed integer"
        )
    return value


def _decode_bool(chunk: LcfChunk) -> bool:
    return _decode_int(chunk) > 0


def _decode_text(chunk: LcfChunk, encoding: str) -> str:
    return chunk.payload.decode(encoding, errors="replace")


def _decode_fixed_array(
    chunk: LcfChunk,
    *,
    item_bytes: int,
    signed: bool,
) -> List[int]:
    if len(chunk.payload) % item_bytes:
        raise LcfParseError(
            f"chunk 0x{chunk.chunk_id:x}: payload length {len(chunk.payload)} "
            f"is not divisible by {item_bytes}"
        )
    return [
        int.from_bytes(
            chunk.payload[offset:offset + item_bytes],
            "little",
            signed=signed,
        )
        for offset in range(0, len(chunk.payload), item_bytes)
    ]


def _decode_area_rect(chunk: LcfChunk) -> List[int]:
    if len(chunk.payload) != 16:
        raise LcfParseError(
            f"area_rect must contain four 32-bit values, got {len(chunk.payload)} bytes"
        )
    return [
        int.from_bytes(chunk.payload[offset:offset + 4], "little", signed=False)
        for offset in range(0, 16, 4)
    ]


def _record_unknown(result: dict, chunk: LcfChunk) -> None:
    result.setdefault("unrecognized_chunks", []).append(chunk.descriptor())


def _record_error(result: dict, chunk: LcfChunk, field: str, error: Exception) -> None:
    result.setdefault("field_decode_errors", []).append(
        {
            "field": field,
            "chunk_id": chunk.chunk_id,
            "offset": chunk.offset,
            "message": str(error),
        }
    )
    result.setdefault("raw_field_payloads", []).append(
        {
            "field": field,
            "chunk_id": chunk.chunk_id,
            "offset": chunk.offset,
            "payload": _payload_descriptor(chunk),
        }
    )


def _finish_struct(
    result: dict,
    read: StructRead,
    *,
    allow_eof: bool = False,
) -> None:
    result["present_chunk_ids"] = [chunk.chunk_id for chunk in read.chunks]
    result["struct_terminated"] = read.terminated
    if not read.terminated and not allow_eof:
        result.setdefault("warnings", []).append(
            "struct ended at EOF without a zero terminator"
        )


Decoder = Callable[[LcfChunk], Any]
NestedDecoder = Callable[[LcfChunk, str], Any]


def _decode_schema(
    reader: LcfReader,
    *,
    fields: Mapping[int, str],
    encoding: str,
    text_fields: Iterable[int] = (),
    bool_fields: Iterable[int] = (),
    fixed_fields: Optional[Mapping[int, Decoder]] = None,
    nested_fields: Optional[Mapping[int, NestedDecoder]] = None,
    partial_fields: Optional[Mapping[int, str]] = None,
    allow_eof: bool = False,
) -> Tuple[dict, StructRead]:
    """Decode a chunked struct while preserving fields outside the schema."""

    text_ids = set(text_fields)
    bool_ids = set(bool_fields)
    fixed = dict(fixed_fields or {})
    nested = dict(nested_fields or {})
    partial = dict(partial_fields or {})
    read = read_struct_chunks(reader)
    result: dict = {}

    for chunk in read.chunks:
        field_name = fields.get(chunk.chunk_id)
        if field_name is None:
            _record_unknown(result, chunk)
            continue

        try:
            if chunk.chunk_id in text_ids:
                value = _decode_text(chunk, encoding)
            elif chunk.chunk_id in bool_ids:
                value = _decode_bool(chunk)
            elif chunk.chunk_id in fixed:
                value = fixed[chunk.chunk_id](chunk)
            elif chunk.chunk_id in nested:
                value = nested[chunk.chunk_id](chunk, encoding)
            elif chunk.chunk_id in partial:
                value = _decode_counted_raw(chunk, partial[chunk.chunk_id])
            else:
                value = _decode_int(chunk)
        except (LcfParseError, UnicodeError, ValueError) as error:
            _record_error(result, chunk, field_name, error)
            continue

        if field_name in result:
            result.setdefault("warnings", []).append(
                f"duplicate field {field_name!r} at offset {chunk.offset}; "
                "last occurrence retained"
            )
        result[field_name] = value

    _finish_struct(result, read, allow_eof=allow_eof)
    return result, read


def _decode_counted_raw(chunk: LcfChunk, label: str) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name=f"chunk 0x{chunk.chunk_id:x}",
        base_offset=chunk.payload_offset,
    )
    count = reader.read_compressed_int()
    if count > MAX_VECTOR_ITEMS:
        raise LcfParseError(
            f"{label}: vector count {count} exceeds safety limit "
            f"{MAX_VECTOR_ITEMS}"
        )
    return {
        "count": count,
        "decoded": False,
        "note": f"{label} records are retained as raw payload for a later parser pass",
        "raw_payload": _payload_descriptor(chunk),
    }


def _decode_raw(chunk: LcfChunk, label: str) -> dict:
    return {
        "decoded": False,
        "note": f"{label} payload is retained for a later parser pass",
        "raw_payload": _payload_descriptor(chunk),
    }


def _parse_condition(chunk: LcfChunk, encoding: str) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name="EventPageCondition",
        base_offset=chunk.payload_offset,
    )
    result, _ = _decode_schema(
        reader,
        fields={
            0x01: "flags",
            0x02: "switch_a_id",
            0x03: "switch_b_id",
            0x04: "variable_id",
            0x05: "variable_value",
            0x06: "item_id",
            0x07: "actor_id",
            0x08: "timer_sec",
            0x09: "timer2_sec",
            0x0A: "compare_operator",
        },
        encoding=encoding,
    )
    return result


def _parse_move_route(chunk: LcfChunk, encoding: str) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name="MoveRoute",
        base_offset=chunk.payload_offset,
    )
    result, _ = _decode_schema(
        reader,
        fields={
            0x0B: "move_commands_size",
            0x0C: "move_commands",
            0x15: "repeat",
            0x16: "skippable",
        },
        encoding=encoding,
        bool_fields=(0x15, 0x16),
        fixed_fields={0x0C: lambda route_chunk: _decode_raw(route_chunk, "move command")},
    )
    return result


def _parse_music(chunk: LcfChunk, encoding: str) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name="Music",
        base_offset=chunk.payload_offset,
    )
    result, _ = _decode_schema(
        reader,
        fields={
            0x01: "name",
            0x02: "fadein",
            0x03: "volume",
            0x04: "tempo",
            0x05: "balance",
        },
        encoding=encoding,
        text_fields=(0x01,),
    )
    return result


def _parse_event_commands(chunk: LcfChunk, encoding: str) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name="EventCommandArray",
        base_offset=chunk.payload_offset,
    )
    commands: List[dict] = []
    terminated = False
    warnings: List[str] = []

    while not reader.eof:
        command_offset = reader.position
        if reader.remaining >= 4 and reader.peek_bytes(4) == b"\x00\x00\x00\x00":
            reader.read_bytes(4)
            terminated = True
            break

        try:
            code = reader.read_compressed_int()
            indent = reader.read_compressed_int()
            string_length = reader.read_compressed_int()
            string_value = reader.read_string(string_length, encoding=encoding)
            parameter_count = reader.read_compressed_int()
            if parameter_count > MAX_VECTOR_ITEMS:
                raise LcfParseError(
                    f"event command parameter count {parameter_count} exceeds "
                    f"safety limit {MAX_VECTOR_ITEMS}"
                )
            parameters = [
                reader.read_compressed_int()
                for _ in range(parameter_count)
            ]
        except LcfParseError:
            raise

        command = {
            "offset": command_offset,
            "code": code,
            "code_name": EVENT_COMMAND_NAMES.get(code),
            "indent": indent,
            "string": string_value,
            "parameters": parameters,
        }
        commands.append(command)

    if not terminated:
        warnings.append("event command array ended without its four-byte terminator")
    if reader.remaining:
        warnings.append(
            f"{reader.remaining} byte(s) remained after the event command terminator"
        )

    result = {
        "commands": commands,
        "command_count": len(commands),
        "payload_length": chunk.length,
        "terminated": terminated,
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _parse_page_vector(chunk: LcfChunk, encoding: str) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name="EventPageVector",
        base_offset=chunk.payload_offset,
    )
    count = reader.read_compressed_int()
    if count > MAX_VECTOR_ITEMS:
        raise LcfParseError(
            f"event page count {count} exceeds safety limit {MAX_VECTOR_ITEMS}"
        )

    pages: List[dict] = []
    for index in range(count):
        page_id = reader.read_compressed_int()
        page = _parse_event_page_from_reader(reader, encoding)
        page["id"] = page_id
        page["index"] = index
        pages.append(page)

    return {
        "count": count,
        "pages": pages,
        "remaining_bytes": reader.remaining,
    }


def _parse_event_page_from_reader(reader: LcfReader, encoding: str) -> dict:
    result, _ = _decode_schema(
        reader,
        fields={
            0x02: "condition",
            0x15: "character_name",
            0x16: "character_index",
            0x17: "character_direction",
            0x18: "character_pattern",
            0x19: "translucent",
            0x1F: "move_type",
            0x20: "move_frequency",
            0x21: "trigger",
            0x22: "layer",
            0x23: "overlap_forbidden",
            0x24: "animation_type",
            0x25: "move_speed",
            0x29: "move_route",
            0x33: "event_commands_size",
            0x34: "event_commands",
        },
        encoding=encoding,
        text_fields=(0x15,),
        bool_fields=(0x19, 0x23),
        nested_fields={
            0x02: _parse_condition,
            0x29: _parse_move_route,
            0x34: _parse_event_commands,
        },
        partial_fields={},
    )
    return _finalize_event_page(result)


def _finalize_event_page(result: dict) -> dict:
    event_commands = result.get("event_commands")
    declared_size = result.get("event_commands_size")
    if isinstance(event_commands, dict) and declared_size is not None:
        actual_size = event_commands.get("payload_length")
        if actual_size != declared_size:
            result.setdefault("warnings", []).append(
                f"event_commands_size declares {declared_size} byte(s), "
                f"but chunk 0x34 contains {actual_size} byte(s)"
            )
    return result


def _parse_event_from_reader(reader: LcfReader, encoding: str) -> dict:
    result, _ = _decode_schema(
        reader,
        fields={
            0x01: "name",
            0x02: "x",
            0x03: "y",
            0x05: "pages",
        },
        encoding=encoding,
        text_fields=(0x01,),
        nested_fields={0x05: _parse_page_vector},
    )
    return result


def _parse_event_vector(chunk: LcfChunk, encoding: str) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name="EventVector",
        base_offset=chunk.payload_offset,
    )
    count = reader.read_compressed_int()
    if count > MAX_VECTOR_ITEMS:
        raise LcfParseError(
            f"event count {count} exceeds safety limit {MAX_VECTOR_ITEMS}"
        )

    events: List[dict] = []
    for index in range(count):
        event_id = reader.read_compressed_int()
        event = _parse_event_from_reader(reader, encoding)
        event["id"] = event_id
        event["index"] = index
        events.append(event)

    return {
        "count": count,
        "events": events,
        "remaining_bytes": reader.remaining,
    }


def _parse_map_info(reader: LcfReader, map_id: int, index: int, encoding: str) -> dict:
    result, _ = _decode_schema(
        reader,
        fields={
            0x01: "name",
            0x02: "parent_map",
            0x03: "indentation",
            0x04: "type",
            0x05: "scrollbar_x",
            0x06: "scrollbar_y",
            0x07: "expanded_node",
            0x0B: "music_type",
            0x0C: "music",
            0x15: "background_type",
            0x16: "background_name",
            0x1F: "teleport",
            0x20: "escape",
            0x21: "save",
            0x29: "encounters",
            0x2C: "encounter_steps",
            0x33: "area_rect",
        },
        encoding=encoding,
        text_fields=(0x01, 0x16),
        bool_fields=(0x07,),
        fixed_fields={0x33: _decode_area_rect},
        partial_fields={
            0x29: "encounter",
        },
        nested_fields={0x0C: _parse_music},
    )
    result["id"] = map_id
    result["index"] = index
    return result


def _parse_start(reader: LcfReader, encoding: str) -> dict:
    result, _ = _decode_schema(
        reader,
        fields={
            0x01: "party_map_id",
            0x02: "party_x",
            0x03: "party_y",
            0x0B: "boat_map_id",
            0x0C: "boat_x",
            0x0D: "boat_y",
            0x15: "ship_map_id",
            0x16: "ship_x",
            0x17: "ship_y",
            0x1F: "airship_map_id",
            0x20: "airship_x",
            0x21: "airship_y",
        },
        encoding=encoding,
    )
    return result


def _parse_lmt(path: Path, encoding: str) -> dict:
    data = path.read_bytes()
    reader = LcfReader(data, source_name=path.name)
    header = reader.read_header(expected="LcfMapTree")
    map_count = reader.read_compressed_int()
    if map_count > MAX_VECTOR_ITEMS:
        raise LcfParseError(
            f"{path.name}: map count {map_count} exceeds safety limit "
            f"{MAX_VECTOR_ITEMS}"
        )

    maps = []
    for index in range(map_count):
        map_id = reader.read_compressed_int()
        maps.append(_parse_map_info(reader, map_id, index, encoding))

    tree_order_count = reader.read_compressed_int()
    if tree_order_count > MAX_VECTOR_ITEMS:
        raise LcfParseError(
            f"{path.name}: tree order count {tree_order_count} exceeds safety limit "
            f"{MAX_VECTOR_ITEMS}"
        )
    tree_order = [
        reader.read_compressed_int()
        for _ in range(tree_order_count)
    ]
    active_node = reader.read_compressed_int()
    start = _parse_start(reader, encoding)

    warnings: List[str] = []
    if reader.remaining:
        warnings.append(
            f"{reader.remaining} trailing byte(s) remained after RPG_RT.lmt"
        )
    result = {
        "file": _source_metadata(path, data),
        "header": header,
        "map_count": map_count,
        "maps": maps,
        "tree_order": tree_order,
        "active_node": active_node,
        "start": start,
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _layer_summary(
    values: Sequence[int],
    *,
    width: int,
    height: int,
    layer_name: str,
) -> dict:
    expected = width * height
    result = {
        "layer": layer_name,
        "tile_count": len(values),
        "expected_tile_count": expected,
        "shape_matches_dimensions": len(values) == expected,
        "tiles": list(values),
    }
    return result


def _parse_lmu(path: Path, encoding: str) -> dict:
    data = path.read_bytes()
    reader = LcfReader(data, source_name=path.name)
    header = reader.read_header(expected="LcfMapUnit")
    result, _ = _decode_schema(
        reader,
        fields={
            0x01: "chipset_id",
            0x02: "width",
            0x03: "height",
            0x0B: "scroll_type",
            0x1F: "parallax_flag",
            0x20: "parallax_name",
            0x21: "parallax_loop_x",
            0x22: "parallax_loop_y",
            0x23: "parallax_auto_loop_x",
            0x24: "parallax_sx",
            0x25: "parallax_auto_loop_y",
            0x26: "parallax_sy",
            0x28: "generator_flag",
            0x29: "generator_mode",
            0x2A: "top_level",
            0x30: "generator_tiles",
            0x31: "generator_width",
            0x32: "generator_height",
            0x33: "generator_surround",
            0x34: "generator_upper_wall",
            0x35: "generator_floor_b",
            0x36: "generator_floor_c",
            0x37: "generator_extra_b",
            0x38: "generator_extra_c",
            0x3C: "generator_x",
            0x3D: "generator_y",
            0x3E: "generator_tile_ids",
            0x47: "lower_layer",
            0x48: "upper_layer",
            0x51: "events",
            0x5A: "save_count_2k3e",
            0x5B: "save_count",
        },
        encoding=encoding,
        text_fields=(0x20,),
        bool_fields=(
            0x1F,
            0x21,
            0x22,
            0x23,
            0x25,
            0x28,
            0x2A,
            0x33,
            0x34,
            0x35,
            0x36,
            0x37,
            0x38,
        ),
        fixed_fields={
            0x3C: lambda chunk: _decode_fixed_array(
                chunk,
                item_bytes=4,
                signed=False,
            ),
            0x3D: lambda chunk: _decode_fixed_array(
                chunk,
                item_bytes=4,
                signed=False,
            ),
            0x3E: lambda chunk: _decode_fixed_array(
                chunk,
                item_bytes=2,
                signed=True,
            ),
            0x47: lambda chunk: _decode_fixed_array(
                chunk,
                item_bytes=2,
                signed=True,
            ),
            0x48: lambda chunk: _decode_fixed_array(
                chunk,
                item_bytes=2,
                signed=True,
            ),
        },
        nested_fields={0x51: _parse_event_vector},
    )

    defaulted_fields = []
    if "chipset_id" not in result:
        result["chipset_id"] = DEFAULT_MAP_CHIPSET_ID
        defaulted_fields.append("chipset_id")
    result["field_defaults_used"] = defaulted_fields

    width = result.get("width", DEFAULT_MAP_WIDTH)
    height = result.get("height", DEFAULT_MAP_HEIGHT)
    defaulted_dimensions = []
    if "width" not in result:
        defaulted_dimensions.append("width")
        result["width"] = width
    if "height" not in result:
        defaulted_dimensions.append("height")
        result["height"] = height
    result["dimensions"] = {
        "width": width,
        "height": height,
        "defaults_used": defaulted_dimensions,
    }

    for field_name in ("lower_layer", "upper_layer"):
        values = result.get(field_name)
        if isinstance(values, list):
            result[field_name] = _layer_summary(
                values,
                width=width,
                height=height,
                layer_name=field_name,
            )

    if reader.remaining:
        result.setdefault("warnings", []).append(
            f"{reader.remaining} trailing byte(s) remained after RPG map struct"
        )

    return {
        "file": _source_metadata(path, data),
        "header": header,
        "map": result,
    }


def parse_lmt(path: Path | str, *, encoding: str = DEFAULT_ENCODING) -> dict:
    """Parse one RPG_RT.lmt map-tree file without modifying it."""

    return _parse_lmt(Path(path), encoding)


def parse_lmu(path: Path | str, *, encoding: str = DEFAULT_ENCODING) -> dict:
    """Parse one MapNNNN.lmu map file without modifying it."""

    return _parse_lmu(Path(path), encoding)


def parse_project(
    project_dir: Path | str,
    *,
    map_filename: str = "Map0001.lmu",
    encoding: str = DEFAULT_ENCODING,
) -> dict:
    """Parse the database, map tree and one selected map read-only."""

    # Imported lazily because database_parser reuses this module's generic
    # schema and event-command helpers.
    from database_parser import parse_ldb

    project_path = Path(project_dir)
    if not project_path.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project_path}")

    lmt_path = project_path / "RPG_RT.lmt"
    lmu_path = project_path / map_filename
    report = {
        "schema_version": 2,
        "parser": {
            "name": "darkest-journey-lcf",
            "version": "0.2.0",
            "read_only": True,
            "encoding": encoding,
        },
        "project": {
            "directory_name": project_path.name,
            "database_filename": "RPG_RT.ldb",
            "map_filename": map_filename,
        },
        "ldb": parse_ldb(project_path / "RPG_RT.ldb", encoding=encoding),
        "lmt": parse_lmt(lmt_path, encoding=encoding),
        "lmu": parse_lmu(lmu_path, encoding=encoding),
    }
    return report


EVENT_COMMAND_NAMES = {
    10: "END",
    1005: "CallCommonEvent",
    1006: "ForceFlee",
    1007: "EnableCombo",
    1008: "ChangeClass",
    1009: "ChangeBattleCommands",
    10110: "ShowMessage",
    10120: "MessageOptions",
    10130: "ChangeFaceGraphic",
    10140: "ShowChoice",
    10150: "InputNumber",
    10210: "ControlSwitches",
    10220: "ControlVars",
    10230: "TimerOperation",
    10310: "ChangeGold",
    10320: "ChangeItems",
    10330: "ChangePartyMembers",
    10410: "ChangeExp",
    10420: "ChangeLevel",
    10430: "ChangeParameters",
    10440: "ChangeSkills",
    10450: "ChangeEquipment",
    10460: "ChangeHP",
    10470: "ChangeSP",
    10480: "ChangeCondition",
    10490: "FullHeal",
    10500: "SimulatedAttack",
    10610: "ChangeHeroName",
    10620: "ChangeHeroTitle",
    10630: "ChangeSpriteAssociation",
    10640: "ChangeActorFace",
    10650: "ChangeVehicleGraphic",
    10660: "ChangeSystemBGM",
    10670: "ChangeSystemSFX",
    10680: "ChangeSystemGraphics",
    10690: "ChangeScreenTransitions",
    10710: "EnemyEncounter",
    10720: "OpenShop",
    10730: "ShowInn",
    10740: "EnterHeroName",
    10810: "Teleport",
    10820: "MemorizeLocation",
    10830: "RecallToLocation",
    10840: "EnterExitVehicle",
    10850: "SetVehicleLocation",
    10860: "ChangeEventLocation",
    10870: "TradeEventLocations",
    10910: "StoreTerrainID",
    10920: "StoreEventID",
    11010: "EraseScreen",
    11020: "ShowScreen",
    11030: "TintScreen",
    11040: "FlashScreen",
    11050: "ShakeScreen",
    11060: "PanScreen",
    11070: "WeatherEffects",
    11110: "ShowPicture",
    11120: "MovePicture",
    11130: "ErasePicture",
    11210: "ShowBattleAnimation",
    11310: "PlayerVisibility",
    11320: "FlashSprite",
    11330: "MoveEvent",
    11340: "ProceedWithMovement",
    11350: "HaltAllMovement",
    11410: "Wait",
    11510: "PlayBGM",
    11520: "FadeOutBGM",
    11530: "MemorizeBGM",
    11540: "PlayMemorizedBGM",
    11550: "PlaySound",
    11560: "PlayMovie",
    11610: "KeyInputProc",
    11710: "ChangeMapTileset",
    11720: "ChangePBG",
    11740: "ChangeEncounterSteps",
    11750: "TileSubstitution",
    11810: "TeleportTargets",
    11820: "ChangeTeleportAccess",
    11830: "EscapeTarget",
    11840: "ChangeEscapeAccess",
    11910: "OpenSaveMenu",
    11930: "ChangeSaveAccess",
    11950: "OpenMainMenu",
    11960: "ChangeMainMenuAccess",
    12010: "ConditionalBranch",
    12110: "Label",
    12120: "JumpToLabel",
    12210: "Loop",
    12220: "BreakLoop",
    12310: "EndEventProcessing",
    12320: "EraseEvent",
    12330: "CallEvent",
    12410: "Comment",
    12420: "GameOver",
    12510: "ReturntoTitleScreen",
    13110: "ChangeMonsterHP",
    13120: "ChangeMonsterMP",
    13130: "ChangeMonsterCondition",
    13150: "ShowHiddenMonster",
    13210: "ChangeBattleBG",
    13260: "ShowBattleAnimation_B",
    13310: "ConditionalBranch_B",
    13410: "TerminateBattle",
    20110: "ShowMessage_2",
    20140: "ShowChoiceOption",
    20141: "ShowChoiceEnd",
    20710: "VictoryHandler",
    20711: "EscapeHandler",
    20712: "DefeatHandler",
    20713: "EndBattle",
    20720: "Transaction",
    20721: "NoTransaction",
    20722: "EndShop",
    20730: "Stay",
    20731: "NoStay",
    20732: "EndInn",
    22010: "ElseBranch",
    22011: "EndBranch",
    22210: "EndLoop",
    22410: "Comment_2",
    23310: "ElseBranch_B",
    23311: "EndBranch_B",
}
