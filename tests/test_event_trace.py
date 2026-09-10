import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "05_runtime"))

from event_trace import (  # noqa: E402
    CharacterState,
    EventTraceRunner,
    TraceContext,
    TraceLimits,
    TraceOptions,
)
from runtime_providers import (  # noqa: E402
    ProviderDecision,
    RuntimeProviders,
    ScriptedRuntimeProviders,
)


def command(code, parameters=None, *, indent=0, name=None, string=""):
    result = {
        "code": code,
        "indent": indent,
        "parameters": list(parameters or []),
        "string": string,
    }
    if name is not None:
        result["code_name"] = name
    return result


def show(picture_id, x, y, name, *, position_mode=0):
    return command(
        11110,
        [picture_id, position_mode, x, y, 0, 100, 0, 1, 0, 0, 0, 0, 0, 0],
        name="ShowPicture",
        string=name,
    )


class EventTraceTests(unittest.TestCase):
    def test_non_waiting_move_can_be_sampled_at_a_partial_time(self):
        commands = [
            show(1, 0, 0, "train"),
            command(
                11120,
                [1, 0, 100, 0, 0, 100, 0, 0, 0, 0, 0, 0, 0, 0, 10, 0],
                name="MovePicture",
            ),
            command(11410, [5], name="Wait"),
        ]

        result = EventTraceRunner().run(
            commands,
            options=TraceOptions(stop_after_wait=True),
        )

        self.assertEqual(result.status, "checkpoint")
        self.assertEqual(result.frames_elapsed, 30)
        slot = result.context.picture_state.slots[1]
        self.assertEqual((slot.x, slot.y), (100, 0))
        self.assertAlmostEqual(slot.current_x, 50.0)
        self.assertEqual(slot.move_remaining_frames, 30)

    def test_switch_branch_selects_the_matching_picture_and_skips_else(self):
        commands = [
            command(10210, [0, 7, 7, 0], name="ControlSwitches"),
            command(12010, [0, 7, 0, 0, 0, 1], name="ConditionalBranch"),
            show(1, 10, 10, "enabled"),
            command(22010, name="ElseBranch"),
            show(1, 20, 20, "disabled"),
            command(22011, name="EndBranch"),
        ]

        result = EventTraceRunner().run(commands)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.context.picture_state.slots[1].name, "enabled")
        self.assertEqual(result.context.picture_state.slots[1].x, 10)

    def test_loop_budget_stops_an_unbounded_trace(self):
        commands = [
            command(12210, name="Loop"),
            command(12210, name="Loop", indent=1),
            command(22210, name="EndLoop", indent=1),
            command(22210, name="EndLoop"),
        ]

        result = EventTraceRunner(
            limits=TraceLimits(max_loop_iterations=3)
        ).run(commands)

        self.assertEqual(result.status, "budget_exhausted")
        self.assertIn("loop", result.reason)

    def test_common_event_call_resolves_indirect_picture_pointer(self):
        common_events = {
            7: [
                command(10220, [0, 114, 114, 0, 2, 10, 0], name="ControlVars"),
                command(
                    11110,
                    [50113, 0, 160, 180, 0, 100, 0, 1, 0, 0, 0, 0, 0, 0],
                    name="ShowPicture",
                    string="Item_XXXX",
                ),
            ]
        }
        commands = [command(12330, [0, 7, 0], name="CallEvent")]
        context = TraceContext(variables={10: 11, 11: 23, 113: 1})

        result = EventTraceRunner(common_events).run(commands, context)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.context.variables[114], 23)
        self.assertEqual(result.context.picture_state.slots[1].name, "Item_0023")
        self.assertEqual(
            result.context.picture_state.slots[1].source,
            {"kind": "common_event", "id": 7, "command_index": 1},
        )
        self.assertTrue(
            any(
                entry["source"] == {"kind": "common_event", "id": 7}
                for entry in result.path
            )
        )

    def test_character_direction_and_screen_values_drive_picture(self):
        commands = [
            command(10220, [0, 41, 41, 0, 6, 10001, 4], name="ControlVars"),
            command(10220, [0, 42, 42, 0, 6, 10001, 5], name="ControlVars"),
            command(12010, [6, 10001, 1, 0, 0, 1], name="ConditionalBranch"),
            show(20, 41, 42, "Sichtkegel_Rechts2", position_mode=1),
            command(22011, name="EndBranch"),
            command(11410, [0], name="Wait"),
        ]
        context = TraceContext(
            characters={
                10001: CharacterState(
                    x=4,
                    y=5,
                    facing=1,
                    screen_x=123,
                    screen_y=77,
                )
            }
        )

        result = EventTraceRunner().run(
            commands,
            context,
            options=TraceOptions(stop_after_wait=True),
        )

        self.assertEqual(result.status, "checkpoint")
        self.assertEqual(
            (result.context.variables[41], result.context.variables[42]),
            (123, 77),
        )
        self.assertEqual(result.context.picture_state.slots[20].name, "Sichtkegel_Rechts2")
        self.assertEqual(result.context.picture_state.slots[20].current_x, 123)

    def test_message_stops_trace_without_silently_skipping_it(self):
        result = EventTraceRunner().run(
            [show(1, 0, 0, "before"), command(10110, name="ShowMessage")]
        )

        self.assertEqual(result.status, "awaiting_input")
        self.assertEqual(len(result.context.picture_state.slots), 1)
        self.assertEqual(result.context.picture_state.slots[1].name, "before")

    def test_message_provider_completes_continuations_and_records_text(self):
        scripted = ScriptedRuntimeProviders(
            messages=[
                ProviderDecision.complete(wait_frames=2),
                ProviderDecision.complete(),
            ]
        )
        result = EventTraceRunner().run(
            [
                command(10110, name="ShowMessage", string="Hello"),
                command(20110, name="ShowMessage_2", string="world"),
            ],
            options=TraceOptions(providers=RuntimeProviders(message=scripted)),
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.frames_elapsed, 2)
        self.assertEqual(
            result.context.actions,
            [
                {"action": "show_message", "text": "Hello", "continuation": False},
                {"action": "show_message", "text": "world", "continuation": True},
            ],
        )
        self.assertEqual(
            [call["kind"] for call in scripted.calls],
            ["message", "message"],
        )

    def test_keyboard_provider_writes_the_key_to_the_command_variable(self):
        scripted = ScriptedRuntimeProviders(
            keys=[ProviderDecision.complete(value=6)]
        )
        result = EventTraceRunner().run(
            [command(11610, [59, 1, 0, 1, 0], name="KeyInputProc")],
            options=TraceOptions(providers=RuntimeProviders(keyboard=scripted)),
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.context.variables, {59: 6})
        self.assertEqual(
            result.context.actions,
            [{"action": "key_input", "variable_id": 59, "value": 6}],
        )

    def test_movement_provider_applies_only_explicit_character_updates(self):
        scripted = ScriptedRuntimeProviders(
            movements=[
                ProviderDecision.complete(
                    character_updates={1: {"x": 3, "y": 4, "facing": 1}}
                ),
                ProviderDecision.complete(),
            ]
        )
        context = TraceContext(
            characters={1: CharacterState(x=1, y=2, facing=2)}
        )
        result = EventTraceRunner().run(
            [
                command(11330, [0, 1, 0], name="MoveEvent"),
                command(11340, name="ProceedWithMovement"),
            ],
            context,
            options=TraceOptions(providers=RuntimeProviders(movement=scripted)),
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(
            result.context.characters[1],
            CharacterState(x=3, y=4, facing=1),
        )
        self.assertEqual(len(result.context.actions), 2)
        self.assertEqual(scripted.calls[0]["code"], 11330)


if __name__ == "__main__":
    unittest.main()
