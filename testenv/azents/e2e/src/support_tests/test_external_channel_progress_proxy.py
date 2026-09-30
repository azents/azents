"""Deterministic External Channel progress proxy tests."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

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
    assert barrier.has_progress_issued_for("binding-quiet-123") is True


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
    barrier = proxy._ExternalChannelQuietWorkBarrier()
    barrier.arm("binding-quiet-123")

    barrier.mark_progress_issued("binding-quiet-123")

    assert barrier.evidence() == {
        "armed": True,
        "reached": False,
        "released": False,
        "timed_out": False,
    }
    assert barrier.has_progress_issued_for("binding-quiet-123") is True


def test_quiet_work_barrier_holds_work_progression_until_release() -> None:
    """Repeated attempts keep the Work boundary without blocking inference."""
    sparse_continuation: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": "### Binding `binding-quiet-123`",
            }
        ],
        "tools": [],
    }
    barrier = proxy._ExternalChannelQuietWorkBarrier()
    barrier.arm("binding-quiet-123")
    barrier.mark_progress_issued("binding-quiet-123")

    assert proxy.is_external_channel_progress_request(sparse_continuation) is False
    assert proxy.external_channel_binding(sparse_continuation) == "binding-quiet-123"
    for _ in range(184):
        assert barrier.hold("binding-quiet-123") is True
        assert barrier.complete_progress_boundary("binding-quiet-123") is False
        assert barrier.has_progress_issued_for("binding-quiet-123") is True

    assert barrier.wait_until_reached(timeout=1)
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": False,
        "timed_out": False,
    }

    barrier.release()
    assert barrier.hold("binding-quiet-123") is False
    assert barrier.complete_progress_boundary("binding-quiet-123") is True
    assert barrier.complete_progress_boundary("binding-quiet-123") is False
    assert barrier.has_progress_issued_for("binding-quiet-123") is False

    barrier.arm("binding-rearmed-456")

    assert barrier.evidence() == {
        "armed": True,
        "reached": False,
        "released": False,
        "timed_out": False,
    }
    assert barrier.hold("binding-quiet-123") is False
    assert barrier.evidence()["reached"] is False


def test_quiet_work_barrier_rearm_invalidates_the_old_boundary() -> None:
    """A new generation never reaches another Binding's boundary."""
    barrier = proxy._ExternalChannelQuietWorkBarrier()
    barrier.arm("binding-quiet-123")
    assert barrier.hold("binding-quiet-123") is True
    barrier.arm("binding-next-456")
    assert barrier.hold("binding-quiet-123") is False
    assert barrier.evidence() == {
        "armed": True,
        "reached": False,
        "released": False,
        "timed_out": False,
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
    barrier = proxy._ExternalChannelQuietWorkBarrier()
    barrier.arm("binding-quiet-123")
    barrier.mark_progress_issued("binding-quiet-123")

    assert barrier.has_progress_issued_for("binding-other-456") is False
    assert barrier.hold("binding-other-456") is False
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


@pytest.fixture
def isolated_progress_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the fixture boundaries without starting a listener."""
    monkeypatch.setattr(
        proxy, "_EXTERNAL_CHANNEL_RESPONSES", proxy._ExternalChannelResponseRegistry()
    )
    monkeypatch.setattr(
        proxy,
        "_EXTERNAL_CHANNEL_QUIET_WORK_BARRIER",
        proxy._ExternalChannelQuietWorkBarrier(),
    )
    monkeypatch.setattr(
        proxy,
        "_EXTERNAL_CHANNEL_PROGRESS_SEQUENCES",
        proxy._ExternalChannelProgressSequenceRegistry(),
    )
    monkeypatch.setattr(proxy._State, "external_channel_progress_requests", [])


def _dispatch(
    request: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    *,
    prepared: bool = False,
    expected_status: int = 200,
) -> dict[str, object]:
    """Exercise the real POST dispatcher and writer without I/O."""
    handler = proxy._Handler.__new__(proxy._Handler)
    handler.path = "/v1/responses"
    responses: list[tuple[int, dict[str, object]]] = []
    monkeypatch.setattr(handler, "_read_body", lambda: json.dumps(request).encode())
    monkeypatch.setattr(
        handler,
        "_write_json",
        lambda status, payload: responses.append((status, payload)),
    )
    monkeypatch.setattr(
        handler,
        "_proxy",
        lambda body=None: responses.append((599, {"upstream": True})),
    )
    if prepared:
        handler._dispatch_prepared_request(request, json.dumps(request).encode())
    else:
        handler.do_POST()
    assert len(responses) == 1
    status, payload = responses[0]
    assert status == expected_status, payload
    return payload


def _tool_item(response: dict[str, object]) -> dict[str, object]:
    output = response["output"]
    assert isinstance(output, list) and len(output) == 1
    item = output[0]
    assert isinstance(item, dict)
    assert item["type"] == "function_call"
    return item


def _sparse(
    response: dict[str, object],
    *,
    output: str = "{}",
) -> dict[str, object]:
    return {
        "previous_response_id": response["id"],
        "input": [
            {
                "type": "function_call_output",
                "call_id": _tool_item(response)["call_id"],
                "output": output,
            }
        ],
        "tools": [{"type": "function", "name": "channel_action"}],
    }


def _quiet_request() -> dict[str, object]:
    return {
        "input": [
            {
                "role": "user",
                "content": (
                    "Message Type: EXTERNAL_CHANNEL_TURN\n"
                    "Binding: binding-quiet-123\n\n"
                    "Discord quiet work presence E2E"
                ),
            }
        ],
        "tools": [{"type": "function", "name": "channel_action"}],
    }


@pytest.mark.usefixtures("isolated_progress_proxy")
def test_dispatcher_sparse_setup_completes_without_upstream_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native tool-output-only setup recovers its exact Binding."""
    request = _quiet_request()
    request["input"] = [
        {
            "role": "user",
            "content": (
                "Message Type: EXTERNAL_CHANNEL_TURN\n"
                "Binding: binding-quiet-123\n\n"
                "Discord quiet work setup E2E"
            ),
        }
    ]
    response = _dispatch(request, monkeypatch)
    assert (
        _tool_item(response)["call_id"]
        == proxy._EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID
    )
    completed = _dispatch(_sparse(response), monkeypatch)
    assert completed["status"] == "completed"
    assert "setup_completed" in str(completed["id"])


@pytest.mark.usefixtures("isolated_progress_proxy")
def test_dispatcher_holds_work_through_sparse_retries_and_late_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Late input cannot advance held Work before explicit release."""
    barrier = proxy._EXTERNAL_CHANNEL_QUIET_WORK_BARRIER
    barrier.arm("binding-quiet-123")
    initial = _dispatch(_quiet_request(), monkeypatch)
    assert _tool_item(initial)["call_id"] == proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    initial_arguments = json.loads(str(_tool_item(initial)["arguments"]))
    assert initial_arguments["todo_update"][0]["status"] == "in_progress"
    emitted: set[tuple[object, object, object]] = set()
    previous = initial
    for index in range(184):
        request = _sparse(previous)
        if index == 10:
            request = _quiet_request()
            request["input"] = [
                {
                    "role": "user",
                    "content": (
                        "Message Type: EXTERNAL_CHANNEL_TURN\n"
                        "Binding: binding-quiet-123\n\n"
                        "Provider-native Channel Work progress E2E. Late mention."
                    ),
                }
            ]
        previous = _dispatch(request, monkeypatch)
        item = _tool_item(previous)
        identity = (previous["id"], item["id"], item["call_id"])
        assert identity not in emitted
        emitted.add(identity)
        assert json.loads(str(item["arguments"])) == {
            "mode": "continue",
            "binding": "binding-quiet-123",
            "title": "Investigating error logs…",
        }
        assert barrier.has_progress_issued_for("binding-quiet-123") is True
        assert proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active("binding-quiet-123")
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": False,
        "timed_out": False,
    }
    assert any(
        evidence["binding"] == "binding-quiet-123"
        and evidence["marker_present"] is True
        and evidence["matched"] is True
        and evidence["stage"] == "after_progress"
        for evidence in proxy._State.external_channel_progress_requests[10:]
    )
    barrier.release()
    outcome = _dispatch(_sparse(previous), monkeypatch)
    assert (
        _tool_item(outcome)["call_id"]
        == proxy._EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID
    )
    outcome_arguments = json.loads(str(_tool_item(outcome)["arguments"]))
    assert (
        outcome_arguments["message"] == "I found a release that matches the incident."
    )
    assert outcome_arguments["todo_update"][0]["status"] == "completed"
    failure = _dispatch(_sparse(outcome), monkeypatch)
    assert (
        _tool_item(failure)["call_id"]
        == proxy._EXTERNAL_CHANNEL_FAILURE_PROGRESS_CALL_ID
    )
    request_input = _dispatch(_sparse(failure), monkeypatch)
    assert (
        _tool_item(request_input)["call_id"]
        == proxy._EXTERNAL_CHANNEL_REQUEST_INPUT_CALL_ID
    )
    waiting = _dispatch(_sparse(request_input), monkeypatch)
    assert waiting["id"] == "resp_external_channel_request_input_waiting"
    assert proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_awaiting("binding-quiet-123")
    assert not proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active("binding-quiet-123")


@pytest.mark.usefixtures("isolated_progress_proxy")
def test_dispatcher_resumed_work_holds_then_finishes_from_sparse_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A marker-free participant response cannot finish Work before release."""
    proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.mark_awaiting("binding-quiet-123")
    barrier = proxy._EXTERNAL_CHANNEL_QUIET_WORK_BARRIER
    barrier.arm("binding-quiet-123")
    request = _quiet_request()
    request["input"] = [
        {
            "role": "user",
            "content": (
                "Message Type: EXTERNAL_CHANNEL_TURN\n"
                "Binding: binding-quiet-123\n\nUse the rollback option."
            ),
        }
    ]
    held = _dispatch(request, monkeypatch)
    for _ in range(3):
        held = _dispatch(_sparse(held), monkeypatch)
        assert json.loads(str(_tool_item(held)["arguments"]))["mode"] == "continue"
        assert proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_awaiting(
            "binding-quiet-123"
        )
    assert barrier.evidence()["reached"] is True
    barrier.release()
    finish = _dispatch(_sparse(held), monkeypatch)
    assert _tool_item(finish)["call_id"] == proxy._EXTERNAL_CHANNEL_FINISH_CALL_ID
    assert json.loads(str(_tool_item(finish)["arguments"]))["mode"] == "finish"
    completed = _dispatch(_sparse(finish), monkeypatch)
    assert completed["id"] == "resp_external_channel_request_input_completed"
    assert not proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_awaiting(
        "binding-quiet-123"
    )


def test_response_registry_scopes_new_turn_ids_and_preserves_retry_identity() -> None:
    """New genuine user turns cannot collide with Run-level tool deduplication."""
    registry = proxy._ExternalChannelResponseRegistry()
    request = registry.prepare(_quiet_request())
    first = registry.issue(request, proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID)
    assert first is not None
    assert first[0] == proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    assert registry.issue(request, proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID) == first
    later = _quiet_request()
    later["input"] = [
        {
            "role": "user",
            "content": (
                "Message Type: EXTERNAL_CHANNEL_TURN\n"
                "Binding: binding-quiet-123\n\n"
                "Discord quiet work presence E2E. New human turn."
            ),
        }
    ]
    prepared = registry.prepare(later)
    second = registry.issue(prepared, proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID)
    assert second is not None
    assert all(left != right for left, right in zip(first, second, strict=True))
    items = prepared["input"]
    assert isinstance(items, list)
    continuation = {
        **later,
        "input": [
            *items,
            {"type": "function_call_output", "call_id": second[0], "output": "{}"},
        ],
    }
    assert proxy.has_current_tool_output(
        registry.prepare(continuation), proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    )


@pytest.mark.parametrize("kind", ["unknown", "mismatch", "nested", "human", "mixed"])
def test_response_registry_rejects_unbound_sparse_continuation(kind: str) -> None:
    """Restore only a known response with its exact top-level output."""
    registry = proxy._ExternalChannelResponseRegistry()
    emitted = registry.issue(
        registry.prepare(_quiet_request()), proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    )
    assert emitted is not None
    call_id, response_id, _ = emitted
    item: dict[str, object] = {
        "type": "function_call_output",
        "call_id": call_id,
        "output": "{}",
    }
    request: dict[str, object] = {
        "previous_response_id": response_id,
        "input": [item],
    }
    if kind == "unknown":
        request["previous_response_id"] = "resp_unknown"
    elif kind == "mismatch":
        item["call_id"] = "call_other"
    elif kind == "nested":
        request["input"] = [{"output": item}]
    elif kind == "mixed":
        request["input"] = [
            item,
            {"type": "function_call_output", "call_id": "call_other", "output": "{}"},
        ]
    else:
        request["input"] = [{"role": "user", "content": []}, item]
    assert registry.prepare(request) == request


def test_response_registry_is_bounded_private_and_reset_generation_fenced() -> None:
    """Associations retain no source/output bodies and expire safely on reset."""
    registry = proxy._ExternalChannelResponseRegistry(limit=3)
    request = _quiet_request()
    items = request["input"]
    assert isinstance(items, list) and isinstance(items[0], dict)
    items[0]["content"] = (
        str(items[0]["content"]) + "\nbot_token=source-secret signing_secret=private"
    )
    prepared = registry.prepare(request)
    emitted = [
        registry.issue(prepared, proxy._EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID)
        for _ in range(10)
    ]
    assert all(identity is not None for identity in emitted)
    assert len(registry._responses) == 3
    assert len(registry._aliases) == 3
    assert len(registry._identities) <= 3
    retained = repr((registry._responses, registry._aliases, registry._identities))
    assert "source-secret" not in retained
    assert "signing_secret" not in retained
    latest = emitted[-1]
    assert latest is not None
    sparse: dict[str, object] = {
        "previous_response_id": latest[1],
        "input": [
            {
                "type": "function_call_output",
                "call_id": latest[0],
                "output": "tool-secret",
            }
        ],
    }
    restored = registry.prepare(sparse)
    assert proxy.external_channel_binding(restored) == "binding-quiet-123"
    assert "tool-secret" not in repr(registry._responses)
    registry.clear()
    assert registry.prepare(sparse) == sparse
    replacement = registry.issue(
        registry.prepare(request), proxy._EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID
    )
    assert replacement is not None
    assert all(left != right for left, right in zip(latest, replacement, strict=True))


def test_response_registry_concurrent_emissions_have_unique_held_call_ids() -> None:
    """Concurrent checkpoint writers cannot collide on canonical Run dedup keys."""
    registry = proxy._ExternalChannelResponseRegistry()
    prepared = registry.prepare(_quiet_request())
    with ThreadPoolExecutor(max_workers=8) as executor:
        identities = list(
            executor.map(
                lambda _: registry.issue(
                    prepared, proxy._EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID
                ),
                range(64),
            )
        )
    assert all(identity is not None for identity in identities)
    assert len(set(identities)) == 64
    for index in range(3):
        assert len({identity[index] for identity in identities if identity}) == 64


def test_response_registry_reset_changes_canonical_progress_call_identity() -> None:
    """Reset never reuses the initial progress call ID within the same Run."""
    registry = proxy._ExternalChannelResponseRegistry()
    first = registry.issue(
        registry.prepare(_quiet_request()), proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    )
    assert first is not None
    registry.clear()
    second = registry.issue(
        registry.prepare(_quiet_request()), proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    )
    assert second is not None
    assert all(left != right for left, right in zip(first, second, strict=True))


def _binding_request(binding: str) -> dict[str, object]:
    request = _quiet_request()
    items = request["input"]
    assert isinstance(items, list) and isinstance(items[0], dict)
    items[0]["content"] = str(items[0]["content"]).replace("binding-quiet-123", binding)
    return request


def test_response_registry_canonical_stage_and_aliases_are_binding_scoped() -> None:
    """Session-shared proxy stages preserve first-call assertions per Binding."""
    registry = proxy._ExternalChannelResponseRegistry()
    first = registry.issue(
        registry.prepare(_binding_request("binding-one")),
        proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
    )
    assert first is not None
    registry.clear()
    second = registry.issue(
        registry.prepare(_binding_request("binding-two")),
        proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
    )
    assert second is not None
    assert first[0] == second[0] == proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    assert first[1:] != second[1:]
    third = registry.issue(
        registry.prepare(_binding_request("binding-three")),
        proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
    )
    assert third is not None and third[0] == second[0]
    for binding, identity in [("binding-two", second), ("binding-three", third)]:
        sparse: dict[str, object] = {
            "previous_response_id": identity[1],
            "input": [
                {"type": "function_call_output", "call_id": identity[0], "output": "{}"}
            ],
        }
        restored = registry.prepare(sparse)
        assert proxy.external_channel_binding(restored) == binding
        assert proxy.has_current_tool_output(
            restored, proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
        )


def test_response_registry_saturation_never_recycles_canonical_stage() -> None:
    """Bounded canonical allocations fail closed to unique IDs after capacity."""
    registry = proxy._ExternalChannelResponseRegistry(limit=2)
    identities = [
        registry.issue(
            registry.prepare(_binding_request(binding)),
            proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
        )
        for binding in ("binding-one", "binding-two", "binding-over-cap")
    ]
    assert all(identity is not None for identity in identities)
    assert len(registry._used_stages) == 2
    third = identities[-1]
    assert third is not None
    assert third[0] != proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    registry.clear()
    repeated = registry.issue(
        registry.prepare(_binding_request("binding-over-cap")),
        proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
    )
    assert repeated is not None
    assert repeated[0] != proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID
    assert repeated[0] != third[0]
    assert len(registry._used_stages) == 2


@pytest.mark.usefixtures("isolated_progress_proxy")
def test_dispatcher_rejects_retired_prepared_generation_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reset-fenced 409 cannot repopulate Registry or reactivate old Work."""
    registry = proxy._EXTERNAL_CHANNEL_RESPONSES
    prepared = registry.prepare(_quiet_request())
    registry.issue(prepared, proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID)
    registry.clear(reset_state=proxy._reset_external_channel_progress_state)
    barrier = proxy._EXTERNAL_CHANNEL_QUIET_WORK_BARRIER
    barrier.arm("binding-fresh")
    barrier.mark_progress_issued("binding-fresh")
    proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.start("binding-fresh")
    before = (
        barrier.evidence(),
        dict(registry._responses),
        dict(registry._identities),
        dict(registry._aliases),
        set(registry._used_stages),
    )
    rejected = _dispatch(prepared, monkeypatch, prepared=True, expected_status=409)
    assert "generation retired" in str(rejected)
    assert not proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active("binding-quiet-123")
    assert proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active("binding-fresh")
    assert barrier.has_progress_issued_for("binding-fresh") is True
    assert before == (
        barrier.evidence(),
        dict(registry._responses),
        dict(registry._identities),
        dict(registry._aliases),
        set(registry._used_stages),
    )
    with pytest.raises(proxy._ExternalChannelStaleResponseContext):
        registry.issue(prepared, proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID)
    assert registry._responses == {}


@pytest.mark.usefixtures("isolated_progress_proxy")
def test_registry_dispatch_and_reset_share_one_generation_boundary() -> None:
    """A concurrent reset retires all side effects of the admitted old dispatch."""
    registry = proxy._EXTERNAL_CHANNEL_RESPONSES
    prepared = registry.prepare(_quiet_request())
    entered = threading.Event()
    release = threading.Event()
    resetting = threading.Event()
    reset_done = threading.Event()

    def dispatch() -> None:
        entered.set()
        assert release.wait(timeout=5)
        proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.start("binding-quiet-123")
        proxy._EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.arm("binding-quiet-123")
        registry.issue(prepared, proxy._EXTERNAL_CHANNEL_PROGRESS_CALL_ID)

    def reset() -> None:
        resetting.set()
        registry.clear(reset_state=proxy._reset_external_channel_progress_state)
        reset_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        dispatched = executor.submit(registry.run_if_current, prepared, dispatch)
        assert entered.wait(timeout=5)
        retired = executor.submit(reset)
        assert resetting.wait(timeout=5)
        assert not reset_done.is_set()
        release.set()
        assert dispatched.result(timeout=5) is True
        retired.result(timeout=5)
    assert reset_done.is_set()
    assert registry._responses == {}
    assert not proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active("binding-quiet-123")
    assert proxy._EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.evidence() == {
        "armed": False,
        "reached": False,
        "released": False,
        "timed_out": False,
    }


@pytest.mark.usefixtures("isolated_progress_proxy")
def test_dispatcher_release_retries_preserve_rich_outcome_until_exact_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lost-response retries cannot replace rich outcome with a title-only call."""
    barrier = proxy._EXTERNAL_CHANNEL_QUIET_WORK_BARRIER
    barrier.arm("binding-quiet-123")
    initial = _dispatch(_quiet_request(), monkeypatch)
    held = _dispatch(_sparse(initial), monkeypatch)
    request = _sparse(held)
    barrier.release()
    first = _dispatch(request, monkeypatch)
    second = _dispatch(request, monkeypatch)
    assert first["id"] == second["id"]
    assert _tool_item(first) == _tool_item(second)
    arguments = json.loads(str(_tool_item(first)["arguments"]))
    assert arguments["message"] == "I found a release that matches the incident."
    assert arguments["todo_update"][0]["status"] == "completed"
    assert barrier.has_progress_issued_for("binding-quiet-123") is True
    with ThreadPoolExecutor(max_workers=8) as executor:
        repeated = list(
            executor.map(lambda _: _dispatch(request, monkeypatch), range(16))
        )
    for response in repeated:
        assert response["id"] == first["id"]
        assert _tool_item(response) == _tool_item(first)
    mismatch = {
        **_sparse(first),
        "input": [
            {
                "type": "function_call_output",
                "call_id": _tool_item(held)["call_id"],
                "output": "{}",
            }
        ],
    }
    _dispatch(mismatch, monkeypatch, expected_status=599)
    assert barrier.has_progress_issued_for("binding-quiet-123") is True
    acknowledged = _dispatch(_sparse(first), monkeypatch)
    assert (
        _tool_item(acknowledged)["call_id"]
        == proxy._EXTERNAL_CHANNEL_FAILURE_PROGRESS_CALL_ID
    )
    assert barrier.has_progress_issued_for("binding-quiet-123") is False
    delayed_prepared = proxy._EXTERNAL_CHANNEL_RESPONSES.prepare(request)
    after_ack = _dispatch(request, monkeypatch)
    assert after_ack["id"] == first["id"]
    assert _tool_item(after_ack) == _tool_item(first)
    participant_question = _dispatch(_sparse(acknowledged), monkeypatch)
    _dispatch(_sparse(participant_question), monkeypatch)
    assert proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_awaiting("binding-quiet-123")
    delayed = _dispatch(delayed_prepared, monkeypatch, prepared=True)
    assert delayed["id"] == first["id"]
    assert _tool_item(delayed) == _tool_item(first)
    with ThreadPoolExecutor(max_workers=8) as executor:
        after_waiting = list(
            executor.map(lambda _: _dispatch(request, monkeypatch), range(16))
        )
    for response in after_waiting:
        assert response["id"] == first["id"]
        assert _tool_item(response) == _tool_item(first)
    assert proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_awaiting("binding-quiet-123")
    assert not proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active("binding-quiet-123")


@pytest.mark.usefixtures("isolated_progress_proxy")
def test_dispatcher_retired_outcome_ack_does_not_advance_rearmed_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An outcome from the retired response generation cannot release new Work."""
    registry = proxy._EXTERNAL_CHANNEL_RESPONSES
    barrier = proxy._EXTERNAL_CHANNEL_QUIET_WORK_BARRIER
    barrier.arm("binding-quiet-123")
    initial = _dispatch(_quiet_request(), monkeypatch)
    held = _dispatch(_sparse(initial), monkeypatch)
    barrier.release()
    old_outcome = _dispatch(_sparse(held), monkeypatch)
    registry.clear(reset_state=proxy._reset_external_channel_progress_state)
    barrier.arm("binding-quiet-123")
    new_initial = _dispatch(_quiet_request(), monkeypatch)
    assert _tool_item(new_initial)["call_id"] != _tool_item(initial)["call_id"]
    _dispatch(_sparse(old_outcome), monkeypatch, expected_status=599)
    assert barrier.has_progress_issued_for("binding-quiet-123") is True
    assert barrier.evidence()["released"] is False


def test_response_registry_distinct_arguments_never_reuse_emitted_ids() -> None:
    """Semantic variants stay separate when Binding, turn and stage match."""
    registry = proxy._ExternalChannelResponseRegistry()
    prepared = registry.prepare(_quiet_request())
    rich: dict[str, object] = {"mode": "continue", "message": "fixture-outcome-body"}
    neutral: dict[str, object] = {"mode": "continue", "title": "fixture-neutral-body"}
    first = registry.issue(
        prepared, proxy._EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID, arguments=rich
    )
    second = registry.issue(
        prepared, proxy._EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID, arguments=neutral
    )
    assert first is not None and second is not None
    assert all(left != right for left, right in zip(first, second, strict=True))
    assert (
        registry.issue(
            prepared, proxy._EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID, arguments=rich
        )
        == first
    )
    retained = repr(registry._identities)
    assert "fixture-outcome-body" not in retained
    assert "fixture-neutral-body" not in retained


@pytest.mark.usefixtures("isolated_progress_proxy")
def test_dispatcher_released_replay_is_bounded_and_safe_on_decision_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evicted fingerprints retain exact known-response replay or fail unbound."""
    registry = proxy._ExternalChannelResponseRegistry(limit=6)
    monkeypatch.setattr(proxy, "_EXTERNAL_CHANNEL_RESPONSES", registry)
    barrier = proxy._EXTERNAL_CHANNEL_QUIET_WORK_BARRIER
    barrier.arm("binding-quiet-123")
    initial = _dispatch(_quiet_request(), monkeypatch)
    held = _dispatch(_sparse(initial), monkeypatch)
    barrier.release()
    request = _sparse(held)
    rich = _dispatch(request, monkeypatch)
    _dispatch(_sparse(rich), monkeypatch)
    for index in range(12):
        registry.remember_released_outcome(
            {"_external_channel_fixture_request_key": f"{index:064x}"}
        )
    assert len(registry._released_outcomes) == 6
    replay = _dispatch(request, monkeypatch)
    assert replay["id"] == rich["id"]
    assert _tool_item(replay) == _tool_item(rich)
    for _ in range(12):
        registry.issue(
            registry.prepare(_binding_request("binding-other")),
            proxy._EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID,
        )
    assert len(registry._responses) == 6
    assert len(registry._identities) <= 6
    assert len(registry._released_outcomes) == 6
    before = proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active("binding-quiet-123")
    _dispatch(request, monkeypatch, expected_status=599)
    assert (
        proxy._EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active("binding-quiet-123")
        == before
    )
