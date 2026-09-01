"""Read-only semantic parser for an RPG Maker 2000/2003 ``RPG_RT.ldb``.

The database is the central source for actors, items, skills, enemies,
troops, tilesets, system settings and common events.  This module deliberately
does not write LCF data.  It decodes the fields that are useful for a first
porting analysis and keeps every field outside the current schema as a compact
descriptor, so adding coverage later does not require losing information.

The field IDs and their primitive types follow the public liblcf LDB chunk
definitions.  The parser reuses the existing event-command decoder from
``project_parser`` so map events and common events receive the same model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Tuple

from lcf_reader import LcfChunk, LcfParseError, LcfReader, StructRead
from project_parser import (
    DEFAULT_ENCODING,
    MAX_VECTOR_ITEMS,
    _decode_counted_raw,
    _decode_fixed_array,
    _decode_raw,
    _decode_schema,
    _parse_event_commands,
    _source_metadata,
)


Schema = Mapping[str, Any]
NestedDecoder = Callable[[LcfChunk, str], Any]


def _flag_array(chunk: LcfChunk) -> dict:
    """Decode an LCF flag array while retaining its exact byte count."""

    return {
        "count": len(chunk.payload),
        "values": [value != 0 for value in chunk.payload],
    }


def _uint32_array(chunk: LcfChunk) -> List[int]:
    return _decode_fixed_array(chunk, item_bytes=4, signed=False)


def _short_array(chunk: LcfChunk) -> List[int]:
    return _decode_fixed_array(chunk, item_bytes=2, signed=True)


def _six_short_arrays(chunk: LcfChunk) -> dict:
    values = _short_array(chunk)
    if len(values) % 6:
        raise LcfParseError(
            f"six-parameter array contains {len(values)} values, not a multiple of 6"
        )
    values_per_parameter = len(values) // 6
    return {
        "parameter_count": 6,
        "values_per_parameter": values_per_parameter,
        "values": [
            values[offset:offset + values_per_parameter]
            for offset in range(0, len(values), values_per_parameter)
        ],
    }


def _struct_payload(
    chunk: LcfChunk,
    encoding: str,
    schema: Schema,
    *,
    allow_eof: bool = False,
) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name=f"ldb chunk 0x{chunk.chunk_id:x}",
        base_offset=chunk.payload_offset,
    )
    result, _ = _decode_schema(
        reader,
        fields=schema["fields"],
        encoding=encoding,
        text_fields=schema.get("text_fields", ()),
        bool_fields=schema.get("bool_fields", ()),
        fixed_fields=schema.get("fixed_fields"),
        nested_fields=schema.get("nested_fields"),
        partial_fields=schema.get("partial_fields"),
        allow_eof=allow_eof,
    )
    return result


def _parse_sound(chunk: LcfChunk, encoding: str) -> dict:
    return _struct_payload(
        chunk,
        encoding,
        {
            "fields": {
                0x01: "name",
                0x03: "volume",
                0x04: "tempo",
                0x05: "balance",
            },
            "text_fields": (0x01,),
        },
    )


def _parse_music(chunk: LcfChunk, encoding: str) -> dict:
    return _struct_payload(
        chunk,
        encoding,
        {
            "fields": {
                0x01: "name",
                0x02: "fadein",
                0x03: "volume",
                0x04: "tempo",
                0x05: "balance",
            },
            "text_fields": (0x01,),
        },
    )


def _finish_declared_command_size(result: dict) -> dict:
    commands = result.get("event_commands")
    declared_size = result.get("event_commands_size")
    if isinstance(commands, dict) and declared_size is not None:
        actual_size = commands.get("payload_length")
        if actual_size != declared_size:
            result.setdefault("warnings", []).append(
                f"event_commands_size declares {declared_size} byte(s), "
                f"but the command field contains {actual_size} byte(s)"
            )
    return result


def _actor_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "title",
            0x03: "character_name",
            0x04: "character_index",
            0x05: "transparent",
            0x07: "initial_level",
            0x08: "final_level",
            0x09: "critical_hit",
            0x0A: "critical_hit_chance",
            0x0F: "face_name",
            0x10: "face_index",
            0x15: "two_weapon",
            0x16: "lock_equipment",
            0x17: "auto_battle",
            0x18: "super_guard",
            0x1F: "parameters",
            0x29: "exp_base",
            0x2A: "exp_inflation",
            0x2B: "exp_correction",
            0x33: "initial_equipment",
            0x38: "unarmed_animation",
            0x39: "class_id",
            0x3B: "battle_x",
            0x3C: "battle_y",
            0x3E: "battler_animation",
            0x3F: "skills",
            0x42: "rename_skill",
            0x43: "skill_name",
            0x47: "state_ranks_size",
            0x48: "state_ranks",
            0x49: "attribute_ranks_size",
            0x4A: "attribute_ranks",
            0x50: "battle_commands",
        },
        "text_fields": (0x01, 0x02, 0x03, 0x0F, 0x43),
        "bool_fields": (
            0x05,
            0x09,
            0x15,
            0x16,
            0x17,
            0x18,
            0x42,
        ),
        "fixed_fields": {
            0x1F: _six_short_arrays,
            0x33: lambda field: _decode_fixed_array(
                field,
                item_bytes=2,
                signed=False,
            ),
            0x48: _short_array,
            0x4A: _short_array,
            0x50: _uint32_array,
        },
        "nested_fields": {
            0x3F: lambda field, _encoding: _decode_counted_raw(
                field, "actor learning"
            ),
        },
    }


def _skill_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "description",
            0x03: "using_message1",
            0x04: "using_message2",
            0x07: "failure_message",
            0x08: "type",
            0x09: "sp_type",
            0x0A: "sp_percent",
            0x0B: "sp_cost",
            0x0C: "scope",
            0x0D: "switch_id",
            0x0E: "animation_id",
            0x10: "sound_effect",
            0x12: "occasion_field",
            0x13: "occasion_battle",
            0x14: "reverse_state_effect",
            0x15: "physical_rate",
            0x16: "magical_rate",
            0x17: "variance",
            0x18: "power",
            0x19: "hit",
            0x1F: "affect_hp",
            0x20: "affect_sp",
            0x21: "affect_attack",
            0x22: "affect_defense",
            0x23: "affect_spirit",
            0x24: "affect_agility",
            0x25: "absorb_damage",
            0x26: "ignore_defense",
            0x29: "state_effects_size",
            0x2A: "state_effects",
            0x2B: "attribute_effects_size",
            0x2C: "attribute_effects",
            0x2D: "affect_attr_defence",
            0x31: "battler_animation",
            0x32: "battler_animation_data",
        },
        "text_fields": (0x01, 0x02, 0x03, 0x04),
        "bool_fields": (
            0x12,
            0x13,
            0x14,
            0x1F,
            0x20,
            0x21,
            0x22,
            0x23,
            0x24,
            0x25,
            0x26,
            0x2D,
        ),
        "fixed_fields": {
            0x2A: _flag_array,
            0x2C: _flag_array,
        },
        "nested_fields": {
            0x10: _parse_sound,
            0x32: lambda field, _encoding: _decode_raw(
                field, "skill battler animation data"
            ),
        },
    }


def _item_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "description",
            0x03: "type",
            0x05: "price",
            0x06: "uses",
            0x0B: "atk_points1",
            0x0C: "def_points1",
            0x0D: "spi_points1",
            0x0E: "agi_points1",
            0x0F: "two_handed",
            0x10: "sp_cost",
            0x11: "hit",
            0x12: "critical_hit",
            0x14: "animation_id",
            0x15: "preemptive",
            0x16: "dual_attack",
            0x17: "attack_all",
            0x18: "ignore_evasion",
            0x19: "prevent_critical",
            0x1A: "raise_evasion",
            0x1B: "half_sp_cost",
            0x1C: "no_terrain_damage",
            0x1D: "cursed",
            0x1F: "entire_party",
            0x20: "recover_hp_rate",
            0x21: "recover_hp",
            0x22: "recover_sp_rate",
            0x23: "recover_sp",
            0x25: "occasion_field1",
            0x26: "ko_only",
            0x29: "max_hp_points",
            0x2A: "max_sp_points",
            0x2B: "atk_points2",
            0x2C: "def_points2",
            0x2D: "spi_points2",
            0x2E: "agi_points2",
            0x33: "using_message",
            0x35: "skill_id",
            0x37: "switch_id",
            0x39: "occasion_field2",
            0x3A: "occasion_battle",
            0x3D: "actor_set_size",
            0x3E: "actor_set",
            0x3F: "state_set_size",
            0x40: "state_set",
            0x41: "attribute_set_size",
            0x42: "attribute_set",
            0x43: "state_chance",
            0x44: "reverse_state_effect",
            0x45: "weapon_animation",
            0x46: "animation_data",
            0x47: "use_skill",
            0x48: "class_set_size",
            0x49: "class_set",
            0x4B: "ranged_trajectory",
            0x4C: "ranged_target",
            0xCA: "max_count",
        },
        "text_fields": (0x01, 0x02),
        "bool_fields": (
            0x0F,
            0x15,
            0x16,
            0x17,
            0x18,
            0x19,
            0x1A,
            0x1B,
            0x1C,
            0x1D,
            0x1F,
            0x25,
            0x26,
            0x39,
            0x3A,
            0x44,
            0x47,
        ),
        "fixed_fields": {
            0x3E: _flag_array,
            0x40: _flag_array,
            0x42: _flag_array,
            0x49: _flag_array,
        },
        "nested_fields": {
            0x46: lambda field, _encoding: _decode_raw(
                field, "item animation data"
            ),
        },
    }


def _enemy_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "battler_name",
            0x03: "battler_hue",
            0x04: "max_hp",
            0x05: "max_sp",
            0x06: "attack",
            0x07: "defense",
            0x08: "spirit",
            0x09: "agility",
            0x0A: "transparent",
            0x0B: "exp",
            0x0C: "gold",
            0x0D: "drop_id",
            0x0E: "drop_prob",
            0x15: "critical_hit",
            0x16: "critical_hit_chance",
            0x1A: "miss",
            0x1C: "levitate",
            0x1F: "state_ranks_size",
            0x20: "state_ranks",
            0x21: "attribute_ranks_size",
            0x22: "attribute_ranks",
            0x2A: "actions",
        },
        "text_fields": (0x01, 0x02),
        "bool_fields": (0x0A, 0x15, 0x1A, 0x1C),
        "fixed_fields": {
            0x20: _short_array,
            0x22: _short_array,
        },
        "nested_fields": {
            0x2A: lambda field, _encoding: _decode_counted_raw(
                field, "enemy action"
            ),
        },
    }


def _troop_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "members",
            0x03: "auto_alignment",
            0x04: "terrain_set_size",
            0x05: "terrain_set",
            0x06: "appear_randomly",
            0x0B: "pages",
        },
        "text_fields": (0x01,),
        "bool_fields": (0x03, 0x06),
        "fixed_fields": {0x05: _flag_array},
        "nested_fields": {
            0x02: lambda field, _encoding: _decode_counted_raw(
                field, "troop member"
            ),
            0x0B: lambda field, _encoding: _decode_counted_raw(
                field, "troop page"
            ),
        },
    }


def _terrain_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "damage",
            0x03: "encounter_rate",
            0x04: "background_name",
            0x05: "boat_pass",
            0x06: "ship_pass",
            0x07: "airship_pass",
            0x09: "airship_land",
            0x0B: "bush_depth",
            0x0F: "footstep",
            0x10: "on_damage_se",
            0x11: "background_type",
            0x15: "background_a_name",
            0x16: "background_a_scrollh",
            0x17: "background_a_scrollv",
            0x18: "background_a_scrollh_speed",
            0x19: "background_a_scrollv_speed",
            0x1E: "background_b",
            0x1F: "background_b_name",
            0x20: "background_b_scrollh",
            0x21: "background_b_scrollv",
            0x22: "background_b_scrollh_speed",
            0x23: "background_b_scrollv_speed",
            0x28: "special_flags",
            0x29: "special_back_party",
            0x2A: "special_back_enemies",
            0x2B: "special_lateral_party",
            0x2C: "special_lateral_enemies",
            0x2D: "grid_location",
            0x2E: "grid_top_y",
            0x2F: "grid_elongation",
            0x30: "grid_inclination",
        },
        "text_fields": (0x01, 0x04, 0x15, 0x1F),
        "bool_fields": (
            0x05,
            0x06,
            0x07,
            0x09,
            0x10,
            0x16,
            0x17,
            0x1E,
            0x20,
            0x21,
        ),
        "fixed_fields": {0x28: _flag_array},
        "nested_fields": {0x0F: _parse_sound},
    }


def _attribute_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "type",
            0x0B: "a_rate",
            0x0C: "b_rate",
            0x0D: "c_rate",
            0x0E: "d_rate",
            0x0F: "e_rate",
        },
        "text_fields": (0x01,),
    }


def _state_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "type",
            0x03: "color",
            0x04: "priority",
            0x05: "restriction",
            0x0B: "a_rate",
            0x0C: "b_rate",
            0x0D: "c_rate",
            0x0E: "d_rate",
            0x0F: "e_rate",
            0x15: "hold_turn",
            0x16: "auto_release_prob",
            0x17: "release_by_damage",
            0x1E: "affect_type",
            0x1F: "affect_attack",
            0x20: "affect_defense",
            0x21: "affect_spirit",
            0x22: "affect_agility",
            0x23: "reduce_hit_ratio",
            0x24: "avoid_attacks",
            0x25: "reflect_magic",
            0x26: "cursed",
            0x27: "battler_animation_id",
            0x29: "restrict_skill",
            0x2A: "restrict_skill_level",
            0x2B: "restrict_magic",
            0x2C: "restrict_magic_level",
            0x2D: "hp_change_type",
            0x2E: "sp_change_type",
            0x33: "message_actor",
            0x34: "message_enemy",
            0x35: "message_already",
            0x36: "message_affected",
            0x37: "message_recovery",
            0x3D: "hp_change_max",
            0x3E: "hp_change_val",
            0x3F: "hp_change_map_steps",
            0x40: "hp_change_map_val",
            0x41: "sp_change_max",
            0x42: "sp_change_val",
            0x43: "sp_change_map_steps",
            0x44: "sp_change_map_val",
        },
        "text_fields": (0x01, 0x33, 0x34, 0x35, 0x36, 0x37),
        "bool_fields": (
            0x1F,
            0x20,
            0x21,
            0x22,
            0x24,
            0x25,
            0x26,
            0x29,
            0x2B,
        ),
    }


def _animation_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "animation_name",
            0x03: "large",
            0x09: "scope",
            0x0A: "position",
        },
        "text_fields": (0x01, 0x02),
        "bool_fields": (0x03,),
    }


def _chipset_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "chipset_name",
            0x03: "terrain_data",
            0x04: "passable_data_lower",
            0x05: "passable_data_upper",
            0x0B: "animation_type",
            0x0C: "animation_speed",
        },
        "text_fields": (0x01, 0x02),
        "fixed_fields": {
            0x03: _short_array,
            0x04: _flag_array,
            0x05: _flag_array,
        },
    }


def _class_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x15: "two_weapon",
            0x16: "lock_equipment",
            0x17: "auto_battle",
            0x18: "super_guard",
            0x1F: "parameters",
            0x29: "exp_base",
            0x2A: "exp_inflation",
            0x2B: "exp_correction",
            0x3E: "battler_animation",
            0x47: "state_ranks_size",
            0x48: "state_ranks",
            0x49: "attribute_ranks_size",
            0x4A: "attribute_ranks",
            0x50: "battle_commands",
        },
        "text_fields": (0x01,),
        "bool_fields": (0x15, 0x16, 0x17, 0x18),
        "fixed_fields": {
            0x1F: _six_short_arrays,
            0x48: _short_array,
            0x4A: _short_array,
            0x50: _uint32_array,
        },
    }


def _battler_animation_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x02: "speed",
        },
        "text_fields": (0x01,),
    }


def _named_schema() -> dict:
    return {
        "fields": {0x01: "name"},
        "text_fields": (0x01,),
    }


RECORD_SCHEMAS: Dict[str, Schema] = {
    "actors": _actor_schema(),
    "skills": _skill_schema(),
    "items": _item_schema(),
    "enemies": _enemy_schema(),
    "troops": _troop_schema(),
    "terrains": _terrain_schema(),
    "attributes": _attribute_schema(),
    "states": _state_schema(),
    "animations": _animation_schema(),
    "chipsets": _chipset_schema(),
    "classes": _class_schema(),
    "battleranimations": _battler_animation_schema(),
    "switches": _named_schema(),
    "variables": _named_schema(),
    "maniac_string_variables": _named_schema(),
}


def _common_event_schema() -> dict:
    return {
        "fields": {
            0x01: "name",
            0x0B: "trigger",
            0x0C: "switch_flag",
            0x0D: "switch_id",
            0x15: "event_commands_size",
            0x16: "event_commands",
        },
        "text_fields": (0x01,),
        "bool_fields": (0x0C,),
        "nested_fields": {0x16: _parse_event_commands},
    }


TERMS_FIELD_NAMES = {
    0x01: "encounter",
    0x02: "special_combat",
    0x03: "escape_success",
    0x04: "escape_failure",
    0x05: "victory",
    0x06: "defeat",
    0x07: "exp_received",
    0x08: "gold_received_a",
    0x09: "gold_received_b",
    0x0A: "item_received",
    0x0B: "attacking",
    0x0C: "enemy_critical",
    0x0D: "actor_critical",
    0x0E: "defending",
    0x0F: "observing",
    0x10: "focus",
    0x11: "autodestruction",
    0x12: "enemy_escape",
    0x13: "enemy_transform",
    0x14: "enemy_damaged",
    0x15: "enemy_undamaged",
    0x16: "actor_damaged",
    0x17: "actor_undamaged",
    0x18: "skill_failure_a",
    0x19: "skill_failure_b",
    0x1A: "skill_failure_c",
    0x1B: "dodge",
    0x1C: "use_item",
    0x1D: "hp_recovery",
    0x1E: "parameter_increase",
    0x1F: "parameter_decrease",
    0x20: "enemy_hp_absorbed",
    0x21: "actor_hp_absorbed",
    0x22: "resistance_increase",
    0x23: "resistance_decrease",
    0x24: "level_up",
    0x25: "skill_learned",
    0x26: "battle_start",
    0x27: "miss",
    0x29: "shop_greeting1",
    0x2A: "shop_regreeting1",
    0x2B: "shop_buy1",
    0x2C: "shop_sell1",
    0x2D: "shop_leave1",
    0x2E: "shop_buy_select1",
    0x2F: "shop_buy_number1",
    0x30: "shop_purchased1",
    0x31: "shop_sell_select1",
    0x32: "shop_sell_number1",
    0x33: "shop_sold1",
    0x36: "shop_greeting2",
    0x37: "shop_regreeting2",
    0x38: "shop_buy2",
    0x39: "shop_sell2",
    0x3A: "shop_leave2",
    0x3B: "shop_buy_select2",
    0x3C: "shop_buy_number2",
    0x3D: "shop_purchased2",
    0x3E: "shop_sell_select2",
    0x3F: "shop_sell_number2",
    0x40: "shop_sold2",
    0x43: "shop_greeting3",
    0x44: "shop_regreeting3",
    0x45: "shop_buy3",
    0x46: "shop_sell3",
    0x47: "shop_leave3",
    0x48: "shop_buy_select3",
    0x49: "shop_buy_number3",
    0x4A: "shop_purchased3",
    0x4B: "shop_sell_select3",
    0x4C: "shop_sell_number3",
    0x4D: "shop_sold3",
    0x50: "inn_a_greeting_1",
    0x51: "inn_a_greeting_2",
    0x52: "inn_a_greeting_3",
    0x53: "inn_a_accept",
    0x54: "inn_a_cancel",
    0x55: "inn_b_greeting_1",
    0x56: "inn_b_greeting_2",
    0x57: "inn_b_greeting_3",
    0x58: "inn_b_accept",
    0x59: "inn_b_cancel",
    0x5C: "possessed_items",
    0x5D: "equipped_items",
    0x5F: "gold",
    0x65: "battle_fight",
    0x66: "battle_auto",
    0x67: "battle_escape",
    0x68: "command_attack",
    0x69: "command_defend",
    0x6A: "command_item",
    0x6B: "command_skill",
    0x6C: "menu_equipment",
    0x6E: "menu_save",
    0x70: "menu_quit",
    0x72: "new_game",
    0x73: "load_game",
    0x75: "exit_game",
    0x76: "status",
    0x77: "row",
    0x78: "order",
    0x79: "wait_on",
    0x7A: "wait_off",
    0x7B: "level",
    0x7C: "health_points",
    0x7D: "spirit_points",
    0x7E: "normal_status",
    0x7F: "exp_short",
    0x80: "lvl_short",
    0x81: "hp_short",
    0x82: "sp_short",
    0x83: "sp_cost",
    0x84: "attack",
    0x85: "defense",
    0x86: "spirit",
    0x87: "agility",
    0x88: "weapon",
    0x89: "shield",
    0x8A: "armor",
    0x8B: "helmet",
    0x8C: "accessory",
    0x92: "save_game_message",
    0x93: "load_game_message",
    0x94: "file",
    0x97: "exit_game_message",
    0x98: "yes",
    0x99: "no",
    0xA1: "maniac_item_received_a",
    0xA2: "maniac_level_up_a",
    0xA3: "maniac_level_up_b",
    0xA4: "maniac_level_up_c",
    0xA5: "maniac_exp_received_a",
    0xA6: "maniac_skill_learned_a",
    0xC8: "easyrpg_item_number_separator",
    0xC9: "easyrpg_skill_cost_separator",
    0xCA: "easyrpg_equipment_arrow",
    0xCB: "easyrpg_status_scene_name",
    0xCC: "easyrpg_status_scene_class",
    0xCD: "easyrpg_status_scene_title",
    0xCE: "easyrpg_status_scene_condition",
    0xCF: "easyrpg_status_scene_front",
    0xD0: "easyrpg_status_scene_back",
    0xD1: "easyrpg_order_scene_confirm",
    0xD2: "easyrpg_order_scene_redo",
    0xD3: "easyrpg_battle2k3_double_attack",
    0xD4: "easyrpg_battle2k3_defend",
    0xD5: "easyrpg_battle2k3_observe",
    0xD6: "easyrpg_battle2k3_charge",
    0xD7: "easyrpg_battle2k3_selfdestruct",
    0xD8: "easyrpg_battle2k3_escape",
    0xD9: "easyrpg_battle2k3_special_combat_back",
    0xDA: "easyrpg_battle2k3_skill",
    0xDB: "easyrpg_battle2k3_item",
}


SYSTEM_FIELDS = {
    0x0A: "ldb_id",
    0x0B: "boat_name",
    0x0C: "ship_name",
    0x0D: "airship_name",
    0x0E: "boat_index",
    0x0F: "ship_index",
    0x10: "airship_index",
    0x11: "title_name",
    0x12: "gameover_name",
    0x13: "system_name",
    0x14: "system2_name",
    0x15: "party_size",
    0x16: "party",
    0x1A: "menu_commands_size",
    0x1B: "menu_commands",
    0x1F: "title_music",
    0x20: "battle_music",
    0x21: "battle_end_music",
    0x22: "inn_music",
    0x23: "boat_music",
    0x24: "ship_music",
    0x25: "airship_music",
    0x26: "gameover_music",
    0x29: "cursor_se",
    0x2A: "decision_se",
    0x2B: "cancel_se",
    0x2C: "buzzer_se",
    0x2D: "battle_se",
    0x2E: "escape_se",
    0x2F: "enemy_attack_se",
    0x30: "enemy_damaged_se",
    0x31: "actor_damaged_se",
    0x32: "dodge_se",
    0x33: "enemy_death_se",
    0x34: "item_se",
    0x3D: "transition_out",
    0x3E: "transition_in",
    0x3F: "battle_start_fadeout",
    0x40: "battle_start_fadein",
    0x41: "battle_end_fadeout",
    0x42: "battle_end_fadein",
    0x47: "message_stretch",
    0x48: "font_id",
    0x51: "selected_condition",
    0x52: "selected_hero",
    0x54: "battletest_background",
    0x5B: "save_count",
    0x5E: "battletest_terrain",
    0x5F: "battletest_formation",
    0x60: "battletest_condition",
    0x61: "equipment_setting",
    0x62: "battletest_alt_terrain",
    0x63: "show_frame",
    0x64: "frame_name",
    0x65: "invert_animations",
    0x6F: "show_title",
}


def _system_schema() -> dict:
    nested: Dict[int, NestedDecoder] = {}
    for field_id in (0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26):
        nested[field_id] = _parse_music
    for field_id in range(0x29, 0x35):
        nested[field_id] = _parse_sound
    return {
        "fields": SYSTEM_FIELDS,
        "text_fields": (
            0x0B,
            0x0C,
            0x0D,
            0x11,
            0x12,
            0x13,
            0x14,
            0x54,
            0x64,
        ),
        "bool_fields": (0x63, 0x65, 0x6F),
        "fixed_fields": {
            0x16: _short_array,
            0x1B: _short_array,
        },
        "nested_fields": nested,
    }


def _battlecommands_schema() -> dict:
    return {
        "fields": {
            0x02: "placement",
            0x04: "death_handler_unused",
            0x06: "row",
            0x07: "battle_type",
            0x09: "unused_display_normal_parameters",
            0x0A: "commands",
            0x0F: "death_handler",
            0x10: "death_event",
            0x14: "window_size",
            0x18: "transparency",
            0x19: "death_teleport",
            0x1A: "death_teleport_id",
            0x1B: "death_teleport_x",
            0x1C: "death_teleport_y",
            0x1D: "death_teleport_face",
        },
        "bool_fields": (0x04, 0x09, 0x0F),
        "fixed_fields": {0x0A: _uint32_array},
    }


ROOT_FIELDS = {
    0x0B: "actors",
    0x0C: "skills",
    0x0D: "items",
    0x0E: "enemies",
    0x0F: "troops",
    0x10: "terrains",
    0x11: "attributes",
    0x12: "states",
    0x13: "animations",
    0x14: "chipsets",
    0x15: "terms",
    0x16: "system",
    0x17: "switches",
    0x18: "variables",
    0x19: "commonevents",
    0x1A: "version",
    0x1B: "commoneventD2",
    0x1C: "commoneventD3",
    0x1D: "battlecommands",
    0x1E: "classes",
    0x1F: "classD1",
    0x20: "battleranimations",
    0x21: "maniac_string_variables",
}


VECTOR_ROOT_FIELDS = {
    "actors",
    "skills",
    "items",
    "enemies",
    "troops",
    "terrains",
    "attributes",
    "states",
    "animations",
    "chipsets",
    "switches",
    "variables",
    "commonevents",
    "classes",
    "battleranimations",
    "maniac_string_variables",
}


def _parse_record_vector(
    chunk: LcfChunk,
    encoding: str,
    *,
    section_name: str,
    schema: Schema,
) -> dict:
    reader = LcfReader(
        chunk.payload,
        source_name=f"ldb {section_name} vector",
        base_offset=chunk.payload_offset,
    )
    count = reader.read_compressed_int()
    if count > MAX_VECTOR_ITEMS:
        raise LcfParseError(
            f"{section_name} count {count} exceeds safety limit {MAX_VECTOR_ITEMS}"
        )

    records: List[dict] = []
    for index in range(count):
        record_id = reader.read_compressed_int()
        record, _ = _decode_schema(
            reader,
            fields=schema["fields"],
            encoding=encoding,
            text_fields=schema.get("text_fields", ()),
            bool_fields=schema.get("bool_fields", ()),
            fixed_fields=schema.get("fixed_fields"),
            nested_fields=schema.get("nested_fields"),
            partial_fields=schema.get("partial_fields"),
        )
        record["id"] = record_id
        record["index"] = index
        if section_name == "commonevents":
            _finish_declared_command_size(record)
        records.append(record)

    return {
        "count": count,
        "records": records,
        "remaining_bytes": reader.remaining,
    }


def _root_vector_decoder(section_name: str) -> NestedDecoder:
    schema = (
        _common_event_schema()
        if section_name == "commonevents"
        else RECORD_SCHEMAS[section_name]
    )

    def decode(chunk: LcfChunk, encoding: str) -> dict:
        return _parse_record_vector(
            chunk,
            encoding,
            section_name=section_name,
            schema=schema,
        )

    return decode


def _parse_terms(chunk: LcfChunk, encoding: str) -> dict:
    return _struct_payload(
        chunk,
        encoding,
        {
            "fields": TERMS_FIELD_NAMES,
            "text_fields": tuple(TERMS_FIELD_NAMES),
        },
    )


def _parse_database_root(reader: LcfReader, encoding: str) -> Tuple[dict, StructRead]:
    nested: Dict[int, NestedDecoder] = {
        chunk_id: _root_vector_decoder(name)
        for chunk_id, name in ROOT_FIELDS.items()
        if name in VECTOR_ROOT_FIELDS
    }
    nested[0x15] = _parse_terms
    nested[0x16] = lambda chunk, value_encoding: _struct_payload(
        chunk,
        value_encoding,
        _system_schema(),
    )
    nested[0x1D] = lambda chunk, value_encoding: _struct_payload(
        chunk,
        value_encoding,
        _battlecommands_schema(),
    )
    nested[0x1B] = lambda chunk, _value_encoding: _decode_raw(
        chunk, "duplicated common-event D2"
    )
    nested[0x1C] = lambda chunk, _value_encoding: _decode_raw(
        chunk, "duplicated common-event D3"
    )
    nested[0x1F] = lambda chunk, _value_encoding: _decode_raw(
        chunk, "duplicated class D1"
    )

    result, read = _decode_schema(
        reader,
        fields=ROOT_FIELDS,
        encoding=encoding,
        nested_fields=nested,
        allow_eof=True,
    )
    result["root_end_offset"] = read.end_offset
    result["root_remaining_bytes"] = read.remaining
    result["root_terminated_at_eof"] = not read.terminated and read.remaining == 0
    result["section_counts"] = {
        name: result[name]["count"]
        for name in VECTOR_ROOT_FIELDS
        if isinstance(result.get(name), dict) and "count" in result[name]
    }
    return result, read


def _parse_ldb(path: Path, encoding: str) -> dict:
    data = path.read_bytes()
    reader = LcfReader(data, source_name=path.name)
    header = reader.read_header(expected="LcfDataBase")
    database, _ = _parse_database_root(reader, encoding)
    if reader.remaining:
        database.setdefault("warnings", []).append(
            f"{reader.remaining} trailing byte(s) remained after RPG_RT.ldb"
        )
    return {
        "file": _source_metadata(path, data),
        "header": header,
        "database": database,
    }


def parse_ldb(path: Path | str, *, encoding: str = DEFAULT_ENCODING) -> dict:
    """Parse one RPG Maker database without modifying it."""

    return _parse_ldb(Path(path), encoding)
