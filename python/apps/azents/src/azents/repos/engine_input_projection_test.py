"""Database-only input projection ordering and payload regression tests."""

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, assert_never

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind, ExchangeFileStatus, ModelFileStatus
from azents.engine.events.types import (
    AssistantMessagePayload,
    AttachmentOutputPart,
    ClientToolResultPayload,
    Event,
    EventPayload,
    FileOutputPart,
    NativeArtifact,
    OutputContentPart,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolSemanticContent,
    build_native_compat_key,
)
from azents.repos.engine_input_projection import EngineInputProjectionRepository


@dataclass
class _ProjectionState:
    """Track the single caller-repository session and ordered payload changes."""

    session: AsyncSession
    events: list[Event]
    operations: list[str]

    def assert_session(self, session: AsyncSession) -> None:
        """Require the projection primitive to retain its caller's session."""
        assert session is self.session


class _ExchangeRepository:
    """Return configured Exchange statuses while checking deduplication."""

    def __init__(
        self, state: _ProjectionState, *, status: ExchangeFileStatus | None
    ) -> None:
        self.state = state
        self.status = status

    async def list_statuses_by_object_key(
        self, session: AsyncSession, *, object_keys: Sequence[str]
    ) -> dict[str, ExchangeFileStatus]:
        """Read attachment status once in transcript order."""
        self.state.assert_session(session)
        assert object_keys == ["test/object"]
        self.state.operations.append("exchange_status")
        return {} if self.status is None else {"test/object": self.status}


class _ModelFileRepository:
    """Return configured ModelFile status after Exchange payload updates."""

    def __init__(
        self, state: _ProjectionState, *, status: ModelFileStatus | None
    ) -> None:
        self.state = state
        self.status = status

    async def list_statuses_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        model_file_ids: Sequence[str],
    ) -> dict[str, ModelFileStatus]:
        """Check status lookup is Session scoped and file IDs are deduplicated."""
        self.state.assert_session(session)
        assert session_id == "session-1"
        assert model_file_ids == ["m" * 32]
        self.state.operations.append("model_status")
        return {} if self.status is None else {"m" * 32: self.status}


class _TranscriptRepository:
    """Persist projection payloads without opening an independent transaction."""

    def __init__(self, state: _ProjectionState) -> None:
        self.state = state

    async def update_payload(
        self, session: AsyncSession, event_id: str, payload: EventPayload
    ) -> Event:
        """Return the immutable updated Event used by the next projection."""
        self.state.assert_session(session)
        self.state.operations.append("update_payload")
        for index, event in enumerate(self.state.events):
            if event.id == event_id:
                updated = event.model_copy(update={"payload": payload})
                self.state.events[index] = updated
                return updated
        raise AssertionError("event not found")


def _native_artifact() -> NativeArtifact:
    """Provide provider metadata that availability projection preserves."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="test",
            native_format="responses",
            provider="test",
            model="test",
            schema_version="1",
        ),
        adapter="test",
        native_format="responses",
        provider="test",
        model="test",
        schema_version="1",
        item={"type": "tool"},
    )


def _event(
    source: Literal["assistant", "client_tool", "provider_tool"],
) -> Event:
    """Create supported output with duplicate attachment and ModelFile refs."""
    attachment = AttachmentOutputPart(
        uri="exchange://test/object",
        name="result.txt",
        media_type="text/plain",
        size=10,
    )
    file = FileOutputPart(
        model_file_id="m" * 32,
        media_type="image/png",
        name="result.png",
        size=20,
        kind="image",
    )
    parts: list[OutputContentPart] = [attachment, file, attachment, file]
    payload: EventPayload
    match source:
        case "assistant":
            kind = EventKind.ASSISTANT_MESSAGE
            payload = AssistantMessagePayload(
                content=parts,
                native_artifact=_native_artifact(),
            )
        case "client_tool":
            kind = EventKind.CLIENT_TOOL_RESULT
            payload = ClientToolResultPayload(
                call_id="call-1",
                name="read",
                wire_dialect="json_function",
                status="completed",
                output=parts,
            )
        case "provider_tool":
            kind = EventKind.PROVIDER_TOOL_CALL
            payload = ProviderToolCallPayload(
                call_id="call-1",
                name="image_generation",
                status="completed",
                semantic=ProviderToolSemanticContent(
                    input="generate",
                    output=parts,
                    references=[],
                ),
                native_artifact=_native_artifact(),
            )
        case _:
            assert_never(source)
    return Event(
        id="1" * 32,
        session_id="session-1",
        kind=kind,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _parts(payload: EventPayload) -> list[OutputContentPart]:
    """Read supported output parts without changing the payload union."""
    if isinstance(payload, AssistantMessagePayload):
        assert isinstance(payload.content, list)
        return payload.content
    if isinstance(payload, ClientToolResultPayload):
        assert isinstance(payload.output, list)
        return payload.output
    assert isinstance(payload, ProviderToolCallPayload)
    assert isinstance(payload.semantic.output, list)
    return payload.semantic.output


@pytest.mark.parametrize("source", ["assistant", "client_tool", "provider_tool"])
@pytest.mark.parametrize(
    "attachment_status,availability",
    [(None, "unavailable"), (ExchangeFileStatus.EXPIRED, "expired")],
)
@pytest.mark.parametrize("file_status", [None, ModelFileStatus.DELETED])
async def test_input_projection_preserves_all_supported_output_shapes(
    source: Literal["assistant", "client_tool", "provider_tool"],
    attachment_status: ExchangeFileStatus | None,
    availability: Literal["unavailable", "expired"],
    file_status: ModelFileStatus | None,
) -> None:
    """Keep output order and provider metadata through both durable projections."""
    original = _event(source)
    async with AsyncSession() as session:
        state = _ProjectionState(session=session, events=[original], operations=[])
        repository = EngineInputProjectionRepository(
            exchange_file_repository=_ExchangeRepository(
                state, status=attachment_status
            ),
            model_file_repository=_ModelFileRepository(state, status=file_status),
            transcript_repository=_TranscriptRepository(state),
        )

        projected = await repository.apply_in_session(
            session, session_id="session-1", transcript=[original]
        )

    assert state.operations == [
        "exchange_status",
        "update_payload",
        "model_status",
        "update_payload",
    ]
    assert projected == state.events
    assert original.payload != projected[0].payload
    parts = _parts(projected[0].payload)
    assert len(parts) == 4
    for index in (0, 2):
        part = parts[index]
        assert isinstance(part, AttachmentOutputPart)
        assert part.availability == availability
        assert part.uri == "exchange://test/object"
    for index in (1, 3):
        part = parts[index]
        assert isinstance(part, OutputTextPart)
        assert "result.png" in part.text
        expected = (
            "model file metadata is unavailable"
            if file_status is None
            else "model file status is deleted"
        )
        assert expected in part.text
    payload = projected[0].payload
    if isinstance(payload, ProviderToolCallPayload):
        assert payload.semantic.input == "generate"
        assert payload.semantic.references == []
        assert payload.native_artifact == _native_artifact()
    if isinstance(payload, AssistantMessagePayload):
        assert payload.native_artifact == _native_artifact()


async def test_input_projection_does_not_rewrite_available_parts() -> None:
    """Available parts retain the original Event and require no payload mutation."""
    original = _event("provider_tool")
    async with AsyncSession() as session:
        state = _ProjectionState(session=session, events=[original], operations=[])
        repository = EngineInputProjectionRepository(
            exchange_file_repository=_ExchangeRepository(
                state, status=ExchangeFileStatus.AVAILABLE
            ),
            model_file_repository=_ModelFileRepository(
                state, status=ModelFileStatus.AVAILABLE
            ),
            transcript_repository=_TranscriptRepository(state),
        )

        projected = await repository.apply_in_session(
            session, session_id="session-1", transcript=[original]
        )

    assert projected == [original]
    assert projected[0] is original
    assert state.operations == ["exchange_status", "model_status"]
