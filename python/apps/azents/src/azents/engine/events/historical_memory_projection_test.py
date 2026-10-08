"""Historical Memory source-event projection tests."""

import datetime
import json

from azents.core.enums import EventKind
from azents.engine.events.historical_memory_projection import (
    HistoricalMemoryEvidenceTier,
    project_historical_memory_input,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    EventPayload,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolSemanticContent,
    SystemReminderPayload,
    UserMessagePayload,
    build_native_compat_key,
)

_NOW = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


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
        item={"type": "test"},
    )


def _event(index: int, kind: EventKind, payload: EventPayload) -> Event:
    return Event(
        id=f"{index:032d}",
        session_id="session-1",
        kind=kind,
        payload=payload,
        created_at=_NOW + datetime.timedelta(seconds=index),
    )


def _user(index: int, text: str) -> Event:
    return _event(
        index,
        EventKind.USER_MESSAGE,
        UserMessagePayload(
            sender_user_id=None,
            content=text,
            attachments=[],
            metadata={},
            requested_inference_profile=None,
            applied_inference_profile=None,
        ),
    )


def _assistant(index: int, text: str) -> Event:
    return _event(
        index,
        EventKind.ASSISTANT_MESSAGE,
        AssistantMessagePayload(
            content=text,
            attachments=[],
            native_artifact=_native_artifact(),
        ),
    )


def _tool_call(index: int, *, name: str, arguments: object) -> Event:
    return _event(
        index,
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id=f"call-{index}",
            name=name,
            arguments=json.dumps(arguments),
            wire_dialect="json_function",
            toolkit_source=None,
            native_artifact=_native_artifact(),
        ),
    )


def _provider_tool(index: int) -> Event:
    return _event(
        index,
        EventKind.PROVIDER_TOOL_CALL,
        ProviderToolCallPayload(
            call_id=f"provider-call-{index}",
            name="web_search",
            status="completed",
            semantic=ProviderToolSemanticContent(
                input="query=historical memory authorization",
                output=[OutputTextPart(text="Found token=output-secret")],
                references=[
                    ProviderToolReference(
                        kind="url",
                        uri="https://example.test/source?credential=reference-secret",
                        title="Source title",
                        excerpt="Relevant evidence",
                        metadata={"api_key": "metadata-secret"},
                    )
                ],
            ),
            native_artifact=_native_artifact(),
        ),
    )


def test_projection_prioritizes_human_evidence_then_restores_chronology() -> None:
    """Newer tier selection does not reorder the admitted source evidence."""
    projection = project_historical_memory_input(
        [
            _assistant(1, "old assistant " + "x" * 400),
            _user(2, "human-old"),
            _tool_call(3, name="probe", arguments={"payload": "x" * 400}),
            _user(4, "human-new"),
        ],
        token_limit=31,
    )

    assert projection.selected_event_ids == (
        f"{1:032d}",
        f"{2:032d}",
        f"{4:032d}",
    )
    assert projection.omitted_event_count == 1
    assert projection.text.index("human-old") < projection.text.index("human-new")
    assert projection.text.count("[... source events omitted ...]") == 1
    assert projection.selected_tier_counts == (
        (HistoricalMemoryEvidenceTier.HUMAN, 2),
        (HistoricalMemoryEvidenceTier.ASSISTANT, 1),
    )


def test_registered_conversational_tool_is_one_assistant_evidence_item() -> None:
    """The linked result annotates an utterance without duplicate Tool evidence."""
    call = _tool_call(
        1,
        name="channel_action",
        arguments={
            "mode": "finish",
            "binding": "binding-1",
            "message": "Published answer",
        },
    )
    result = _event(
        2,
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="call-1",
            name="channel_action",
            wire_dialect="json_function",
            status="completed",
            output=json.dumps(
                {"outcomes": [{"operation": "reply", "part": 0, "status": "delivered"}]}
            ),
        ),
    )

    projection = project_historical_memory_input([call, result], token_limit=100)

    assert projection.candidate_event_count == 1
    assert projection.selected_event_ids == (call.id,)
    assert "Published answer" in projection.text
    assert "delivery=delivered" in projection.text


def test_projection_omits_hidden_system_reminders() -> None:
    """System prompt material is not source evidence for Historical Memory."""
    reminder = _event(
        1,
        EventKind.SYSTEM_REMINDER,
        SystemReminderPayload(text="hidden instruction"),
    )

    projection = project_historical_memory_input(
        [reminder, _user(2, "visible request")],
        token_limit=100,
    )

    assert "hidden instruction" not in projection.text
    assert "visible request" in projection.text
    assert projection.candidate_event_count == 1


def test_projection_redacts_sensitive_json_and_url_query_values() -> None:
    """Generic Tool evidence preserves safe structure without access-bearing values."""
    event = _tool_call(
        1,
        name="request",
        arguments={
            "api_key": "secret-value",
            "url": "https://example.test/path?token=abc&safe=value",
        },
    )

    projection = project_historical_memory_input([event], token_limit=100)

    assert "secret-value" not in projection.text
    assert "token=abc" not in projection.text
    assert "safe=value" not in projection.text
    assert "[REDACTED]" in projection.text


def test_provider_tool_projection_preserves_semantic_axes_with_redaction() -> None:
    """Provider evidence keeps query and references without access-bearing values."""
    projection = project_historical_memory_input(
        [_provider_tool(1)],
        token_limit=200,
    )

    assert "Input:" in projection.text
    assert "query=historical memory authorization" in projection.text
    assert "Output:" in projection.text
    assert "References:" in projection.text
    assert "Source title" in projection.text
    assert "Relevant evidence" in projection.text
    assert "output-secret" not in projection.text
    assert "reference-secret" not in projection.text
    assert "metadata-secret" not in projection.text
    assert "[REDACTED]" in projection.text


def test_projection_redacts_url_queries_embedded_in_conversation_text() -> None:
    """Access-bearing query values are removed without dropping surrounding text."""
    projection = project_historical_memory_input(
        [
            _user(
                1,
                "Inspect https://example.test/path?token=abc&safe=value, then report.",
            )
        ],
        token_limit=100,
    )

    assert "token=abc" not in projection.text
    assert "safe=value" not in projection.text
    assert (
        "Inspect https://example.test/path?token=[REDACTED]&safe=[REDACTED], "
        "then report."
    ) in projection.text


def test_projection_redacts_bearer_assignments_in_conversation_text() -> None:
    """Header-shaped access values are removed without dropping later lines."""
    projection = project_historical_memory_input(
        [_user(1, "Authorization: Bearer top-secret\nKeep this request.")],
        token_limit=100,
    )

    assert "top-secret" not in projection.text
    assert "Authorization: [REDACTED]" in projection.text
    assert "Keep this request." in projection.text


def test_projection_redacts_standalone_bearer_values() -> None:
    """Bearer credentials are removed even without an Authorization label."""
    projection = project_historical_memory_input(
        [_user(1, "Use Bearer top-secret for the request.")],
        token_limit=100,
    )

    assert "top-secret" not in projection.text
    assert "Bearer [REDACTED]" in projection.text


def test_projection_redacts_url_user_info() -> None:
    """HTTP user info is access-bearing even when the URL has no query."""
    projection = project_historical_memory_input(
        [_user(1, "Inspect https://user:password@example.test/path.")],
        token_limit=100,
    )

    assert "user:password" not in projection.text
    assert "https://[REDACTED]@example.test/path" in projection.text


def test_projection_redacts_url_user_info_before_ipv6_host() -> None:
    """URL redaction covers credentials attached to bracketed IPv6 hosts."""
    projection = project_historical_memory_input(
        [_user(1, "Inspect https://user:password@[2001:db8::1]/path.")],
        token_limit=100,
    )

    assert "user:password" not in projection.text
    assert "https://[REDACTED]@[2001:db8::1]/path" in projection.text


def test_projection_truncates_newest_lower_tier_after_higher_tier_selection() -> None:
    """A selected higher tier does not prevent bounded newest lower-tier evidence."""
    projection = project_historical_memory_input(
        [
            _assistant(1, "older assistant"),
            _user(2, "priority request"),
            _assistant(3, "newest assistant " + "x" * 400),
        ],
        token_limit=35,
    )

    assert projection.selected_event_ids == (f"{2:032d}", f"{3:032d}")
    assert "priority request" in projection.text
    assert "newest assistant" in projection.text
    assert "... [truncated]" in projection.text


def test_projection_skips_oversized_newest_item_for_smaller_older_item() -> None:
    """A remainder too small for useful truncation can admit smaller older evidence."""
    projection = project_historical_memory_input(
        [
            _assistant(1, "small"),
            _user(2, "priority request " + "y" * 20),
            _assistant(3, "newest assistant " + "x" * 400),
        ],
        token_limit=27,
    )

    assert projection.selected_event_ids == (f"{1:032d}", f"{2:032d}")
    assert "small" in projection.text
    assert "newest assistant" not in projection.text


def test_projection_counts_every_omission_interval_inside_total_budget() -> None:
    """Separated omitted runs cannot push rendered text over the byte limit."""
    token_limit = 32
    projection = project_historical_memory_input(
        [
            _user(1, "priority one"),
            _tool_call(2, name="probe", arguments={"value": "x" * 200}),
            _user(3, "priority two"),
            _tool_call(4, name="probe", arguments={"value": "y" * 200}),
            _user(5, "priority three"),
        ],
        token_limit=token_limit,
    )

    assert projection.text.count("[... source events omitted ...]") == 2
    assert len(projection.text.encode()) <= token_limit * 4
