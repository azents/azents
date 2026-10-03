"""Conversational client-tool projection tests."""

import json
from types import MappingProxyType
from typing import Literal

import pytest

from azents.engine.events.conversational_tool_projection import (
    CONVERSATIONAL_TOOL_PROJECTIONS,
    project_conversational_tool_call,
)
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    NativeArtifact,
    build_native_compat_key,
)


def _native_artifact() -> NativeArtifact:
    compat_key = build_native_compat_key(
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-test",
        schema_version="1",
    )
    return NativeArtifact(
        compat_key=compat_key,
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-test",
        schema_version="1",
        item={"type": "function_call"},
    )


def _call(arguments: object) -> ClientToolCallPayload:
    return ClientToolCallPayload(
        call_id="call-1",
        name="channel_action",
        arguments=json.dumps(arguments),
        wire_dialect="json_function",
        toolkit_source=None,
        native_artifact=_native_artifact(),
    )


def _result(
    status: str,
    *,
    result_status: Literal[
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ] = "completed",
) -> ClientToolResultPayload:
    return ClientToolResultPayload(
        call_id="call-1",
        name="channel_action",
        wire_dialect="json_function",
        status=result_status,
        output=json.dumps(
            {"outcomes": [{"operation": "reply", "part": 0, "status": status}]}
        ),
    )


def test_conversational_tool_registry_is_runtime_immutable() -> None:
    """Durable-name interpretation cannot change after module composition."""
    assert isinstance(CONVERSATIONAL_TOOL_PROJECTIONS, MappingProxyType)


def test_channel_action_projects_delivered_message_and_work_state() -> None:
    """Participant-visible tool input becomes attributed Agent conversation."""
    projection = project_conversational_tool_call(
        _call(
            {
                "mode": "continue",
                "binding": "binding-1",
                "message": "I checked the venue.",
                "title": "Checking availability…",
                "todo_update": [
                    {
                        "id": "check",
                        "title": "Check venue",
                        "status": "completed",
                        "output": {"token": "secret-value"},
                    }
                ],
            }
        ),
        _result("delivered"),
    )

    assert projection is not None
    assert projection.text == "I checked the venue."
    assert projection.delivery_status == "delivered"
    rendered = projection.render()
    assert "tool=channel_action" in rendered
    assert "delivery=delivered" in rendered
    assert "title: Checking availability…" in rendered
    assert "todo_update:" in rendered
    assert "secret-value" not in rendered
    assert "[REDACTED]" in rendered


def test_channel_action_ignore_produces_no_conversation() -> None:
    """Silent completion does not invent an Agent utterance."""
    assert (
        project_conversational_tool_call(
            _call({"mode": "ignore", "binding": "binding-1"}),
            _result("delivered"),
        )
        is None
    )


def test_channel_action_failed_reply_preserves_delivery_uncertainty() -> None:
    """A rejected provider effect is not rendered as delivered conversation."""
    projection = project_conversational_tool_call(
        _call(
            {
                "mode": "finish",
                "binding": "binding-1",
                "message": "Final answer",
            }
        ),
        _result("failed"),
    )

    assert projection is not None
    assert projection.delivery_status == "failed"


def test_channel_action_failed_tool_result_is_failed_delivery() -> None:
    """A failed durable client-tool result is known failed delivery."""
    projection = project_conversational_tool_call(
        _call(
            {
                "mode": "finish",
                "binding": "binding-1",
                "message": "Final answer",
            }
        ),
        _result("unknown", result_status="failed"),
    )

    assert projection is not None
    assert projection.delivery_status == "failed"


def test_channel_action_redacts_embedded_url_query_values() -> None:
    """Participant text retains retrieval clues without access-bearing queries."""
    projection = project_conversational_tool_call(
        _call(
            {
                "mode": "finish",
                "binding": "binding-1",
                "message": (
                    "Open https://example.test/path?token=abc&safe=value, then reply."
                ),
            }
        ),
        _result("delivered"),
    )

    assert projection is not None
    assert projection.text is not None
    assert "token=abc" not in projection.text
    assert "safe=value" not in projection.text
    assert (
        "https://example.test/path?token=[REDACTED]&safe=[REDACTED]," in projection.text
    )


def test_channel_action_redacts_bearer_assignment_in_visible_text() -> None:
    """Conversational projection is safe when reused outside extraction."""
    projection = project_conversational_tool_call(
        _call(
            {
                "mode": "finish",
                "binding": "binding-1",
                "message": "Authorization: Bearer top-secret\nContinue safely.",
            }
        ),
        _result("delivered"),
    )

    assert projection is not None
    assert projection.text is not None
    assert "top-secret" not in projection.text
    assert "Authorization: [REDACTED]" in projection.text
    assert "Continue safely." in projection.text


def test_malformed_registered_arguments_fall_back_to_generic_tool_projection() -> None:
    """Malformed legacy input is not interpreted as participant conversation."""
    call = _call({"mode": "finish", "binding": "binding-1", "message": "answer"})
    malformed = call.model_copy(update={"arguments": "{"})

    assert project_conversational_tool_call(malformed, _result("delivered")) is None


@pytest.mark.parametrize(
    ("arguments", "text", "context"),
    [
        ({"message": " legacy answer ", "future": True}, "legacy answer", ()),
        ({"mode": 7, "message": "answer"}, "answer", ()),
        ({"message": 7, "title": " Work "}, None, (("title", "Work"),)),
        ({"message": None, "title": 0}, None, (("title", "0"),)),
        ({"title": False}, None, (("title", "false"),)),
        ({"title": "", "todo_update": []}, None, ()),
        ({"title": {}, "todo_update": None}, None, ()),
        (
            {"ignored": True, "text": "not a wire field", "message": "answer"},
            "answer",
            (),
        ),
    ],
)
def test_historical_projection_retains_existing_optional_field_tolerance(
    arguments: dict[str, object],
    text: str | None,
    context: tuple[tuple[str, str], ...],
) -> None:
    """Decode the historical view without requiring today's executable payload."""
    projection = project_conversational_tool_call(_call(arguments), None)
    if text is None and not context:
        assert projection is None
        return
    assert projection is not None
    assert projection.text == text
    assert projection.context == context
    assert projection.delivery_status == ("unknown" if text is not None else None)


@pytest.mark.parametrize("arguments", [None, [], "text", 7, False])
def test_nonobject_historical_arguments_are_not_conversation(arguments: object) -> None:
    """Only JSON objects admit the registered historical operation view."""
    assert project_conversational_tool_call(_call(arguments), None) is None


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ({}, "unknown"),
        ({"outcomes": None}, "unknown"),
        ({"outcomes": {}}, "unknown"),
        (
            {"outcomes": [None, 7, {"operation": "other", "status": "delivered"}]},
            "unknown",
        ),
        (
            {
                "outcomes": [
                    None,
                    {"operation": "reply", "status": "delivered", "future": 7},
                ]
            },
            "delivered",
        ),
        (
            {"outcomes": [{"operation": "reply", "status": "not_attempted"}]},
            "failed",
        ),
        (
            {
                "outcomes": [
                    {"operation": "reply"},
                    {"operation": "reply", "status": "delivered"},
                ]
            },
            "unknown",
        ),
        ([], "unknown"),
    ],
)
def test_historical_reply_decoder_retains_order_and_delivery_meanings(
    output: object, expected: str
) -> None:
    """The first matching reply outcome remains the delivery authority."""
    result = ClientToolResultPayload(
        call_id="call-1",
        name="channel_action",
        wire_dialect="json_function",
        status="completed",
        output=json.dumps(output),
    )
    projection = project_conversational_tool_call(_call({"message": "answer"}), result)
    assert projection is not None
    assert projection.delivery_status == expected
