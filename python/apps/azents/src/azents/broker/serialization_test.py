"""Broker event serialization tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.enums import AgentRunPhase, EventKind
from azents.engine.events.builders import make_system_error_event
from azents.engine.events.engine_events import (
    CompactionComplete,
    CompactionStarted,
    ContentDelta,
    FunctionCallDelta,
    ProviderToolActivityChanged,
    ReasoningDelta,
    RunComplete,
    RunPhaseChanged,
    RunStarted,
    RunStopped,
    RuntimeErrorEvent,
    SubagentTreeChanged,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    Attachment,
    AttachmentOutputPart,
    Event,
    NativeArtifact,
    SystemErrorPayload,
)

from .serialization import deserialize_event, serialize_event


class TestSerializeEngineEvent:
    """Engine/control event serialization."""

    def test_content_delta(self) -> None:
        """Serialize ContentDelta with top-level type discriminator."""
        result = serialize_event(ContentDelta(delta="hello", content_index=0))
        assert result == {
            "type": "content_delta",
            "delta": "hello",
            "content_index": 0,
        }

    def test_reasoning_delta(self) -> None:
        """Serialize ReasoningDelta with its live item identity."""
        result = serialize_event(
            ReasoningDelta(
                delta="thinking...",
                item_id="rs_1",
                output_index=2,
                summary_index=1,
            )
        )
        assert result == {
            "type": "reasoning_delta",
            "delta": "thinking...",
            "item_id": "rs_1",
            "output_index": 2,
            "summary_index": 1,
        }

    def test_function_call_delta(self) -> None:
        """Serialize FunctionCallDelta."""
        result = serialize_event(
            FunctionCallDelta(index=0, id="tc-1", name="search", arguments_delta='{"q"')
        )
        assert result == {
            "type": "function_call_delta",
            "index": 0,
            "id": "tc-1",
            "name": "search",
            "arguments_delta": '{"q"',
        }

    def test_provider_tool_activity(self) -> None:
        """Serialize provider-neutral hosted-tool activity telemetry."""
        event = ProviderToolActivityChanged(
            call_id="search-1",
            name="web_search",
            status="running",
            arguments=None,
        )

        serialized = serialize_event(event)

        assert serialized == {
            "type": "provider_tool_activity_changed",
            "call_id": "search-1",
            "name": "web_search",
            "status": "running",
            "arguments": None,
        }
        assert deserialize_event(serialized) == event

    def test_run_started(self) -> None:
        """Serialize RunStarted phase."""
        result = serialize_event(
            RunStarted(run_id="r1", phase=AgentRunPhase.WAITING_FOR_MODEL)
        )
        assert result == {
            "type": "run_started",
            "run_id": "r1",
            "phase": "waiting_for_model",
        }

    def test_run_phase_changed(self) -> None:
        """Serialize RunPhaseChanged."""
        result = serialize_event(
            RunPhaseChanged(
                run_id="r1",
                phase=AgentRunPhase.STREAMING_MODEL,
                model_call_started_at=datetime.datetime(
                    2026, 7, 14, tzinfo=datetime.UTC
                ),
            )
        )
        assert result == {
            "type": "run_phase_changed",
            "run_id": "r1",
            "phase": "streaming_model",
            "model_call_started_at": "2026-07-14T00:00:00Z",
        }

    def test_run_complete(self) -> None:
        """Serialize RunComplete."""
        assert serialize_event(RunComplete(run_id="run-001")) == {
            "type": "run_complete",
            "run_id": "run-001",
        }

    def test_run_stopped(self) -> None:
        """Serialize RunStopped."""
        assert serialize_event(RunStopped(run_id="run-001")) == {
            "type": "run_stopped",
            "run_id": "run-001",
        }

    def test_runtime_error(self) -> None:
        """Serialize RuntimeErrorEvent."""
        assert serialize_event(RuntimeErrorEvent(message="boom")) == {
            "type": "runtime_error",
            "message": "boom",
        }

    def test_compaction_started(self) -> None:
        """Serialize CompactionStarted."""
        assert serialize_event(CompactionStarted()) == {
            "type": "compaction_started",
            "continuing": False,
        }

    def test_compaction_complete(self) -> None:
        """Serialize CompactionComplete."""
        assert serialize_event(CompactionComplete(continuing=True)) == {
            "type": "compaction_complete",
            "continuing": True,
        }

    def test_subagent_tree_changed(self) -> None:
        """Serialize SubagentTreeChanged."""
        assert serialize_event(
            SubagentTreeChanged(
                root_session_agent_id="root-agent",
                changed_session_agent_id="child-agent",
            )
        ) == {
            "type": "subagent_tree_changed",
            "root_session_agent_id": "root-agent",
            "changed_session_agent_id": "child-agent",
        }


class TestSerializeEvent:
    """Event serialization."""

    def test_system_error(self) -> None:
        """Event keeps the kind/payload wire shape."""
        event = make_system_error_event(session_id="session-1", content="boom")
        result = serialize_event(event)
        assert result["id"] == event.id
        assert result["session_id"] == "session-1"
        assert result["kind"] == "system_error"
        assert result["payload"] == {
            "content": "boom",
            "severity": "error",
            "recoverable": True,
            "reset_suggested": None,
        }

    def test_attachment_uses_chat_transport_shape(self) -> None:
        """WS event attachments use the same transport shape as REST history."""
        created_at = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
        event = Event(
            id="event000000000000000000000000001",
            session_id="session-1",
            kind=EventKind.ASSISTANT_MESSAGE,
            payload=AssistantMessagePayload(
                content=[
                    AttachmentOutputPart(
                        attachment_id="att-output",
                        uri="exchange://output.png",
                        name="output.png",
                        media_type="image/png",
                        size=2,
                        preview_summary="output summary",
                    )
                ],
                attachments=[
                    Attachment(
                        attachment_id="att-1",
                        uri="exchange://image.png",
                        name="image.png",
                        media_type="image/png",
                        size=1,
                        created_at=created_at,
                        source="user_upload",
                        preview_summary="summary",
                    )
                ],
                native_artifact=NativeArtifact(
                    compat_key="test:json:test:model:v1",
                    adapter="test",
                    native_format="json",
                    provider="test",
                    model="model",
                    schema_version="v1",
                    item={},
                ),
            ),
            created_at=created_at,
        )

        result = serialize_event(event)

        assert result["payload"] == {
            "content": [
                {
                    "type": "attachment",
                    "attachment_id": "att-output",
                    "uri": "exchange://output.png",
                    "name": "output.png",
                    "media_type": "image/png",
                    "size": 2,
                    "text_preview": "output summary",
                    "preview_thumbnail_uri": None,
                    "availability": "available",
                    "preview_title": None,
                    "preview_thumbnail_media_type": None,
                    "preview_thumbnail_width": None,
                    "preview_thumbnail_height": None,
                    "preview_generated_at": None,
                }
            ],
            "attachments": [
                {
                    "attachment_id": "att-1",
                    "uri": "exchange://image.png",
                    "name": "image.png",
                    "media_type": "image/png",
                    "size": 1,
                    "text_preview": "summary",
                    "preview_thumbnail_uri": None,
                    "availability": "available",
                    "preview_title": None,
                    "preview_thumbnail_media_type": None,
                    "preview_thumbnail_width": None,
                    "preview_thumbnail_height": None,
                    "preview_generated_at": None,
                }
            ],
            "native_artifact": {
                "compat_key": "test:json:test:model:v1",
                "adapter": "test",
                "native_format": "json",
                "provider": "test",
                "model": "model",
                "schema_version": "v1",
                "item": {},
            },
        }


class TestDeserializeEvent:
    """Broker wire deserialize."""

    def test_engine_event(self) -> None:
        """Restore flat engine event."""
        event = deserialize_event(
            {"type": "content_delta", "delta": "x", "content_index": 0}
        )
        assert isinstance(event, ContentDelta)
        assert event.delta == "x"

    def test_event(self) -> None:
        """Restore Event."""
        source = make_system_error_event(session_id="session-1", content="boom")
        event = deserialize_event(serialize_event(source))
        assert isinstance(event, Event)
        assert event.kind == EventKind.SYSTEM_ERROR
        assert isinstance(event.payload, SystemErrorPayload)
        assert event.payload.content == "boom"

    def test_legacy_envelope_is_rejected(self) -> None:
        """Reject legacy Event envelope on broker wire."""
        with pytest.raises(ValueError, match="Legacy event envelope"):
            deserialize_event({"id": "legacy-1", "item": {"type": "text_item"}})

    def test_unknown_engine_event_raises_validation_error(self) -> None:
        """Unknown flat event type is a validation error."""
        with pytest.raises(ValidationError):
            deserialize_event({"type": "totally_unknown_type"})
