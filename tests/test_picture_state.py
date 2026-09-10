import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "03_rendering"))

from map_renderer import EventState, _build_picture_state, _control_switches
from picture_state import PictureState


def picture_command(code, parameters, name=None):
    command = {"code": code, "parameters": list(parameters)}
    if name is not None:
        command["string"] = name
    return command


class PictureStateTests(unittest.TestCase):
    def test_control_switches_uses_rpg_maker_on_off_and_toggle_values(self):
        switches = {2: True, 3: False}

        applied, reason, detail = _control_switches(
            picture_command(10210, [0, 1, 1, 0]), switches
        )
        self.assertTrue(applied)
        self.assertIsNone(reason)
        self.assertTrue(switches[1])
        self.assertEqual(detail["operation"], "on")

        _control_switches(picture_command(10210, [0, 2, 2, 1]), switches)
        _control_switches(picture_command(10210, [0, 3, 3, 2]), switches)
        self.assertFalse(switches[2])
        self.assertTrue(switches[3])

    def test_show_move_and_erase_keep_one_runtime_slot(self):
        state = PictureState()
        show = picture_command(
            11110,
            [20, 0, 10, 12, 1, 100, 25, 0, 100, 100, 100, 100, 0, 88],
            "flur",
        )
        move = picture_command(
            11120,
            [20, 0, 30, 40, 0, 150, 10, 0, -10, 20, 30, 40, 1, 7, 12, 1],
        )
        erase = picture_command(11130, [20])

        self.assertTrue(state.apply_command(show, {}))
        self.assertEqual(state.slots[20].effect_power, 0)
        self.assertTrue(state.apply_command(move, {}))
        slot = state.slots[20]
        self.assertEqual((slot.x, slot.y, slot.zoom, slot.top_transparency), (30, 40, 150, 10))
        self.assertEqual(slot.name, "flur")
        self.assertEqual((slot.move_duration, slot.move_wait), (12, True))
        self.assertTrue(state.apply_command(erase, {}))
        self.assertNotIn(20, state.slots)
        self.assertEqual([record["operation"] for record in state.operations], ["show", "move", "erase"])

    def test_variable_coordinates_and_picture_pointer_are_resolved(self):
        state = PictureState()
        variable_position = picture_command(
            11110,
            [3, 1, 7, 8, 0, 100, 0, 0, 100, 100, 100, 100, 0, 0],
            "cursor",
        )
        pointer = picture_command(
            11110,
            [50113, 0, 0, 0, 0, 100, 0, 0, 100, 100, 100, 100, 0, 0],
            "Item_XXXX",
        )

        self.assertTrue(state.apply_command(variable_position, {7: 123, 8: 77}))
        self.assertEqual((state.slots[3].x, state.slots[3].y), (123, 77))
        self.assertTrue(state.apply_command(pointer, {113: 19, 114: 7}))
        self.assertIn(19, state.slots)
        self.assertEqual(state.slots[19].raw_picture_id, 50113)
        self.assertEqual(state.slots[19].name, "Item_0007")
        self.assertEqual(state.slots[19].variable_ids, (113, 114))

    def test_invalid_pointer_is_reported_without_creating_a_slot(self):
        state = PictureState()
        command = picture_command(
            11110,
            [50113, 0, 0, 0, 0, 100, 0, 0, 100, 100, 100, 100, 0, 0],
            "Item_XXXX",
        )

        self.assertFalse(state.apply_command(command, {113: 0, 114: 7}))
        self.assertEqual(state.slots, {})
        self.assertEqual(state.skipped[0]["reason"], "picture pointer variable 113 resolves to 0")

    def test_conservative_parallel_setup_trace_applies_control_variables(self):
        commands = [
            picture_command(10220, [0, 30, 30, 0, 6, 25, 4]),
            picture_command(10220, [0, 31, 31, 0, 6, 25, 5]),
            picture_command(
                11110,
                [20, 1, 30, 31, 1, 100, 0, 0, 100, 100, 100, 100, 0, 0],
                "flur",
            ),
            picture_command(12320, []),
        ]
        selection = {
            "event": {"id": 25, "name": "setup", "x": 4, "y": 2},
            "page": {
                "index": 0,
                "trigger": 4,
                "event_commands": {"commands": commands},
            },
        }

        state, switches, variables, traces = _build_picture_state(
            [selection], EventState()
        )

        self.assertEqual((state.slots[20].x, state.slots[20].y), (72, 48))
        self.assertEqual((switches, variables), ({}, {30: 72, 31: 48}))
        self.assertEqual(traces[0]["status"], "applied")
        self.assertEqual(traces[0]["applied_picture_commands"], 1)

    def test_non_parallel_picture_page_is_not_replayed_as_setup(self):
        selection = {
            "event": {"id": 1, "name": "action"},
            "page": {
                "index": 0,
                "trigger": 0,
                "event_commands": {
                    "commands": [
                        picture_command(
                            11110,
                            [20, 0, 10, 10, 0, 100, 0, 0, 100, 100, 100, 100, 0, 0],
                            "flur",
                        )
                    ]
                },
            },
        }

        state, _switches, _variables, traces = _build_picture_state(
            [selection], EventState()
        )

        self.assertEqual(state.slots, {})
        self.assertEqual(traces[0]["status"], "skipped")
        self.assertIn("not a parallel-process page", traces[0]["reason"])


if __name__ == "__main__":
    unittest.main()
