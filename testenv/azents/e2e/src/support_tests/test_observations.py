"""Pure contracts for E2E observation ingress, without infrastructure.

Generated HTTP models tolerate unknown envelope extensions and retain opaque
event payloads. Narrow fixture/event projections retain extension fields and
preserve optional-field omission separately from explicit null.
"""

import json

import pytest
import requests
from pydantic import ValidationError

from support.observations import (
    ChatActionObservation,
    InputMessageObservation,
    RunMarkerObservation,
    RuntimeHookObservation,
    SeleniumStatusObservation,
    SystemErrorObservation,
    ToolCallObservation,
    TurnMarkerObservation,
    decode_bootstrap_status,
    decode_browser_transport,
    decode_chat_write,
    decode_historical_memory,
    decode_history_page,
    decode_runtime_hook,
    decode_runtime_providers,
    decode_session,
    decode_subagent_tree,
)
from tests.required.public import test_agent_execution_persistence as persistence


def _event(event_id: str, kind: str, payload: dict[str, object]) -> dict[str, object]:
    """Supply the generated durable envelope, keeping payload values opaque."""
    return {
        "id": event_id,
        "session_id": "session",
        "kind": kind,
        "payload": payload,
        "schema_version": "1",
        "created_at": "2026-10-03T00:00:00Z",
        "future_envelope": {"new": True},
    }


def _page(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "items": events,
        "has_more": False,
        "has_newer": False,
        "next_cursor": None,
        "previous_cursor": None,
        "future_page": True,
    }


def _response(payload: object) -> requests.Response:
    """Inject an HTTP response without opening a listener or connection."""
    response = requests.Response()
    response.status_code = 200
    response.encoding = "utf-8"
    response._content = json.dumps(payload).encode()
    return response


def test_history_contract_preserves_opaque_payload_and_tolerates_extensions() -> None:
    payload: dict[str, object] = {
        "content": "hello",
        "future_payload": {"array": [1, None, {"new": True}]},
    }
    page = decode_history_page(_page([_event("event", "user_message", payload)]))
    assert page.items[0].id == "event"
    assert page.items[0].payload == payload
    assert page.items[0].additional_properties == {"future_envelope": {"new": True}}
    assert page.model_dump(mode="json", exclude_unset=True)["future_page"] is True
    assert page.next_cursor is None
    assert "next_cursor" in page.model_fields_set


def test_history_omitted_and_null_cursor_remain_distinct() -> None:
    omitted = decode_history_page({"items": [], "has_more": False})
    explicit = decode_history_page(
        {"items": [], "has_more": False, "next_cursor": None}
    )
    assert omitted.next_cursor is explicit.next_cursor is None
    assert "next_cursor" not in omitted.model_fields_set
    assert "next_cursor" in explicit.model_fields_set


@pytest.mark.parametrize("invalid", ["true", 1, None])
def test_history_rejects_non_boolean_pagination(invalid: object) -> None:
    payload = _page([])
    payload["has_more"] = invalid
    with pytest.raises(ValidationError):
        decode_history_page(payload)


@pytest.mark.parametrize("missing", ["id", "session_id", "kind", "schema_version"])
def test_history_rejects_missing_required_event_metadata(missing: str) -> None:
    event = _event("event", "user_message", {"content": "hello"})
    del event[missing]
    with pytest.raises(ValidationError):
        decode_history_page(_page([event]))


def test_input_projection_preserves_extensions_and_omission() -> None:
    omitted = InputMessageObservation.model_validate({"content": "hello"})
    explicit = InputMessageObservation.model_validate(
        {"content": "hello", "summary": None, "future": [None, True]}
    )
    assert "summary" not in omitted.model_fields_set
    assert "summary" in explicit.model_fields_set
    assert explicit.model_dump(exclude_unset=True) == {
        "content": "hello",
        "summary": None,
        "future": [None, True],
    }


def test_input_profile_requires_explicit_nullable_effort() -> None:
    profile = {
        "model_target_label": "Quality",
        "enabled_execution_options": ["fast"],
    }
    with pytest.raises(ValidationError):
        InputMessageObservation.model_validate({"requested_inference_profile": profile})
    profile["reasoning_effort"] = None
    observation = InputMessageObservation.model_validate(
        {"requested_inference_profile": profile}
    )
    assert observation.requested_inference_profile is not None
    assert observation.requested_inference_profile.reasoning_effort is None


@pytest.mark.parametrize("invalid", [True, "12", 12.5])
def test_turn_usage_rejects_coerced_token_evidence(invalid: object) -> None:
    with pytest.raises(ValidationError):
        TurnMarkerObservation.model_validate({"usage": {"prompt_tokens": invalid}})


def test_turn_provenance_and_usage_retain_opaque_extensions() -> None:
    marker = TurnMarkerObservation.model_validate(
        {
            "usage": {"prompt_tokens": 1, "future_usage": {"provider": [1, None]}},
            "applied_inference_profile": {
                "model_target_label": "Quality",
                "model_display_name": "Model",
                "reasoning_effort": None,
                "enabled_execution_options": ["fast"],
            },
            "effective_context_window_tokens": 32000,
            "future_marker": True,
        }
    )
    assert marker.usage is not None
    assert marker.usage.model_extra == {"future_usage": {"provider": [1, None]}}
    assert marker.applied_inference_profile is not None
    assert marker.applied_inference_profile.model_target_label == "Quality"
    assert marker.effective_context_window_tokens == 32000
    assert marker.model_extra == {"future_marker": True}


def test_fast_turn_tolerates_null_omitting_event_profile_transport() -> None:
    profile: dict[str, object] = {
        "model_target_label": "Fast",
        "enabled_execution_options": [],
    }
    omitted = TurnMarkerObservation.model_validate(
        {"applied_inference_profile": profile}
    ).applied_inference_profile
    explicit = TurnMarkerObservation.model_validate(
        {"applied_inference_profile": {**profile, "reasoning_effort": None}}
    ).applied_inference_profile
    assert omitted is not None and explicit is not None
    assert omitted.reasoning_effort is explicit.reasoning_effort is None
    assert "reasoning_effort" not in omitted.model_fields_set
    assert "reasoning_effort" in explicit.model_fields_set


def test_toolkit_source_and_arguments_are_separate_contracts() -> None:
    arguments: dict[str, object] = {"nested": [True, None, {"opaque": "value"}]}
    observation = ToolCallObservation.model_validate(
        {
            "call_id": "call",
            "name": "tool",
            "arguments": arguments,
            "toolkit_source": {
                "toolkit_config_id": "config",
                "toolkit_name": "Toolkit",
                "toolkit_slug": "toolkit",
                "toolkit_namespace": "namespace",
                "source_identity": {"route": "selected"},
                "future_source": True,
            },
        }
    )
    assert observation.arguments == arguments
    assert observation.toolkit_source is not None
    assert observation.toolkit_source.toolkit_namespace == "namespace"
    assert observation.toolkit_source.model_extra == {"future_source": True}


def test_failed_run_attempts_use_actual_wire_field_names() -> None:
    error = SystemErrorObservation.model_validate(
        {
            "failure": {
                "kind": "failed_run",
                "failed_attempt_count": 1,
                "attempts": [
                    {
                        "attempt_number": 1,
                        "user_message": "Safe provider error",
                        "retryability": "unknown",
                        "failure_code": None,
                    }
                ],
            }
        }
    )
    assert error.failure is not None and error.failure.attempts is not None
    assert error.failure.attempts[0].attempt_number == 1
    assert error.failure.attempts[0].user_message == "Safe provider error"
    assert error.failure.attempts[0].failure_code is None


def test_unrelated_system_error_does_not_require_failed_run_controls() -> None:
    error = SystemErrorObservation.model_validate(
        {"message": "Unrelated error", "future_error": True}
    )
    assert error.failure is None


def test_ws_action_decodes_history_and_preserves_native_identity() -> None:
    action = ChatActionObservation.model_validate(
        {
            "type": "history_event_appended",
            "session_id": "session",
            "event": _event("event", "user_message", {"content": "hello"}),
            "future_action": True,
        }
    )
    assert action.event is not None
    assert action.event.id == "event"
    assert action.session_id == "session"
    assert action.model_extra == {"future_action": True}


def test_ws_action_optional_identity_preserves_omission() -> None:
    action = ChatActionObservation.model_validate({"type": "subagent_tree_changed"})
    assert action.session_id is None
    assert "session_id" not in action.model_fields_set


@pytest.mark.parametrize(
    "action_type",
    [
        "history_event_appended",
        "mailbox_item_upserted",
        "mailbox_item_removed",
        "legacy_message",
    ],
)
def test_ws_action_rejects_missing_variant_evidence(action_type: str) -> None:
    with pytest.raises(ValidationError):
        ChatActionObservation.model_validate(
            {"type": action_type, "session_id": "session"}
        )


def test_health_ack_tolerates_omitted_optional_request_id() -> None:
    action = ChatActionObservation.model_validate(
        {"type": "subscription_health_check_ack", "session_id": "session"}
    )
    assert action.request_id is None
    assert "request_id" not in action.model_fields_set


@pytest.mark.parametrize("invalid", ["false", 0, None])
def test_readiness_requires_real_boolean(invalid: object) -> None:
    with pytest.raises(ValidationError):
        decode_bootstrap_status({"available": invalid})
    with pytest.raises(ValidationError):
        SeleniumStatusObservation.model_validate({"value": {"ready": invalid}})


def test_bootstrap_readiness_tolerates_extension_fields() -> None:
    assert (
        decode_bootstrap_status({"available": False, "future": True}).available is False
    )
    status = SeleniumStatusObservation.model_validate(
        {"value": {"ready": True, "message": "ready"}, "future": True}
    )
    assert status.value.ready is True


def test_write_contract_decodes_complete_snapshot_and_null_run() -> None:
    write = decode_chat_write(
        {
            "session_id": "session",
            "client_request_id": "request",
            "accepted": {"type": "mailbox_item", "id": "mailbox"},
            "snapshot": {
                "partial_history_events": [],
                "mailbox_items": [],
                "run": None,
                "session_run_state": "idle",
                "future": True,
            },
            "history_reload_required": False,
            "future_write": True,
        }
    )
    assert write.session_id == "session"
    assert write.accepted.id == "mailbox"
    assert write.snapshot.run is None
    assert write.snapshot.session_run_state == "idle"


def test_subagent_tree_recursively_decodes_generated_node_contract() -> None:
    node: dict[str, object] = {
        "session_agent_id": "child-agent",
        "agent_session_id": "child-session",
        "name": "child",
        "path": "/root/child",
        "agent_type": "default",
        "status": "completed",
        "unread_result": False,
        "children": None,
        "future_node": True,
    }
    tree = decode_subagent_tree(
        {
            "root_session_agent_id": "root-agent",
            "root_agent_session_id": "root-session",
            "current_session_agent_id": "root-agent",
            "nodes": [node],
        }
    )
    assert tree.nodes[0].agent_session_id == "child-session"
    assert tree.nodes[0].children is None


@pytest.mark.parametrize(
    "evidence",
    [{"error": "upload failed"}, {"echoBody": {}}, {"error": 12}],
)
def test_browser_transport_failure_never_becomes_success(evidence: object) -> None:
    with pytest.raises(AssertionError):
        decode_browser_transport(evidence)


def test_persistence_helpers_operate_on_typed_events_and_opaque_results() -> None:
    result: dict[str, object] = {"new_provider_result": [1, None]}
    page = decode_history_page(
        _page(
            [
                _event("input", "user_message", {"content": "hello"}),
                _event("call", "client_tool_call", {"call_id": "c", "name": "tool"}),
                _event(
                    "result", "client_tool_result", {"call_id": "c", "output": result}
                ),
                _event("turn", "turn_marker", {"usage": {"total_tokens": 2}}),
                _event("run", "run_marker", {"status": "completed"}),
            ]
        )
    )
    assert persistence._message_contents(page) == ["hello"]
    assert persistence._tool_call_names(page) == ["tool"]
    assert persistence._tool_result_call_ids(page) == ["c"]
    assert persistence._tool_result_content(page, "c") == result
    assert persistence._run_complete_ids(page) == ["run"]
    assert persistence._turn_usage_items(page)[0].total_tokens == 2
    assert persistence._message_roles(page) == [
        "user",
        "assistant",
        "tool",
        "turn_complete",
        "run_complete",
    ]


def test_history_http_helper_decodes_before_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response(_page([_event("input", "user_message", {"content": "hello"})]))
    monkeypatch.setattr(persistence.requests, "get", lambda *args, **kwargs: response)
    page = persistence._list_history(
        server_url="http://injected.invalid", token="token", session_id="session"
    )
    assert page.items[0].id == "input"
    assert persistence._message_contents(page) == ["hello"]
    assert persistence.list_history(
        server_url="http://injected.invalid", token="token", session_id="session"
    )["items"]
    wire_events = persistence.history_events(
        persistence.list_history(
            server_url="http://injected.invalid", token="token", session_id="session"
        )
    )
    # Compatibility egress must contain JSON timestamps, not datetime objects.
    json.dumps(wire_events)
    assert isinstance(wire_events[0]["created_at"], str)
    assert wire_events[0]["future_envelope"] == {"new": True}


def test_terminal_marker_rejects_non_string_status() -> None:
    with pytest.raises(ValidationError):
        RunMarkerObservation.model_validate({"status": True})


def _session() -> dict[str, object]:
    """Supply all required nullable fields of the generated Session contract."""
    return {
        "id": "session",
        "agent_id": "agent",
        "current_model_target_label": "Quality",
        "current_reasoning_effort": None,
        "current_enabled_execution_options": ["fast"],
        "title": None,
        "title_source": None,
        "status": "active",
        "product_mode": None,
        "run_state": "idle",
        "pinned": False,
        "unread_terminal_run_id": None,
        "auto_archive_after": None,
        "archived_at": None,
        "purge_after": None,
        "archive_retention_days_snapshot": None,
        "created_at": "2026-10-03T00:00:00Z",
        "updated_at": "2026-10-03T00:00:00Z",
        "future_session": True,
    }


def test_session_identity_readiness_and_profile_use_generated_contract() -> None:
    session = decode_session(_session())
    assert session.id == "session"
    assert session.current_model_target_label == "Quality"
    assert session.current_reasoning_effort is None
    assert session.current_enabled_execution_options == ["fast"]
    assert session.run_state == "idle"
    assert session.primary_kind is None
    assert "primary_kind" not in session.model_fields_set
    assert "current_reasoning_effort" in session.model_fields_set


@pytest.mark.parametrize(
    ("field", "invalid"),
    [("id", 12), ("run_state", "unknown"), ("pinned", "false")],
)
def test_session_rejects_invalid_interpreted_evidence(
    field: str,
    invalid: object,
) -> None:
    payload = _session()
    payload[field] = invalid
    with pytest.raises(ValidationError):
        decode_session(payload)


def test_runtime_provider_readiness_and_opaque_capabilities() -> None:
    capabilities: dict[str, object] = {"future_capability": [None, True]}
    providers = decode_runtime_providers(
        {
            "items": [
                {
                    "id": "row",
                    "provider_id": "provider",
                    "scope": "system",
                    "workspace_id": None,
                    "kind": "docker",
                    "display_name": "Docker",
                    "registration_method": "registered",
                    "enabled": True,
                    "lifecycle_state": "active",
                    "availability_mode": "platform_wide",
                    "current_contract_revision_id": "contract",
                    "active_config_revision_id": None,
                    "admin_version": 1,
                    "capabilities": capabilities,
                    "config_schema": None,
                    "metadata": None,
                    "future_provider": True,
                }
            ],
        }
    )
    assert providers.items[0].provider_id == "provider"
    assert providers.items[0].current_contract_revision_id == "contract"
    assert providers.items[0].active_config_revision_id is None
    assert providers.items[0].capabilities == capabilities


def test_historical_memory_generated_lifecycle_projection() -> None:
    detail = decode_historical_memory(
        {
            "source_session_id": "source",
            "scope": "team",
            "source_title": None,
            "source_activity_through": "2026-10-03T00:00:00Z",
            "prepared_at": "2026-10-03T00:01:00Z",
            "summary": "Prepared summary",
            "source_path": "azents://historical/source",
            "future_memory": True,
        }
    )
    assert detail.source_session_id == "source"
    assert detail.source_title is None
    assert detail.prepared_at > detail.source_activity_through
    assert detail.summary == "Prepared summary"


def test_live_retry_polling_uses_generated_retry_and_attempt_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response(
        {
            "partial_history": {"items": []},
            "mailbox_items": [],
            "session_run_state": "running",
            "run": {
                "run_id": "run",
                "phase": "waiting_for_model",
                "status": "running",
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
                "using_fallback": False,
                "model_call_started_at": None,
                "retry": {
                    "error_kind": "model_provider",
                    "status": "waiting",
                    "last_error_message": "Safe error",
                    "failed_attempt_count": 1,
                    "max_retries": 3,
                    "backoff_seconds": 1,
                    "next_retry_at": "later",
                    "attempts": [
                        {
                            "attempt_number": 1,
                            "user_message": "Safe error",
                            "error_type": "ProviderError",
                            "source": "provider",
                            "failed_at": "earlier",
                            "backoff_seconds": 1,
                            "next_retry_at": "later",
                            "retryability": "unknown",
                            "truncated": False,
                            "future_attempt": True,
                        }
                    ],
                    "future_retry": True,
                },
            },
        }
    )
    monkeypatch.setattr(persistence.requests, "get", lambda *args, **kwargs: response)
    live = persistence._wait_for_live_retry(
        server_url="http://injected.invalid",
        token="token",
        session_id="session",
        failed_attempt_count=1,
    )
    assert live.run is not None and live.run.retry is not None
    assert live.run.retry.failed_attempt_count == 1
    assert live.run.retry.attempts[0].user_message == "Safe error"
    assert live.run.retry.attempts[0].failure_code is None


def test_idle_polling_reads_authoritative_generated_live_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response(
        {
            "partial_history": {"items": []},
            "mailbox_items": [],
            "session_run_state": "idle",
            "run": None,
            "future_live": True,
            "action_executions": [
                {
                    "execution": {
                        "id": "execution",
                        "source_mailbox_item_id": "mailbox",
                        "sender_user_id": None,
                        "action_type": "create_session_working_folder",
                        "action": {
                            "type": "create_session_working_folder",
                            "future_context": {"opaque": ["retained", None]},
                        },
                        "result": {
                            "phase": "completed",
                            "outcome": "ready",
                            "reason_code": None,
                        },
                        "status": "completed",
                        "owner_generation": 1,
                        "updated_at": "2026-10-03T00:00:00Z",
                        "future_execution": {"opaque": ["retained", None]},
                    },
                    "events": [],
                    "future_projection": True,
                }
            ],
        }
    )
    monkeypatch.setattr(persistence.requests, "get", lambda *args, **kwargs: response)
    persistence._wait_for_session_idle(
        server_url="http://injected.invalid",
        token="token",
        session_id="session",
        timeout=1,
    )
    live = persistence._list_live(
        server_url="http://injected.invalid",
        token="token",
        session_id="session",
    )
    assert live.additional_properties["future_live"] is True
    assert live.action_executions is not None
    projection = live.action_executions[0]
    assert projection.additional_properties["future_projection"] is True
    execution = projection.execution
    assert execution.result is not None
    assert execution.result["phase"].to_dict() == "completed"
    assert execution.result["outcome"].to_dict() == "ready"
    assert execution.result["reason_code"].to_dict() is None
    assert execution.additional_properties["future_execution"] == {
        "opaque": ["retained", None]
    }
    action_wire = execution.action.to_dict()
    assert isinstance(action_wire, dict)
    assert action_wire["future_context"] == {"opaque": ["retained", None]}
    wire = persistence.list_live(
        server_url="http://injected.invalid",
        token="token",
        session_id="session",
    )
    projections = persistence.json_object_list_payload(
        wire["action_executions"], label="action execution projections"
    )
    execution_wire = persistence.json_object_payload(
        projections[0]["execution"], label="action execution"
    )
    assert execution_wire["result"] == {
        "phase": "completed",
        "outcome": "ready",
        "reason_code": None,
    }
    assert execution_wire["updated_at"] == "2026-10-03T00:00:00Z"
    assert execution_wire["future_execution"] == {"opaque": ["retained", None]}
    assert wire["future_live"] is True


def test_runtime_hook_decoder_declares_structured_lifecycle() -> None:
    observation = decode_runtime_hook(
        {
            "message": "Runtime hook QA lifecycle event",
            "runtime_hook_qa_lifecycle": "on_before_tool_call",
            "tool_name": "dupmcp__instance",
            "toolkit_slug": "dupmcp",
            "future_log_field": {"retained": True},
        }
    )
    assert observation is not None
    assert observation.runtime_hook_qa_lifecycle == "on_before_tool_call"
    assert observation.tool_name == "dupmcp__instance"
    assert observation.toolkit_slug == "dupmcp"
    assert observation.model_extra == {"future_log_field": {"retained": True}}


@pytest.mark.parametrize(
    "value",
    [
        [],
        None,
        {},
        {"message": "Unrelated event", "runtime_hook_qa_lifecycle": 1},
        {"message": "Runtime hook QA lifecycle event"},
        {
            "message": "Runtime hook QA lifecycle event: on_before_tool_call",
            "runtime_hook_qa_lifecycle": "on_before_tool_call",
        },
    ],
)
def test_runtime_hook_decoder_rejects_unrelated_or_incomplete_evidence(
    value: object,
) -> None:
    assert decode_runtime_hook(value) is None


@pytest.mark.parametrize("invalid", [1, True, [], {}])
def test_runtime_hook_decoder_rejects_invalid_lifecycle_type(invalid: object) -> None:
    with pytest.raises(ValidationError):
        decode_runtime_hook(
            {
                "message": "Runtime hook QA lifecycle event",
                "runtime_hook_qa_lifecycle": invalid,
            }
        )


def test_runtime_hook_observation_requires_nullable_lifecycle() -> None:
    with pytest.raises(ValidationError):
        RuntimeHookObservation.model_validate(
            {"message": "Runtime hook QA lifecycle event"}
        )
    explicit_null = decode_runtime_hook(
        {
            "message": "Runtime hook QA lifecycle event",
            "runtime_hook_qa_lifecycle": None,
        }
    )
    assert explicit_null is not None
    assert explicit_null.runtime_hook_qa_lifecycle is None
