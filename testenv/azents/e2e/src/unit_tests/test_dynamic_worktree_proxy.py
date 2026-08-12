"""Deterministic dynamic-worktree proxy tests."""

from typing import cast

from support import image_generation_openai_proxy as proxy


def _request(message: str) -> dict[str, object]:
    return {
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": message}],
            }
        ]
    }


def test_dynamic_worktree_scenario_parses_create_source() -> None:
    """Parse one exact source Project path."""
    assert proxy._dynamic_worktree_scenario(
        _request("Agent-managed worktree E2E create\nSource: /workspace/agent/source")
    ) == ("create", "/workspace/agent/source", False)


def test_dynamic_worktree_scenario_parses_remove_force() -> None:
    """Parse one exact worktree Project path and explicit force."""
    assert proxy._dynamic_worktree_scenario(
        _request(
            "Agent-managed worktree E2E remove\n"
            "Path: /workspace/agent/sessions/example/worktrees/repo\n"
            "Force: true"
        )
    ) == (
        "remove",
        "/workspace/agent/sessions/example/worktrees/repo",
        True,
    )


def test_dynamic_worktree_scenario_parses_non_force_remove() -> None:
    """Remove the non-force marker from the exact Project path."""
    assert proxy._dynamic_worktree_scenario(
        _request(
            "Agent-managed worktree E2E remove\n"
            "Path: /workspace/agent/sessions/example/worktrees/repo\n"
            "Force: false"
        )
    ) == (
        "remove",
        "/workspace/agent/sessions/example/worktrees/repo",
        False,
    )


def test_dynamic_worktree_scenario_recovers_create_from_tool_output() -> None:
    """Recover the scenario when a fresh Run carries the durable tool result."""
    assert proxy._dynamic_worktree_scenario(
        {
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_dynamic_worktree_create",
                    "output": '{"accepted":true}',
                },
                {
                    "role": "system",
                    "content": (
                        "The requested Agent-managed Git worktree creation "
                        "reached terminal status completed."
                    ),
                },
            ]
        }
    ) == ("create", "", False)


def test_dynamic_worktree_scenario_recovers_forced_remove_from_reminder() -> None:
    """Recover explicit force from the fresh-Run continuation reminder."""
    assert proxy._dynamic_worktree_scenario(
        {
            "input": [
                {
                    "role": "system",
                    "content": (
                        "The requested Agent-managed Git worktree removal reached "
                        "terminal status completed. Force used: true."
                    ),
                }
            ]
        }
    ) == ("remove", "", True)


def test_dynamic_worktree_scenario_prefers_new_reminder_over_old_user_request() -> None:
    """Treat a terminal reminder after the triggering request as continuation."""
    assert proxy._dynamic_worktree_scenario(
        {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Agent-managed worktree E2E remove\n"
                                "Path: /workspace/agent/worktree\n"
                                "Force: false"
                            ),
                        }
                    ],
                },
                {
                    "role": "system",
                    "content": (
                        "The requested Agent-managed Git worktree removal reached "
                        "terminal status failed. Force used: false."
                    ),
                },
            ]
        }
    ) == ("remove", "", False)


def test_dynamic_worktree_scenario_prefers_latest_removal_over_create_history() -> None:
    """Select the latest bridge operation from an accumulated transcript."""
    assert proxy._dynamic_worktree_scenario(
        {
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_dynamic_worktree_create",
                    "output": '{"accepted":true}',
                },
                {
                    "role": "system",
                    "content": (
                        "The requested Agent-managed Git worktree creation "
                        "reached terminal status completed."
                    ),
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_dynamic_worktree_remove_dirty",
                    "output": '{"accepted":true}',
                },
                {
                    "role": "system",
                    "content": (
                        "The requested Agent-managed Git worktree removal reached "
                        "terminal status failed. Force used: false."
                    ),
                },
            ]
        }
    ) == ("remove", "", False)


def test_dynamic_worktree_scenario_prefers_current_force_user_message() -> None:
    """Treat a new force request as initial despite older removal reminders."""
    assert proxy._dynamic_worktree_scenario(
        {
            "input": [
                {
                    "role": "system",
                    "content": (
                        "The requested Agent-managed Git worktree removal reached "
                        "terminal status failed. Force used: false."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Agent-managed worktree E2E remove\n"
                                "Path: /workspace/agent/worktree\n"
                                "Force: true"
                            ),
                        }
                    ],
                },
            ]
        }
    ) == ("remove", "/workspace/agent/worktree", True)


def _external_request(
    *,
    tool_output_call_id: str | None = None,
    terminal_reminder: bool = False,
) -> dict[str, object]:
    items: list[dict[str, object]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Binding: binding-e2e\n"
                        "Agent-managed worktree External Channel continuity E2E\n"
                        "Source: /workspace/agent/external-source"
                    ),
                }
            ],
        }
    ]
    if terminal_reminder:
        items.append(
            {
                "role": "system",
                "content": (
                    "The requested Agent-managed Git worktree creation reached "
                    "terminal status completed."
                ),
            }
        )
    if tool_output_call_id is not None:
        items.append(
            {
                "type": "function_call_output",
                "call_id": tool_output_call_id,
                "output": '{"status":"completed"}',
            }
        )
    return {"input": items}


def test_dynamic_worktree_external_stages_initial_and_continuation() -> None:
    """Classify the source request and the bridge-restored fresh Run."""
    initial = _external_request()
    assert proxy._dynamic_worktree_external_source(initial) == (
        "/workspace/agent/external-source"
    )
    assert proxy._dynamic_worktree_external_stage(initial) == "initial"
    assert (
        proxy._dynamic_worktree_external_stage(
            _external_request(terminal_reminder=True)
        )
        == "continuation"
    )


def test_dynamic_worktree_external_stages_tool_sequence() -> None:
    """Classify Skill, deferred search, and final publication outputs."""
    expected = {
        "call_dynamic_worktree_external_load_skill": "after_skill",
        "call_dynamic_worktree_external_tool_search": "after_search",
        "call_dynamic_worktree_external_finish": "after_finish",
    }
    for call_id, stage in expected.items():
        assert (
            proxy._dynamic_worktree_external_stage(
                _external_request(
                    terminal_reminder=True,
                    tool_output_call_id=call_id,
                )
            )
            == stage
        )


def test_dynamic_worktree_external_ignores_later_removal_request() -> None:
    """Let a later explicit cleanup request use the ordinary remove scenario."""
    request = _external_request(terminal_reminder=True)
    input_items = cast(list[object], request["input"])
    input_items.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Agent-managed worktree E2E remove\n"
                        "Path: /workspace/agent/worktree\n"
                        "Force: false"
                    ),
                }
            ],
        }
    )
    assert proxy._dynamic_worktree_external_stage(request) is None
    assert proxy._dynamic_worktree_scenario(request) == (
        "remove",
        "/workspace/agent/worktree",
        False,
    )
