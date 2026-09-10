import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "03_rendering"))

from runtime_preview import normalize_trace_spec, run_runtime_traces
from render_batch import load_profiles


def picture_command(picture_id, x, y, name):
    return {
        "code": 11110,
        "string": name,
        "parameters": [
            picture_id,
            0,
            x,
            y,
            0,
            100,
            0,
            0,
            100,
            100,
            100,
            100,
            0,
            0,
        ],
    }


class RuntimePreviewTests(unittest.TestCase):
    def test_checked_in_runtime_scenario_profiles_are_loadable(self):
        profiles = load_profiles(REPO_ROOT / "03_rendering/runtime_scenario_profiles.json")

        self.assertEqual(len(profiles), 7)
        self.assertEqual(
            [profile.name for profile in profiles[:4]],
            [
                "map0002-runtime-flashlight-up",
                "map0002-runtime-flashlight-right",
                "map0002-runtime-flashlight-down",
                "map0002-runtime-flashlight-left",
            ],
        )
        self.assertEqual(profiles[4].variables, {113: 1, 122: 19})
        self.assertEqual(len(profiles[6].traces), 2)

    def test_trace_spec_normalization_keeps_explicit_character_context(self):
        spec = normalize_trace_spec(
            {
                "kind": "common_event",
                "id": 3,
                "fps": 30,
                "characters": {
                    "10001": {"x": 4, "y": 5, "facing": 1, "screen_x": 72}
                },
            }
        )

        self.assertEqual(spec["kind"], "common_event")
        self.assertEqual(spec["id"], 3)
        self.assertEqual(spec["fps"], 30)
        self.assertEqual(
            spec["characters"],
            {"10001": {"facing": 1, "screen_x": 72, "x": 4, "y": 5}},
        )
        self.assertEqual(spec["stop_index"], None)

    def test_common_event_trace_uses_database_commands_and_explicit_state(self):
        database = {
            "commonevents": {
                "records": [
                    {
                        "id": 3,
                        "event_commands": {
                            "commands": [picture_command(20, 72, 88, "cone")]
                        },
                    }
                ]
            }
        }
        map_data = {"events": {"events": []}}

        run = run_runtime_traces(
            database,
            map_data,
            "Map0001.lmu",
            [
                {
                    "kind": "common_event",
                    "id": 3,
                    "characters": {"10001": {"x": 4, "y": 5, "facing": 1}},
                }
            ],
        )

        self.assertEqual(run.results[0]["status"], "completed")
        self.assertEqual(run.results[0]["source"], {"kind": "common_event", "id": 3})
        self.assertEqual(run.picture_state.slots[20].name, "cone")
        self.assertEqual(run.context.characters[10001].facing, 1)


if __name__ == "__main__":
    unittest.main()
