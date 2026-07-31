"""Deterministic plaintext custom apply-patch proxy tests."""

from support import image_generation_openai_proxy as proxy


def test_apply_patch_scenario_prefers_latest_user_turn_over_historical_calls() -> None:
    """Historical success results cannot override a new traversal turn."""
    request: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": "Apply patch E2E success",
            },
            {
                "type": "custom_tool_call_output",
                "call_id": "call_apply_patch_success",
                "output": "completed",
            },
            {
                "role": "user",
                "content": "Apply patch E2E reject traversal",
            },
            {
                "type": "function_call_output",
                "call_id": "call_apply_patch_success_inspect",
                "output": "completed",
            },
        ]
    }

    assert proxy.apply_patch_scenario(request) == "traversal"


def test_apply_patch_scenario_uses_previous_response_for_continuation() -> None:
    """A continuation without user text follows its immediate response chain."""
    request: dict[str, object] = {
        "previous_response_id": "resp_apply_patch_traversal",
        "input": [
            {
                "type": "custom_tool_call_output",
                "call_id": "call_apply_patch_traversal",
                "output": "failed",
            }
        ],
    }

    assert proxy.apply_patch_scenario(request) == "traversal"


def test_apply_patch_scenario_falls_back_to_current_top_level_tool_output() -> None:
    """A stateless continuation can identify its current top-level call output."""
    request: dict[str, object] = {
        "input": [
            {
                "type": "custom_tool_call_output",
                "call_id": "call_apply_patch_success",
                "output": "completed",
            }
        ]
    }

    assert proxy.apply_patch_scenario(request) == "success"
