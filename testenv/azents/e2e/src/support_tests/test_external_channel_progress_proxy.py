"""Deterministic External Channel progress proxy tests."""

import json
import threading

from support import image_generation_openai_proxy as proxy


def _request() -> dict[str, object]:
    return {
        "instructions": (
            "For a current input explicitly marked as an External Channel turn, "
            "invoke `channel_action`."
        ),
        "input": [
            {
                "role": "user",
                "content": (
                    "Message Type: EXTERNAL_CHANNEL_TURN\n"
                    "Provider: slack\n"
                    "Resource: #e2e\n"
                    "Binding: binding-dynamic-123\n\n"
                    "Provider-native Channel Work progress E2E. "
                    "Ask @User UREVIEWER in #e2e."
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "name": "tool_search",
                "parameters": {"type": "object"},
            },
            {
                "type": "function",
                "name": "unrelated_active_tool",
                "parameters": {"type": "object"},
            },
        ],
    }


def test_progress_proxy_recognizes_resolved_external_turn_and_dynamic_binding() -> None:
    """The fixture activates only after visible Slack references are resolved."""
    request = _request()

    assert proxy.is_external_channel_progress_request(request) is True
    assert proxy.external_channel_binding(request) == "binding-dynamic-123"
    assert proxy.external_channel_progress_evidence(request) == {
        "binding": "binding-dynamic-123",
        "marker_present": True,
        "resolved_user_reference": True,
        "resolved_channel_reference": True,
        "search_tool_available": True,
        "progress_tool_available": False,
    }


def test_progress_proxy_extracts_binding_from_compacted_channel_work() -> None:
    """A continuation can recover its handle from compacted Channel Work."""
    request = _request()
    request["input"] = [
        {
            "role": "user",
            "content": (
                "## Channel Work Snapshot\n\n"
                "### Binding `binding-compacted-456`\n"
                "- Current work title: Continue"
            ),
        }
    ]

    assert proxy.external_channel_binding(request) == "binding-compacted-456"


def test_progress_proxy_distinguishes_continue_and_finish_tool_outputs() -> None:
    """Responses and Chat tool-result shapes advance the deterministic sequence."""
    request = _request()
    initial_input = request["input"]
    assert isinstance(initial_input, list)
    request["input"] = [
        *initial_input,
        {
            "type": "function_call_output",
            "call_id": "call_external_channel_progress",
            "output": "{}",
        },
        {
            "role": "tool",
            "tool_call_id": "call_external_channel_finish",
            "content": "{}",
        },
    ]

    assert (
        proxy.request_has_tool_output(
            request,
            "call_external_channel_progress",
        )
        is True
    )
    assert (
        proxy.request_has_tool_output(
            request,
            "call_external_channel_finish",
        )
        is True
    )
    assert proxy.request_has_tool_output(request, "call_missing") is False


def test_progress_proxy_ignores_non_string_nested_type_values() -> None:
    """Nested schema objects cannot be mistaken for tool-output item types."""
    request = _request()
    request["tools"] = [
        {
            "type": "function",
            "name": "channel_action",
            "parameters": {
                "type": {
                    "unexpected": "object",
                }
            },
        }
    ]

    assert (
        proxy.request_has_tool_output(
            request,
            "call_external_channel_progress",
        )
        is False
    )


def test_progress_proxy_records_unresolved_provider_references() -> None:
    """Raw provider IDs remain visible as precise projection evidence."""
    request = _request()
    request["input"] = [
        {
            "role": "user",
            "content": (
                "Message Type: EXTERNAL_CHANNEL_TURN\n"
                "Binding: binding-dynamic-123\n\n"
                "Provider-native Channel Work progress E2E. "
                "Ask <@UREVIEWER> in <#CRELATED>."
            ),
        }
    ]

    assert proxy.is_external_channel_progress_request(request) is True
    assert proxy.external_channel_progress_evidence(request) == {
        "binding": "binding-dynamic-123",
        "marker_present": True,
        "resolved_user_reference": False,
        "resolved_channel_reference": False,
        "search_tool_available": True,
        "progress_tool_available": False,
    }


def test_quiet_work_barrier_ignores_unmatched_progress_request() -> None:
    """The Discord-only barrier does not activate the existing Slack journey."""
    request = _request()

    assert proxy.is_external_channel_progress_request(request) is True
    assert proxy.is_external_channel_quiet_work_request(request) is False


def test_quiet_work_setup_uses_an_isolated_marker_and_call_ids() -> None:
    """Setup cannot leave normal progress results in the shared transcript."""
    request: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": ("Binding: binding-quiet-123\nDiscord quiet work setup E2E"),
            }
        ],
        "tools": [{"type": "function", "name": "channel_action"}],
    }

    assert proxy.is_external_channel_quiet_work_setup_request(request) is True
    assert proxy.is_external_channel_progress_request(request) is False
    assert proxy._EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID not in {
        proxy._EXTERNAL_CHANNEL_SEARCH_CALL_ID,
        proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
        proxy._EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID,
        proxy._EXTERNAL_CHANNEL_FAILURE_PROGRESS_CALL_ID,
        proxy._EXTERNAL_CHANNEL_FINISH_CALL_ID,
    }


def test_quiet_work_setup_continues_from_its_unique_search_result() -> None:
    """Tool discovery in setup continues only through its isolated call ID."""
    request: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": (
                    "### Binding `binding-quiet-123`\nDiscord quiet work setup E2E"
                ),
            },
            {
                "type": "function_call_output",
                "call_id": proxy._EXTERNAL_CHANNEL_QUIET_WORK_SETUP_SEARCH_CALL_ID,
                "output": "{}",
            },
        ],
        "tools": [{"type": "function", "name": "channel_action"}],
    }

    assert proxy.is_external_channel_quiet_work_setup_request(request) is True
    assert proxy.is_external_channel_progress_request(request) is False


def test_quiet_work_setup_history_does_not_intercept_later_progress() -> None:
    """A later quiet turn is not reclassified from historical setup output."""
    request: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": ("Binding: binding-quiet-123\nDiscord quiet work setup E2E"),
            },
            {
                "type": "function_call_output",
                "call_id": proxy._EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID,
                "output": "{}",
            },
            {
                "role": "user",
                "content": (
                    "Binding: binding-quiet-123\n"
                    "Discord quiet work presence E2E. "
                    "Provider-native Channel Work progress E2E."
                ),
            },
        ],
        "tools": [{"type": "function", "name": "channel_action"}],
    }
    barrier = proxy._ExternalChannelQuietWorkBarrier()
    barrier.arm("binding-quiet-123")
    barrier.mark_progress_issued("binding-quiet-123")

    assert proxy.is_external_channel_quiet_work_setup_request(request) is False
    assert proxy.is_external_channel_progress_request(request) is True
    assert barrier.take_progress_issued("binding-quiet-123") is True


def test_quiet_work_barrier_arm_requires_a_bounded_binding() -> None:
    """The arm endpoint accepts one opaque, bounded Binding handle."""
    assert (
        proxy._external_channel_quiet_work_barrier_binding(
            b'{"binding":"binding-quiet-123"}'
        )
        == "binding-quiet-123"
    )
    assert proxy._external_channel_quiet_work_barrier_binding(b"{}") is None
    assert (
        proxy._external_channel_quiet_work_barrier_binding(b'{"binding":" "}') is None
    )
    assert (
        proxy._external_channel_quiet_work_barrier_binding(
            b'{"binding":"binding/invalid"}'
        )
        is None
    )
    assert (
        proxy._external_channel_quiet_work_barrier_binding(
            b'{"binding":"' + (b"a" * 257) + b'"}'
        )
        is None
    )


def test_quiet_work_barrier_initial_issuance_is_not_held() -> None:
    """Issuing the first progress call records, but does not reach, the barrier."""
    barrier = proxy._ExternalChannelQuietWorkBarrier(timeout_seconds=1)
    barrier.arm("binding-quiet-123")

    barrier.mark_progress_issued("binding-quiet-123")

    assert barrier.evidence() == {
        "armed": True,
        "reached": False,
        "released": False,
        "timed_out": False,
    }
    assert barrier.has_progress_issued_for("binding-quiet-123") is True


def test_quiet_work_barrier_holds_one_sparse_continuation_until_release() -> None:
    """Issued state holds the next scoped continuation without parsing output."""
    sparse_continuation: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": "### Binding `binding-quiet-123`",
            }
        ],
        "tools": [],
    }
    barrier = proxy._ExternalChannelQuietWorkBarrier(timeout_seconds=1)
    barrier.arm("binding-quiet-123")
    barrier.mark_progress_issued("binding-quiet-123")
    result: list[bool] = []

    assert proxy.is_external_channel_progress_request(sparse_continuation) is False
    assert proxy.external_channel_binding(sparse_continuation) == "binding-quiet-123"
    assert barrier.take_progress_issued("binding-quiet-123") is True
    waiter = threading.Thread(
        target=lambda: result.append(barrier.wait_for_release("binding-quiet-123"))
    )
    waiter.start()

    assert barrier.wait_until_reached(timeout=1)
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": False,
        "timed_out": False,
    }

    barrier.release()
    waiter.join(timeout=1)

    assert not waiter.is_alive()
    assert result == [True]
    assert barrier.has_progress_issued_for("binding-quiet-123") is False
    assert barrier.take_progress_issued("binding-quiet-123") is False

    barrier.arm("binding-rearmed-456")

    assert barrier.evidence() == {
        "armed": True,
        "reached": False,
        "released": False,
        "timed_out": False,
    }
    assert barrier.wait_for_release("binding-quiet-123") is True
    assert barrier.evidence()["reached"] is False


def test_quiet_work_barrier_records_bounded_timeout() -> None:
    """An armed boundary fails deterministically when no release arrives."""
    barrier = proxy._ExternalChannelQuietWorkBarrier(timeout_seconds=0.01)
    barrier.arm("binding-quiet-123")

    assert barrier.wait_for_release("binding-quiet-123") is False
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": False,
        "timed_out": True,
    }


def test_quiet_work_barrier_evidence_never_retains_request_payload() -> None:
    """The barrier reports booleans only, even for secret-bearing source input."""
    request = _request()
    request["input"] = [
        {
            "role": "user",
            "content": (
                "Binding: binding-secret-123\n"
                "Discord quiet work presence E2E\n"
                "bot_token=xoxb-secret signing_secret=private-body"
            ),
        }
    ]
    request["tools"] = [{"type": "function", "name": "channel_action"}]
    barrier = proxy._ExternalChannelQuietWorkBarrier()
    barrier.arm("binding-secret-123")

    assert proxy.is_external_channel_quiet_work_request(request) is True
    evidence = barrier.evidence()

    assert evidence == {
        "armed": True,
        "reached": False,
        "released": False,
        "timed_out": False,
    }
    serialized = json.dumps(evidence)
    assert "binding-secret-123" not in serialized
    assert "xoxb-secret" not in serialized
    assert "private-body" not in serialized


def test_quiet_work_barrier_ignores_a_different_binding() -> None:
    """One armed Binding never holds unrelated External Channel work."""
    barrier = proxy._ExternalChannelQuietWorkBarrier(timeout_seconds=0.01)
    barrier.arm("binding-quiet-123")
    barrier.mark_progress_issued("binding-quiet-123")

    assert barrier.has_progress_issued_for("binding-other-456") is False
    assert barrier.take_progress_issued("binding-other-456") is False
    assert barrier.evidence() == {
        "armed": True,
        "reached": False,
        "released": False,
        "timed_out": False,
    }


def test_progress_registry_matches_markerless_compacted_continuation() -> None:
    """An active Binding recognizes current results after compaction."""
    request: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": (
                    "## Channel Work Snapshot\n\n"
                    "### Binding `binding-quiet-123`\n"
                    "- Current work title: Investigating error logs"
                ),
            },
            {
                "type": "function_call_output",
                "call_id": "call_external_channel_progress",
                "output": "{}",
            },
        ],
        "tools": [{"type": "function", "name": "channel_action"}],
    }
    registry = proxy._ExternalChannelProgressSequenceRegistry()
    registry.start("binding-quiet-123")

    assert proxy.is_external_channel_progress_request(request) is False
    assert proxy.has_current_external_channel_progress_result(request) is True
    assert registry.is_active(proxy.external_channel_binding(request)) is True
    assert proxy.is_external_channel_quiet_work_request(request) is False
    assert proxy.external_channel_binding(request) == "binding-quiet-123"


def test_progress_registry_waits_for_a_new_same_binding_user_turn() -> None:
    """A delivered request leaves the sequence inactive but resumable by input."""
    registry = proxy._ExternalChannelProgressSequenceRegistry()
    registry.start("binding-quiet-123")

    registry.mark_awaiting("binding-quiet-123")

    assert registry.is_active("binding-quiet-123") is False
    assert registry.is_awaiting("binding-quiet-123") is True
    registry.clear("binding-quiet-123")
    assert registry.is_awaiting("binding-quiet-123") is False


def test_awaiting_resume_requires_latest_same_binding_human_turn() -> None:
    """Unrelated continuation and another Binding cannot resume waiting Work."""
    same_binding: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": (
                    "Message Type: EXTERNAL_CHANNEL_TURN\n"
                    "Binding: binding-quiet-123\n\n"
                    "Use the rollback option."
                ),
            }
        ]
    }
    unrelated_goal: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": (
                    "## Channel Work Snapshot\n"
                    "### Binding `binding-quiet-123`\n"
                    "Goal continuation"
                ),
            }
        ]
    }
    other_binding: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": (
                    "Message Type: EXTERNAL_CHANNEL_TURN\n"
                    "Binding: binding-other-456\n\n"
                    "Unrelated channel input."
                ),
            }
        ]
    }
    registry = proxy._ExternalChannelProgressSequenceRegistry()
    registry.mark_awaiting("binding-quiet-123")

    assert (
        proxy.latest_external_channel_human_binding(same_binding) == "binding-quiet-123"
    )
    assert registry.is_awaiting(
        proxy.latest_external_channel_human_binding(same_binding)
    )
    assert proxy.latest_external_channel_human_binding(unrelated_goal) is None
    assert not registry.is_awaiting(
        proxy.latest_external_channel_human_binding(unrelated_goal)
    )
    assert (
        proxy.latest_external_channel_human_binding(other_binding)
        == "binding-other-456"
    )
    assert not registry.is_awaiting(
        proxy.latest_external_channel_human_binding(other_binding)
    )


def test_completed_history_does_not_match_a_new_unmarked_late_mention() -> None:
    """Historical tool results cannot restart progress for a later user turn."""
    request: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": (
                    "Binding: binding-quiet-123\n"
                    "Discord quiet work presence E2E. "
                    "Provider-native Channel Work progress E2E."
                ),
            },
            {
                "type": "function_call_output",
                "call_id": proxy._EXTERNAL_CHANNEL_FINISH_CALL_ID,
                "output": "{}",
            },
            {
                "role": "user",
                "content": (
                    "Binding: binding-quiet-123\n"
                    "late explicit mention during quiet work"
                ),
            },
        ],
        "tools": [{"type": "function", "name": "channel_action"}],
    }
    registry = proxy._ExternalChannelProgressSequenceRegistry()
    registry.start("binding-quiet-123")
    registry.clear("binding-quiet-123")

    assert proxy.is_external_channel_progress_request(request) is False
    assert proxy.has_current_external_channel_progress_result(request) is False
    assert registry.is_active("binding-quiet-123") is False


def test_progress_registry_clear_all_resets_active_bindings() -> None:
    """Journal reset removes all active deterministic progress sequences."""
    registry = proxy._ExternalChannelProgressSequenceRegistry()
    registry.start("binding-one")
    registry.start("binding-two")
    registry.mark_awaiting("binding-two")

    registry.clear_all()

    assert registry.is_active("binding-one") is False
    assert registry.is_active("binding-two") is False
    assert registry.is_awaiting("binding-two") is False
