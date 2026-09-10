import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "05_runtime"))

from event_scheduler import ParallelScheduler, SchedulerLimits  # noqa: E402
from event_trace import TraceContext  # noqa: E402
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


def common_event(event_id, commands, *, switch_flag=False, switch_id=0):
    return {
        "id": event_id,
        "trigger": 4,
        "switch_flag": switch_flag,
        "switch_id": switch_id,
        "event_commands": {"commands": commands},
    }


def map_page(
    commands,
    *,
    index=0,
    flags=0,
    switch_a_id=None,
    variable_id=None,
    variable_value=None,
    compare_operator=None,
):
    condition = {"flags": flags}
    if switch_a_id is not None:
        condition["switch_a_id"] = switch_a_id
    if variable_id is not None:
        condition["variable_id"] = variable_id
    if variable_value is not None:
        condition["variable_value"] = variable_value
    if compare_operator is not None:
        condition["compare_operator"] = compare_operator
    return {
        "index": index,
        "trigger": 4,
        "condition": condition,
        "event_commands": {"commands": commands},
    }


def map_event(event_id, pages):
    return {"id": event_id, "x": 3, "y": 4, "pages": {"pages": pages}}


def control_variable(variable_id, operation, value):
    return command(
        10220,
        [0, variable_id, variable_id, operation, 0, value, 0],
        name="ControlVars",
    )


class ParallelSchedulerTests(unittest.TestCase):
    def test_waits_are_task_local_and_global_clock_advances_once(self):
        events = [
            common_event(
                1,
                [
                    control_variable(1, 0, 1),
                    command(11410, [0], name="Wait"),
                    control_variable(1, 1, 1),
                    command(11410, [0], name="Wait"),
                ],
            ),
            common_event(
                2,
                [
                    control_variable(1, 1, 10),
                    command(11410, [0], name="Wait"),
                    control_variable(1, 1, 10),
                    command(11410, [0], name="Wait"),
                ],
            ),
        ]

        result = ParallelScheduler(
            events,
            context=TraceContext(),
            limits=SchedulerLimits(max_frames=2),
        ).run(max_frames=2)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.frames_elapsed, 2)
        self.assertEqual(result.context.frame, 2)
        self.assertEqual(result.context.picture_state.current_frame, 2)
        self.assertEqual(result.context.variables[1], 22)
        self.assertEqual(
            [entry["frame"] for entry in result.timeline if entry["task_id"] is None],
            [0, 1],
        )

    def test_nested_common_event_stack_survives_a_wait(self):
        events = [
            common_event(
                1,
                [
                    command(12330, [0, 2, 0], name="CallEvent"),
                    control_variable(1, 1, 10),
                ],
            ),
            common_event(
                2,
                [
                    control_variable(1, 0, 7),
                    command(11410, [0], name="Wait"),
                    control_variable(1, 1, 1),
                ],
            ),
        ]

        result = ParallelScheduler(
            events,
            context=TraceContext(),
            limits=SchedulerLimits(max_frames=2),
        ).run(max_frames=2)

        self.assertEqual(result.context.variables[1], 19)
        self.assertTrue(
            any(
                entry["source"] == {"kind": "common_event", "id": 2}
                and entry["frame_before"] == 1
                for entry in result.path
            )
        )

    def test_completed_parallel_process_restarts_only_on_next_frame(self):
        result = ParallelScheduler(
            [common_event(1, [control_variable(1, 1, 1)])],
            context=TraceContext(),
            limits=SchedulerLimits(max_frames=1),
        ).run(max_frames=1)

        self.assertEqual(result.context.variables[1], 1)
        self.assertEqual(result.context.frame, 1)
        self.assertEqual(result.tasks[0]["restart_count"], 1)
        self.assertEqual(
            [entry["frame_before"] for entry in result.path],
            [0],
        )

    def test_switch_off_pauses_and_reactivation_resumes_same_session(self):
        scheduler = ParallelScheduler(
            [
                common_event(
                    1,
                    [control_variable(1, 1, 1), command(11410, [0], name="Wait")],
                    switch_flag=True,
                    switch_id=7,
                )
            ],
            context=TraceContext(),
        )

        first = scheduler.run(max_frames=2)
        self.assertEqual(first.context.variables.get(1, 0), 0)
        self.assertEqual(first.tasks[0]["status"], "paused")

        scheduler.context.switches[7] = True
        second = scheduler.run(max_frames=1)
        self.assertEqual(second.context.variables[1], 1)
        self.assertEqual(second.context.frame, 3)
        self.assertEqual(second.tasks[0]["status"], "waiting")

    def test_map_page_change_prepares_new_page_for_next_update(self):
        pages = [
            map_page(
                [command(10210, [0, 1, 1, 0], name="ControlSwitches")],
                index=0,
            ),
            map_page(
                [control_variable(1, 0, 2)],
                index=1,
                flags=1,
                switch_a_id=1,
            ),
        ]
        result = ParallelScheduler(
            [],
            [map_event(4, pages)],
            context=TraceContext(),
        ).run(max_frames=2)

        self.assertEqual(result.context.variables[1], 2)
        self.assertEqual(
            [
                (entry["frame_before"], entry["source"]["page_index"])
                for entry in result.path
            ],
            [(0, 0), (1, 1)],
        )

    def test_map_variable_condition_uses_classic_greater_equal_default(self):
        result = ParallelScheduler(
            [],
            [
                map_event(
                    4,
                    [
                        map_page(
                            [control_variable(1, 0, 9)],
                            index=0,
                            flags=4,
                            variable_id=1,
                            variable_value=9,
                        )
                    ],
                )
            ],
            context=TraceContext(variables={1: 9}),
        ).run(max_frames=1)

        self.assertEqual(result.context.variables[1], 9)
        self.assertEqual(result.activation_issues, [])
        self.assertEqual(result.tasks[0]["page_index"], 0)

    def test_map_erase_ends_the_parallel_task(self):
        result = ParallelScheduler(
            [],
            [map_event(4, [map_page([command(12320, name="EraseEvent")])])],
            context=TraceContext(),
        ).run(max_frames=3)

        self.assertEqual(result.context.frame, 3)
        self.assertEqual(
            [entry["status"] for entry in result.path],
            ["executed"],
        )
        self.assertEqual(
            result.timeline[0]["status"],
            "erased",
        )

    def test_diagnostic_mode_keeps_other_tasks_running_after_unsupported_command(self):
        result = ParallelScheduler(
            [
                common_event(1, [command(99999)]),
                common_event(2, [control_variable(1, 0, 5)]),
            ],
            context=TraceContext(),
        ).run(max_frames=1)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.context.variables[1], 5)
        self.assertEqual(result.tasks[0]["status"], "unsupported")
        self.assertEqual(result.tasks[1]["status"], "restarted")

    def test_strict_mode_stops_on_first_blocked_task(self):
        result = ParallelScheduler(
            [
                common_event(1, [command(99999)]),
                common_event(2, [control_variable(1, 0, 5)]),
            ],
            context=TraceContext(),
            strict=True,
        ).run(max_frames=1)

        self.assertEqual(result.status, "unsupported")
        self.assertNotIn(1, result.context.variables)
        self.assertEqual(result.context.frame, 0)

    def test_total_command_budget_prevents_a_partial_global_frame(self):
        result = ParallelScheduler(
            [
                common_event(
                    1,
                    [control_variable(1, 0, 5), control_variable(2, 0, 6)],
                )
            ],
            context=TraceContext(),
            limits=SchedulerLimits(max_total_commands=1),
        ).run(max_frames=1)

        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(result.context.frame, 0)
        self.assertEqual(result.context.variables, {1: 5})

    def test_per_task_budget_yields_and_resumes_on_the_next_frame(self):
        result = ParallelScheduler(
            [
                common_event(
                    1,
                    [
                        control_variable(1, 0, 5),
                        control_variable(2, 0, 6),
                    ],
                )
            ],
            context=TraceContext(),
            limits=SchedulerLimits(max_commands_per_task_frame=1),
        ).run(max_frames=2)

        self.assertEqual(result.context.variables, {1: 5, 2: 6})
        self.assertEqual(
            [
                (entry["frame"], entry["status"])
                for entry in result.timeline
                if entry["task_id"] == "common:1"
            ],
            [(0, "yielded"), (1, "restarted")],
        )

    def test_provider_wait_is_task_local_and_consumed_once_by_scheduler(self):
        scripted = ScriptedRuntimeProviders(
            messages=[ProviderDecision.complete(wait_frames=1)]
        )
        result = ParallelScheduler(
            [
                common_event(
                    1,
                    [
                        command(10110, name="ShowMessage", string="Hello"),
                        control_variable(1, 0, 7),
                    ],
                )
            ],
            context=TraceContext(),
            providers=RuntimeProviders(message=scripted),
            limits=SchedulerLimits(max_frames=2),
        ).run(max_frames=2)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.context.variables, {1: 7})
        self.assertEqual(result.context.frame, 2)
        self.assertEqual(scripted.calls, [{"kind": "message", "code": 10110, "decision": "completed"}])
        self.assertEqual(
            [
                (entry["frame"], entry["status"])
                for entry in result.timeline
                if entry["task_id"] == "common:1"
            ],
            [(0, "waiting"), (1, "restarted")],
        )


if __name__ == "__main__":
    unittest.main()
