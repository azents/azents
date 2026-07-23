"""Event filter/compaction tests."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import azents.engine.events.filters as filters
from azents.core.enums import (
    EventKind,
    ExchangeFileStatus,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ModelFileStatus,
)
from azents.engine.events.filters import (
    EventAttachmentAvailabilityFilter,
    EventAutoCompactionFilter,
    EventCompactor,
    EventFilePartPlaceholderFilter,
    EventPreLowerFilterPipeline,
    NativeRequestSizeGuard,
    NoopPreLowerFilter,
    PostLowerFilterPipeline,
)
from azents.engine.events.protocols import NativeModelRequest
from azents.engine.events.types import (
    AssistantMessagePayload,
    Attachment,
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionMarkerPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    ExternalChannelMessagePayload,
    FileOutputPart,
    InputTextPart,
    NativeArtifact,
    OutputTextPart,
    RunMarkerPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.run.errors import CompactionFailedError, CompactionPlanStaleError
from azents.repos.agent_execution.data import EventCreate


class _Session(AsyncSession):
    """AsyncSession tracking explicit compaction transaction boundaries."""

    def __init__(self) -> None:
        super().__init__()
        self.commit_count = 0
        self.expire_all_count = 0

    async def commit(self) -> None:
        """Record a transaction boundary without requiring a database bind."""
        self.commit_count += 1

    def expire_all(self) -> None:
        """Record caller identity-map invalidation."""
        self.expire_all_count += 1


class _SessionManager:
    """Create short test sessions and commit them on clean scope exit."""

    def __init__(self) -> None:
        self.sessions: list[_Session] = []
        self.active_scopes = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[_Session]:
        """Yield one tracked session scope."""
        session = _Session()
        self.sessions.append(session)
        self.active_scopes += 1
        try:
            yield session
        except BaseException:
            raise
        else:
            await session.commit()
        finally:
            self.active_scopes -= 1


class _TranscriptRepo:
    """Transcript repository for tests."""

    def __init__(self, events: list[Event]) -> None:
        self.events = events

    async def update_model_orders(
        self,
        session: AsyncSession,
        session_id: str,
        order_by_event_id: dict[str, int],
    ) -> None:
        """Apply model order update in memory."""
        del session, session_id
        by_id = {event.id: event for event in self.events}
        for event_id, model_order in order_by_event_id.items():
            event = by_id[event_id]
            self.events[self.events.index(event)] = event.model_copy(
                update={"model_order": model_order}
            )

    async def update_payload(
        self,
        session: AsyncSession,
        event_id: str,
        payload: EventPayload,
    ) -> Event:
        """Apply payload update in memory."""
        del session
        for index, event in enumerate(self.events):
            if event.id != event_id:
                continue
            updated = event.model_copy(update={"payload": payload})
            self.events[index] = updated
            return updated
        raise AssertionError("event not found")

    async def append(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Materialize append request as in-memory event."""
        del session
        payload = _payload_from_create(create)
        event = Event(
            id=f"{len(self.events) + 1:032d}",
            session_id=create.session_id,
            kind=create.kind,
            payload=payload,
            model_order=create.model_order or (len(self.events) + 1) * 1000,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.events.append(event)
        return event


class _SessionRepo:
    """Session repository for tests."""

    def __init__(self) -> None:
        self.head_event_id: str | None = None
        self.model_input_head_event_id: str | None = None
        self.model_input_head_model_order: int | None = None

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> "_SessionRepo":
        """Return current test Session state."""
        del session, agent_session_id
        return self

    async def lock_model_input_head_if_current(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        expected_event_id: str | None,
    ) -> bool:
        """Verify the planned head in the test repository."""
        del session, session_id
        return self.model_input_head_event_id == expected_event_id

    async def move_model_input_head(
        self,
        session: AsyncSession,
        session_id: str,
        event_id: str,
    ) -> object:
        """Record head movement."""
        del session, session_id
        self.head_event_id = event_id
        self.model_input_head_event_id = event_id
        return object()


def _compactor(
    *,
    transcript_repo: _TranscriptRepo,
    session_repo: _SessionRepo,
    session_manager: _SessionManager | None = None,
) -> EventCompactor:
    """Create an EventCompactor with tracked short session scopes."""
    return EventCompactor(
        session_manager=session_manager or _SessionManager(),
        transcript_repo=transcript_repo,
        session_repo=session_repo,
    )


def _native_artifact() -> NativeArtifact:
    """Create native artifact for tests."""
    return _native_artifact_with_item({"type": "message"})


def _native_artifact_with_item(item: dict[str, object]) -> NativeArtifact:
    """Create native artifact for tests containing specified item."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item=item,
    )


def _usage(prompt_tokens: int) -> TokenUsagePayload:
    """Create token usage for tests."""
    return TokenUsagePayload(
        prompt_tokens=prompt_tokens,
        completion_tokens=5,
        total_tokens=prompt_tokens + 5,
        raw={
            "input_tokens": prompt_tokens,
            "output_tokens": 5,
            "total_tokens": prompt_tokens + 5,
        },
    )


def _attachment(uri: str) -> Attachment:
    """Create event attachment for tests."""
    return Attachment(
        attachment_id="attachment-1",
        uri=uri,
        name="report.txt",
        media_type="text/plain",
        size=10,
        created_at=datetime.datetime.now(datetime.UTC),
    )


class _ModelFileStatusRepo:
    """ModelFile status repository for tests."""

    def __init__(self, statuses: dict[str, ModelFileStatus]) -> None:
        self.statuses = statuses
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def list_statuses_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        model_file_ids: Sequence[str],
    ) -> dict[str, ModelFileStatus]:
        """Record ModelFile status lookup call."""
        del session
        self.calls.append((session_id, tuple(model_file_ids)))
        return {
            model_file_id: status
            for model_file_id, status in self.statuses.items()
            if model_file_id in model_file_ids
        }


class _ExchangeFileStatusRepo:
    """ExchangeFile status repository for tests."""

    def __init__(self, statuses: dict[str, ExchangeFileStatus]) -> None:
        self.statuses = statuses
        self.calls: list[tuple[str, ...]] = []

    async def list_statuses_by_object_key(
        self,
        session: AsyncSession,
        *,
        object_keys: Sequence[str],
    ) -> dict[str, ExchangeFileStatus]:
        """Record Exchange object key status lookup call."""
        del session
        self.calls.append(tuple(object_keys))
        return {
            object_key: status
            for object_key, status in self.statuses.items()
            if object_key in object_keys
        }


async def test_attachment_availability_filter_marks_expired_attachment() -> None:
    """Expired Exchange attachment status also expires durable payload."""
    attachment = _attachment("exchange://exchange/workspace/files/random/original")
    event = _event(
        "1",
        EventKind.USER_MESSAGE,
        UserMessagePayload(content="see file", attachments=[attachment]),
    )
    transcript = [event]
    transcript_repo = _TranscriptRepo(transcript)
    status_repo = _ExchangeFileStatusRepo(
        {"exchange/workspace/files/random/original": ExchangeFileStatus.EXPIRED}
    )

    result = await EventAttachmentAvailabilityFilter(
        exchange_file_repository=status_repo,
        transcript_repo=transcript_repo,
    ).apply(_Session(), transcript)

    assert status_repo.calls == [("exchange/workspace/files/random/original",)]
    payload = result[0].payload
    assert isinstance(payload, UserMessagePayload)
    assert payload.attachments[0].availability == "expired"


async def test_attachment_availability_filter_marks_missing_exchange_unavailable() -> (
    None
):
    """Mark attachment unavailable when Exchange metadata is absent."""
    attachment = _attachment("exchange://exchange/workspace/files/missing/original")
    event = _event(
        "1",
        EventKind.USER_MESSAGE,
        UserMessagePayload(content="see file", attachments=[attachment]),
    )
    transcript = [event]
    transcript_repo = _TranscriptRepo(transcript)
    status_repo = _ExchangeFileStatusRepo({})

    result = await EventAttachmentAvailabilityFilter(
        exchange_file_repository=status_repo,
        transcript_repo=transcript_repo,
    ).apply(_Session(), transcript)

    payload = result[0].payload
    assert isinstance(payload, UserMessagePayload)
    assert payload.attachments[0].availability == "unavailable"


async def test_attachment_availability_filter_ignores_non_exchange_uri() -> None:
    """Leave non-Exchange URI unchanged without status lookup."""
    attachment = _attachment("artifact://artifact-1")
    event = _event(
        "1",
        EventKind.USER_MESSAGE,
        UserMessagePayload(content="see file", attachments=[attachment]),
    )
    transcript = [event]
    transcript_repo = _TranscriptRepo(transcript)
    status_repo = _ExchangeFileStatusRepo({})

    result = await EventAttachmentAvailabilityFilter(
        exchange_file_repository=status_repo,
        transcript_repo=transcript_repo,
    ).apply(_Session(), transcript)

    assert status_repo.calls == []
    assert result == transcript


async def test_attachment_availability_filter_updates_tool_output_part() -> None:
    """Also update availability of AttachmentOutputPart in tool output."""
    event = _event(
        "1",
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="call-1",
            name="present_file",
            status="completed",
            output=[
                AttachmentOutputPart(
                    uri="exchange://exchange/workspace/files/result/original",
                    name="result.txt",
                    media_type="text/plain",
                    size=42,
                )
            ],
            wire_dialect="json_function",
        ),
    )
    transcript = [event]
    transcript_repo = _TranscriptRepo(transcript)
    status_repo = _ExchangeFileStatusRepo(
        {"exchange/workspace/files/result/original": ExchangeFileStatus.EXPIRED}
    )

    result = await EventAttachmentAvailabilityFilter(
        exchange_file_repository=status_repo,
        transcript_repo=transcript_repo,
    ).apply(_Session(), transcript)

    payload = result[0].payload
    assert isinstance(payload, ClientToolResultPayload)
    assert isinstance(payload.output, list)
    part = payload.output[0]
    assert isinstance(part, AttachmentOutputPart)
    assert part.availability == "expired"


async def test_filepart_placeholder_filter_rewrites_deleted_user_filepart() -> None:
    """Deleted FilePart becomes text placeholder in user message payload."""
    file_part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="image/jpeg",
        name="chart.jpg",
        size=123,
        kind="image",
    )
    event = _event(
        "1",
        EventKind.USER_MESSAGE,
        UserMessagePayload(content=[file_part]),
    )
    transcript = [event]
    transcript_repo = _TranscriptRepo(transcript)
    status_repo = _ModelFileStatusRepo({"m" * 32: ModelFileStatus.DELETED})

    result = await EventFilePartPlaceholderFilter(
        session_id="session-1",
        model_file_repository=status_repo,
        transcript_repo=transcript_repo,
    ).apply(_Session(), transcript)

    assert status_repo.calls == [("session-1", ("m" * 32,))]
    payload = result[0].payload
    assert isinstance(payload, UserMessagePayload)
    assert isinstance(payload.content, list)
    placeholder = payload.content[0]
    assert isinstance(placeholder, InputTextPart)
    assert "chart.jpg" in placeholder.text
    assert "model file status is deleted" in placeholder.text


async def test_filepart_placeholder_filter_rewrites_missing_tool_filepart() -> None:
    """Missing FilePart becomes text placeholder in tool result payload."""
    file_part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="application/pdf",
        name="report.pdf",
        size=456,
        kind="document",
    )
    event = _event(
        "1",
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="call-1",
            name="read_image",
            status="completed",
            output=[file_part],
            wire_dialect="json_function",
        ),
    )
    transcript = [event]
    transcript_repo = _TranscriptRepo(transcript)
    status_repo = _ModelFileStatusRepo({})

    result = await EventFilePartPlaceholderFilter(
        session_id="session-1",
        model_file_repository=status_repo,
        transcript_repo=transcript_repo,
    ).apply(_Session(), transcript)

    payload = result[0].payload
    assert isinstance(payload, ClientToolResultPayload)
    assert isinstance(payload.output, list)
    placeholder = payload.output[0]
    assert isinstance(placeholder, OutputTextPart)
    assert "report.pdf" in placeholder.text
    assert "model file metadata is unavailable" in placeholder.text


async def test_filepart_placeholder_filter_rewrites_missing_assistant_filepart() -> (
    None
):
    """Missing FilePart becomes text placeholder in assistant message payload."""
    file_part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="image/jpeg",
        name="output.jpg",
        size=789,
        kind="image",
    )
    event = _event(
        "1",
        EventKind.ASSISTANT_MESSAGE,
        AssistantMessagePayload(
            content=[file_part],
            native_artifact=_native_artifact(),
        ),
    )
    transcript = [event]
    transcript_repo = _TranscriptRepo(transcript)
    status_repo = _ModelFileStatusRepo({})

    result = await EventFilePartPlaceholderFilter(
        session_id="session-1",
        model_file_repository=status_repo,
        transcript_repo=transcript_repo,
    ).apply(_Session(), transcript)

    payload = result[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert isinstance(payload.content, list)
    placeholder = payload.content[0]
    assert isinstance(placeholder, OutputTextPart)
    assert "output.jpg" in placeholder.text
    assert "model file metadata is unavailable" in placeholder.text


async def test_filepart_placeholder_filter_keeps_available_filepart() -> None:
    """Available FilePart does not change transcript payload."""
    file_part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="image/jpeg",
        name="chart.jpg",
        size=123,
        kind="image",
    )
    event = _event(
        "1",
        EventKind.USER_MESSAGE,
        UserMessagePayload(content=[file_part]),
    )
    transcript = [event]
    transcript_repo = _TranscriptRepo(transcript)
    status_repo = _ModelFileStatusRepo({"m" * 32: ModelFileStatus.AVAILABLE})

    result = await EventFilePartPlaceholderFilter(
        session_id="session-1",
        model_file_repository=status_repo,
        transcript_repo=transcript_repo,
    ).apply(_Session(), transcript)

    assert result == transcript
    assert transcript_repo.events == transcript


async def test_compactor_appends_marker_summary_and_moves_head() -> None:
    """Compaction atomically appends marker and summary before moving the head."""
    events = [
        _event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old")),
        _event("2", EventKind.USER_MESSAGE, UserMessagePayload(content="recent")),
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return summary result."""
        del summary_budget
        assert [event.id for event in old_events] == [events[0].id, events[1].id]
        return f"summary:{old_events[-1].id}"

    summary = await _compactor(
        transcript_repo=transcript_repo,
        session_repo=session_repo,
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
        reason="manual_command",
    )

    assert summary is not None
    assert session_repo.head_event_id == summary.id
    assert len(transcript_repo.events) == 4
    assert [event.model_order for event in transcript_repo.events] == [
        1000,
        2000,
        2001,
        2002,
    ]
    marker = transcript_repo.events[-2]
    assert marker.kind == EventKind.COMPACTION_MARKER
    marker_payload = marker.payload
    assert isinstance(marker_payload, CompactionMarkerPayload)
    assert marker_payload.compaction_id == "compact-1"
    assert marker_payload.status == "started"
    model_input_events = sorted(
        (
            event
            for event in transcript_repo.events
            if event.model_order >= summary.model_order
        ),
        key=lambda event: event.model_order,
    )
    assert [event.payload for event in model_input_events] == [summary.payload]
    payload = summary.payload
    assert isinstance(payload, CompactionSummaryPayload)
    assert payload.covered_until_event_id == f"{2:032d}"
    assert payload.reason == "manual_command"
    assert "## Recent User Messages" in payload.content
    assert "## Recent Transcript" in payload.content
    assert "1. old" in payload.content
    assert "2. recent" in payload.content
    assert '"kind"' not in payload.content
    assert '"model_order"' not in payload.content


async def test_compactor_opens_no_transaction_during_external_summary_call() -> None:
    """Compaction opens no database transaction during model latency."""
    events = [_event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old"))]
    session_manager = _SessionManager()
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Verify no compaction transaction is active."""
        del old_events, summary_budget
        assert session_manager.active_scopes == 0
        assert len(session_manager.sessions) == 1
        return "summary"

    await _compactor(
        session_manager=session_manager,
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo(),
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
    )

    assert len(session_manager.sessions) == 2
    assert [session.commit_count for session in session_manager.sessions] == [1, 1]


async def test_compactor_preserves_input_appended_during_summary() -> None:
    """Input appended during summary remains after the new model-input head."""
    events = [_event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old"))]
    session_manager = _SessionManager()
    concurrent_session = _Session()
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Append input while no compaction transaction is open."""
        del old_events, summary_budget
        assert session_manager.active_scopes == 0
        assert len(session_manager.sessions) == 1
        await transcript_repo.append(
            concurrent_session,
            EventCreate(
                session_id="session-1",
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="during compaction").model_dump(
                    mode="json",
                    exclude_none=True,
                ),
            ),
        )
        return "summary"

    summary = await _compactor(
        session_manager=session_manager,
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo(),
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
    )

    assert summary is not None
    concurrent_input = transcript_repo.events[1]
    assert summary.model_order == events[0].model_order + 2
    assert concurrent_input.model_order > summary.model_order
    model_input_events = sorted(
        (
            event
            for event in transcript_repo.events
            if event.model_order >= summary.model_order
        ),
        key=lambda event: event.model_order,
    )
    assert [event.id for event in model_input_events] == [
        summary.id,
        concurrent_input.id,
    ]


async def test_compactor_rejects_stale_model_input_head_before_commit() -> None:
    """A concurrent head move prevents marker, summary, and head mutation."""
    events = [_event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old"))]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Advance the model-input head while the summary is in flight."""
        del old_events, summary_budget
        session_repo.model_input_head_event_id = "concurrent-summary"
        return "summary"

    with pytest.raises(CompactionPlanStaleError):
        await _compactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ).compact(
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
        )

    assert transcript_repo.events == events
    assert session_repo.head_event_id is None


async def test_compactor_continuity_uses_concise_transcript_labels() -> None:
    """Continuity transcript omits redundant event and tool wrapper labels."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="run it"),
        ),
        _event(
            "2",
            EventKind.CLIENT_TOOL_CALL,
            ClientToolCallPayload(
                call_id="call-1",
                name="read_text",
                arguments='{"path":"/tmp/report.txt"}',
                native_artifact=_native_artifact(),
                wire_dialect="json_function",
            ),
        ),
        _event(
            "3",
            EventKind.CLIENT_TOOL_RESULT,
            ClientToolResultPayload(
                call_id="call-1",
                name="read_text",
                status="completed",
                output=[OutputTextPart(text="report contents")],
                wire_dialect="json_function",
            ),
        ),
    ]
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return a summary that does not itself contain event text."""
        del old_events, summary_budget
        return "summary"

    summary = await _compactor(
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo(),
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
    )

    assert summary is not None
    payload = summary.payload
    assert isinstance(payload, CompactionSummaryPayload)
    assert "## Recent User Messages" in payload.content
    assert "## Recent Transcript" in payload.content
    assert "### Recent User Message" not in payload.content
    assert "User message:" not in payload.content
    assert "Tool call:\nread_text\narguments:" in payload.content
    assert "Tool result:\nreport contents" in payload.content
    assert "function_call_output" not in payload.content
    assert "call_id:" not in payload.content
    assert "\noutput:\n" not in payload.content


async def test_compactor_continuity_omits_plaintext_custom_input() -> None:
    """Do not pass custom tool input through continuity or its hook context."""
    omitted_input = "opaque-custom-input"
    redacted_input = "[plaintext custom input omitted]"
    events = [
        _event(
            "1",
            EventKind.CLIENT_TOOL_CALL,
            ClientToolCallPayload(
                call_id="call-custom",
                name="apply_patch",
                arguments=omitted_input,
                native_artifact=_native_artifact(),
                wire_dialect="plaintext_custom",
            ),
        ),
    ]
    captured: dict[str, str] = {}

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return a fixed summary without inspecting the transcript."""
        del old_events, summary_budget
        return "summary"

    async def enrich(
        *,
        summary: str,
        continuity_history: str,
        compaction_id: str,
        reason: str | None,
        covered_until_event_id: str,
    ) -> str:
        """Capture the hook-visible continuity history."""
        del compaction_id, reason, covered_until_event_id
        captured["continuity_history"] = continuity_history
        return summary

    summary = await _compactor(
        transcript_repo=_TranscriptRepo(events),
        session_repo=_SessionRepo(),
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
        summary_enricher=enrich,
    )

    assert summary is not None
    payload = summary.payload
    assert isinstance(payload, CompactionSummaryPayload)
    assert omitted_input not in captured["continuity_history"]
    assert omitted_input not in payload.content
    assert redacted_input in captured["continuity_history"]
    assert redacted_input in payload.content


async def test_plaintext_custom_input_does_not_trigger_auto_compaction() -> None:
    """Estimate custom calls from the safe projection instead of their input."""
    events = [
        _event(
            "1",
            EventKind.CLIENT_TOOL_CALL,
            ClientToolCallPayload(
                call_id="call-custom",
                name="apply_patch",
                arguments="opaque" * 10_000,
                native_artifact=_native_artifact(),
                wire_dialect="plaintext_custom",
            ),
        )
    ]

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Fail if custom input reaches the auto-compaction threshold."""
        del old_events, summary_budget
        raise AssertionError("custom input must not trigger compaction")

    result = await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=_compactor(
            transcript_repo=_TranscriptRepo(events),
            session_repo=_SessionRepo(),
        ),
        summarize=summarize,
        max_input_tokens=2_000,
        auto_compaction_threshold_tokens=1_000,
        compaction_id_factory=lambda: "compact-1",
    ).compact(events)

    assert result == events


async def test_compactor_summary_enricher_runs_before_continuity_append() -> None:
    """Summary enrichment can insert content before final continuity history."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="old request"),
        )
    ]
    covered_until_event_id = events[-1].id
    transcript_repo = _TranscriptRepo(events)
    captured: dict[str, str | None] = {}

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return base summary."""
        del old_events, summary_budget
        return "summary"

    async def enrich(
        *,
        summary: str,
        continuity_history: str,
        compaction_id: str,
        reason: str | None,
        covered_until_event_id: str,
    ) -> str:
        """Append enrichment before continuity is reattached."""
        captured["summary"] = summary
        captured["continuity_history"] = continuity_history
        captured["compaction_id"] = compaction_id
        captured["reason"] = reason
        captured["covered_until_event_id"] = covered_until_event_id
        return summary + "\n\n## Toolkit Enrichment\n- extra"

    summary = await _compactor(
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo(),
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
        reason="manual_command",
        summary_enricher=enrich,
    )

    assert summary is not None
    payload = summary.payload
    assert isinstance(payload, CompactionSummaryPayload)
    assert captured == {
        "summary": "summary",
        "continuity_history": (
            "## Recent User Messages\n"
            "Last 5 user messages from the compacted transcript, kept independent "
            "of the recent transcript window.\n"
            "Per-message cap: 2000 estimated tokens.\n\n"
            "1. old request\n\n"
            "## Recent Transcript\n"
            "Recent model-visible excerpts from the compacted transcript. Each "
            "excerpt is bounded and may be truncated.\n"
            "Recent turn window: last 5 completed model turns.\n"
            "Per-event cap: 2000 estimated tokens.\n\n"
            "### 1\n"
            "User:\nold request"
        ),
        "compaction_id": "compact-1",
        "reason": "manual_command",
        "covered_until_event_id": covered_until_event_id,
    }
    assert payload.content.index("summary") < payload.content.index(
        "## Toolkit Enrichment"
    )
    assert payload.content.index("## Toolkit Enrichment") < payload.content.index(
        "## Recent User Messages"
    )


async def test_compactor_runs_commit_action_after_head_move_before_commit() -> None:
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="old request"),
        )
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()
    session_manager = _SessionManager()
    commit_action_sessions: list[AsyncSession] = []

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        del old_events, summary_budget
        return "summary"

    async def on_committing(session: AsyncSession) -> None:
        assert session is session_manager.sessions[-1]
        assert session_repo.model_input_head_event_id is not None
        assert session_manager.sessions[-1].commit_count == 0
        commit_action_sessions.append(session)

    summary = await _compactor(
        session_manager=session_manager,
        transcript_repo=transcript_repo,
        session_repo=session_repo,
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
        on_committing=on_committing,
    )

    assert summary is not None
    assert commit_action_sessions == [session_manager.sessions[-1]]
    assert session_manager.sessions[-1].commit_count == 1


async def test_compactor_commit_action_failure_prevents_final_commit() -> None:
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="old request"),
        )
    ]
    session_manager = _SessionManager()

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        del old_events, summary_budget
        return "summary"

    async def fail_commit_action(session: AsyncSession) -> None:
        del session
        raise RuntimeError("state reset failed")

    with pytest.raises(RuntimeError, match="state reset failed"):
        await _compactor(
            session_manager=session_manager,
            transcript_repo=_TranscriptRepo(events),
            session_repo=_SessionRepo(),
        ).compact(
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
            on_committing=fail_commit_action,
        )

    assert session_manager.sessions[-1].commit_count == 0


async def test_compactor_continuity_uses_last_five_completed_turns() -> None:
    """Continuity excerpts include only the last five completed model turns."""
    events: list[Event] = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="initial request"),
        )
    ]
    for turn in range(1, 7):
        events.append(
            _event(
                str(turn * 2),
                EventKind.ASSISTANT_MESSAGE,
                AssistantMessagePayload(
                    content=f"assistant turn {turn}",
                    native_artifact=_native_artifact(),
                ),
            )
        )
        events.append(
            _event(
                str((turn * 2) + 1),
                EventKind.TURN_MARKER,
                TurnMarkerPayload(run_id="run-1", usage=_usage(prompt_tokens=turn)),
            )
        )
    original_event_ids = [event.id for event in events]
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return a summary that does not itself contain event text."""
        del summary_budget
        assert [event.id for event in old_events] == original_event_ids
        return "summary"

    summary = await _compactor(
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo(),
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
    )

    assert summary is not None
    payload = summary.payload
    assert isinstance(payload, CompactionSummaryPayload)
    assert "## Recent User Messages" in payload.content
    assert "## Recent Transcript" in payload.content
    assert payload.content.index("## Recent User Messages") < payload.content.index(
        "## Recent Transcript"
    )
    user_message_section = payload.content.split(
        "## Recent Transcript",
        maxsplit=1,
    )[0]
    transcript_section = payload.content.split(
        "## Recent Transcript",
        maxsplit=1,
    )[1]
    assert "initial request" in user_message_section
    assert "initial request" not in transcript_section
    assert "assistant turn 1" not in transcript_section
    assert "Assistant:\nassistant turn 2" in transcript_section
    assert "Assistant:\nassistant turn 6" in transcript_section


async def test_compactor_continuity_user_message_section_uses_last_five_users() -> None:
    """Recent user messages are selected independently of recent turn events."""
    events: list[Event] = []
    for turn in range(1, 7):
        events.append(
            _event(
                str((turn * 3) - 2),
                EventKind.USER_MESSAGE,
                UserMessagePayload(content=f"user request {turn}"),
            )
        )
        events.append(
            _event(
                str((turn * 3) - 1),
                EventKind.ASSISTANT_MESSAGE,
                AssistantMessagePayload(
                    content=f"assistant turn {turn}",
                    native_artifact=_native_artifact(),
                ),
            )
        )
        events.append(
            _event(
                str(turn * 3),
                EventKind.TURN_MARKER,
                TurnMarkerPayload(run_id="run-1", usage=_usage(prompt_tokens=turn)),
            )
        )
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return a summary that does not itself contain event text."""
        del old_events, summary_budget
        return "summary"

    summary = await _compactor(
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo(),
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
    )

    assert summary is not None
    payload = summary.payload
    assert isinstance(payload, CompactionSummaryPayload)
    user_message_section = payload.content.split(
        "## Recent Transcript",
        maxsplit=1,
    )[0]
    assert "user request 1" not in user_message_section
    for turn in range(2, 7):
        assert f"user request {turn}" in user_message_section


async def test_compactor_truncates_large_continuity_events() -> None:
    """Oversized continuity excerpts are independently truncated."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="x" * 10_000),
        )
    ]
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return a summary that does not itself contain event text."""
        del old_events, summary_budget
        return "summary"

    summary = await _compactor(
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo(),
    ).compact(
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
    )

    assert summary is not None
    payload = summary.payload
    assert isinstance(payload, CompactionSummaryPayload)
    assert "[Event truncated by Azents continuity guard.]" in payload.content
    assert "x" * 9_000 not in payload.content


async def test_compactor_propagates_summary_failure_without_durable_marker() -> None:
    """Summary failure leaves transcript and model-input head unchanged."""
    events = [
        _event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old")),
        _event("2", EventKind.USER_MESSAGE, UserMessagePayload(content="recent")),
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Raise summary failure."""
        del old_events, summary_budget
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await _compactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ).compact(
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
        )

    assert session_repo.head_event_id is None
    assert transcript_repo.events == events


async def test_compactor_propagates_summary_enrichment_error_without_marker() -> None:
    """Summary enrichment failure leaves no durable compaction lifecycle event."""
    events = [_event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old"))]
    session_manager = _SessionManager()
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return summary text for enrichment."""
        del old_events, summary_budget
        return "summary"

    async def enrich(
        *,
        summary: str,
        continuity_history: str,
        compaction_id: str,
        reason: str | None,
        covered_until_event_id: str,
    ) -> str:
        """Simulate an external enrichment failure."""
        del summary, continuity_history, compaction_id, reason, covered_until_event_id
        raise RuntimeError("enrichment unavailable")

    with pytest.raises(RuntimeError, match="enrichment unavailable"):
        await _compactor(
            session_manager=session_manager,
            transcript_repo=transcript_repo,
            session_repo=_SessionRepo(),
        ).compact(
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
            summary_enricher=enrich,
        )

    assert len(session_manager.sessions) == 1
    assert transcript_repo.events == events


async def test_compactor_propagates_cancelled_start_callback_without_marker() -> None:
    """Cancellation in the start callback leaves transcript unchanged."""
    events = [_event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old"))]
    session_manager = _SessionManager()
    transcript_repo = _TranscriptRepo(events)

    async def on_started() -> None:
        """Simulate Stop while the start lifecycle hook is running."""
        raise asyncio.CancelledError

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Summary must not start after callback cancellation."""
        del old_events, summary_budget
        raise AssertionError("summarize should not be called")

    with pytest.raises(asyncio.CancelledError):
        await _compactor(
            session_manager=session_manager,
            transcript_repo=transcript_repo,
            session_repo=_SessionRepo(),
        ).compact(
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
            on_started=on_started,
        )

    assert len(session_manager.sessions) == 1
    assert transcript_repo.events == events


async def test_compactor_propagates_summary_cancellation_without_marker() -> None:
    """Cancellation during summary leaves transcript unchanged."""
    events = [_event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old"))]
    session_manager = _SessionManager()
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Simulate Stop cancelling the external summary call."""
        del old_events, summary_budget
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _compactor(
            session_manager=session_manager,
            transcript_repo=transcript_repo,
            session_repo=_SessionRepo(),
        ).compact(
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
        )

    assert len(session_manager.sessions) == 1
    assert transcript_repo.events == events


async def test_compactor_raises_when_summary_is_empty() -> None:
    """Empty summary propagates failure without durable lifecycle markers."""
    events = [
        _event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old")),
        _event("2", EventKind.USER_MESSAGE, UserMessagePayload(content="recent")),
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return empty summary."""
        del old_events, summary_budget
        return "   "

    with pytest.raises(CompactionFailedError, match="summary model returned no text"):
        await _compactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ).compact(
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
        )

    assert session_repo.head_event_id is None
    assert transcript_repo.events == events


async def test_auto_compaction_runs_when_threshold_is_exceeded() -> None:
    """Auto compaction persists only the successful summary."""
    events = [
        _event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old" * 100)),
        _event("2", EventKind.USER_MESSAGE, UserMessagePayload(content="recent")),
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return summary result."""
        del summary_budget
        assert [event.id for event in old_events] == [events[0].id, events[1].id]
        return f"summary:{old_events[-1].id}"

    result = await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=_compactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ),
        summarize=summarize,
        max_input_tokens=10,
        auto_compaction_threshold_tokens=None,
        compaction_id_factory=lambda: "compact-1",
    ).compact(events)

    assert session_repo.head_event_id is not None
    assert len(result) == 1
    assert result[0].kind == EventKind.COMPACTION_SUMMARY
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.USER_MESSAGE,
        EventKind.USER_MESSAGE,
        EventKind.COMPACTION_MARKER,
        EventKind.COMPACTION_SUMMARY,
    ]
    summary_payload = result[0].payload
    assert isinstance(summary_payload, CompactionSummaryPayload)
    assert summary_payload.reason == "auto_threshold_exceeded"
    assert "## Recent User Messages" in summary_payload.content
    assert "## Recent Transcript" in summary_payload.content
    assert "2. recent" in summary_payload.content


async def test_auto_compaction_calls_started_before_summary_without_marker() -> None:
    """Auto compaction reports live start before the external summary call."""
    events = [
        _event("1", EventKind.USER_MESSAGE, UserMessagePayload(content="old" * 100)),
        _event("2", EventKind.USER_MESSAGE, UserMessagePayload(content="recent")),
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()
    session_manager = _SessionManager()
    calls: list[str] = []

    async def on_phase_started() -> None:
        assert session_manager.active_scopes == 0
        assert len(session_manager.sessions) == 1
        assert transcript_repo.events == events
        calls.append("phase")

    async def on_compaction_started() -> None:
        assert calls == ["phase"]
        calls.append("hook")

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Record summary call order."""
        del old_events, summary_budget
        calls.append("summarize")
        return "summary"

    await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=_compactor(
            session_manager=session_manager,
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ),
        summarize=summarize,
        max_input_tokens=10,
        auto_compaction_threshold_tokens=None,
        compaction_id_factory=lambda: "compact-1",
        on_compaction_started=on_compaction_started,
    ).compact(events, on_started=on_phase_started)

    assert calls == ["phase", "hook", "summarize"]


async def test_auto_compaction_marks_compacted_only_when_summary_is_created() -> None:
    """Auto compaction marks was_compacted only when actual summary is created."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="old" * 100),
        ),
        _event(
            "2",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="recent"),
        ),
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()
    session_manager = _SessionManager()
    commit_action_sessions: list[AsyncSession] = []

    async def summarize(
        old_events: Sequence[Event],
        max_output_tokens: int,
    ) -> str:
        """Return summary result."""
        del old_events, max_output_tokens
        return "summary"

    async def on_committing(session: AsyncSession) -> None:
        commit_action_sessions.append(session)

    filter_ = EventAutoCompactionFilter(
        session_id="session-1",
        compactor=_compactor(
            session_manager=session_manager,
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ),
        summarize=summarize,
        max_input_tokens=10,
        auto_compaction_threshold_tokens=None,
        compaction_id_factory=lambda: "compact-1",
        on_committing=on_committing,
    )

    await filter_.compact(events)

    assert filter_.was_compacted is True
    assert commit_action_sessions == [session_manager.sessions[-1]]


async def test_auto_compaction_skips_when_threshold_is_not_exceeded() -> None:
    """Auto compaction does not change transcript when below threshold."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="short"),
        )
    ]
    transcript_repo = _TranscriptRepo(events)
    commit_action_sessions: list[AsyncSession] = []

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Summary function that should not be called."""
        del old_events, summary_budget
        raise AssertionError("summarize should not be called")

    async def on_committing(session: AsyncSession) -> None:
        commit_action_sessions.append(session)

    result = await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=_compactor(
            transcript_repo=transcript_repo,
            session_repo=_SessionRepo(),
        ),
        summarize=summarize,
        max_input_tokens=1000,
        auto_compaction_threshold_tokens=None,
        compaction_id_factory=lambda: "compact-1",
        on_committing=on_committing,
    ).compact(events)

    assert result == events
    assert commit_action_sessions == []


async def test_auto_compaction_uses_explicit_threshold_override() -> None:
    """Recovered runs keep their persisted auto-compaction threshold."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="short"),
        )
    ]
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return a summary when the explicit threshold is exceeded."""
        del old_events, summary_budget
        return "summary"

    result = await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=_compactor(
            transcript_repo=transcript_repo,
            session_repo=_SessionRepo(),
        ),
        summarize=summarize,
        max_input_tokens=1000,
        auto_compaction_threshold_tokens=1,
        compaction_id_factory=lambda: "compact-1",
    ).compact(events)

    assert [event.kind for event in result] == [EventKind.COMPACTION_SUMMARY]


async def test_auto_compaction_uses_latest_turn_marker_usage() -> None:
    """Large tool output before latest turn marker is not counted again."""
    events = [
        _event(
            "1",
            EventKind.CLIENT_TOOL_RESULT,
            ClientToolResultPayload(
                call_id="call-1",
                name="read_text",
                status="completed",
                output=[OutputTextPart(text="x" * 50_000)],
                wire_dialect="json_function",
            ),
        ),
        _event(
            "2",
            EventKind.TURN_MARKER,
            TurnMarkerPayload(run_id="run-1", usage=_usage(prompt_tokens=10)),
        ),
    ]
    transcript_repo = _TranscriptRepo(events)

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Summary function that should not be called."""
        del old_events, summary_budget
        raise AssertionError("summarize should not be called")

    result = await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=_compactor(
            transcript_repo=transcript_repo,
            session_repo=_SessionRepo(),
        ),
        summarize=summarize,
        max_input_tokens=1000,
        auto_compaction_threshold_tokens=None,
        compaction_id_factory=lambda: "compact-1",
    ).compact(events)

    assert result == events


async def test_auto_compaction_counts_events_after_latest_turn_marker() -> None:
    """Delta estimate after latest turn marker is added to provider usage."""
    events = [
        _event(
            "1",
            EventKind.TURN_MARKER,
            TurnMarkerPayload(run_id="run-1", usage=_usage(prompt_tokens=80)),
        ),
        _event(
            "2",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="u" * 400),
        ),
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return summary result."""
        del old_events, summary_budget
        return "summary"

    result = await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=_compactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ),
        summarize=summarize,
        max_input_tokens=100,
        auto_compaction_threshold_tokens=None,
        compaction_id_factory=lambda: "compact-1",
    ).compact(events)

    assert session_repo.head_event_id is not None
    assert result[0].kind == EventKind.COMPACTION_SUMMARY


async def test_pre_lower_pipeline_and_native_request_guard() -> None:
    """Pipeline is applied in order, and post-lower guard rejects oversized input."""
    event = _event(
        "1",
        EventKind.USER_MESSAGE,
        UserMessagePayload(content="hello"),
    )
    result = await EventPreLowerFilterPipeline([NoopPreLowerFilter()]).apply(
        _Session(),
        [event],
    )
    assert result == [event]

    guard = NativeRequestSizeGuard(max_input_chars=4)
    request = NativeModelRequest(model="gpt-5.1", input=[{"content": "too long"}])
    try:
        guard.apply(request)
    except ValueError as exc:
        assert "size guard" in str(exc)
    else:
        raise AssertionError("guard must reject oversized request")

    tool_schema_request = NativeModelRequest(
        model="gpt-5.1",
        input=[],
        tools=[{"name": "tool", "description": "x" * 100}],
        kwargs={"instructions": "y" * 100},
    )
    try:
        NativeRequestSizeGuard(max_input_chars=50).apply(tool_schema_request)
    except ValueError as exc:
        assert "size guard" in str(exc)
    else:
        raise AssertionError("guard must count tools and instructions")

    pipeline = PostLowerFilterPipeline([NativeRequestSizeGuard(max_input_chars=100)])
    assert pipeline.apply(NativeModelRequest(model="gpt-5.1", input=[])).input == []


def _event(
    id_suffix: str,
    kind: EventKind,
    payload: EventPayload,
) -> Event:
    """Create Event test fixture."""
    return Event(
        id=f"{int(id_suffix):032d}",
        session_id="session-1",
        kind=kind,
        payload=payload,
        model_order=int(id_suffix) * 1000,
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _external_payload() -> ExternalChannelMessagePayload:
    """Create one external message fixture."""
    return ExternalChannelMessagePayload(
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        resource_id="resource-1",
        resource_label="#incident / thread",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding-1",
        invocation_batch_id="batch-1",
        external_message_id="message-1",
        revision_id="revision-1",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        projection_root_id="external-channel:binding-1:message-1",
        provider_message_key="slack:tenant-1:C1:1.000001",
        provider_position="00000000000000000001.000001",
        principal_id="principal-1",
        provider_user_id="U1",
        sender_display_name="Alice",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        authorization="context_only",
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        body="context body",
        attachment_metadata={
            "files": [
                {
                    "name": "report.csv",
                    "title": "Report",
                    "media_type": "text/csv",
                    "declared_size": 1024,
                    "supported": True,
                    "unsupported_reason": None,
                    "file": "external-file:v1:slack:binding-1:F123",
                    "url_private": "https://secret-download.example/F123",
                }
            ]
        },
        provider_created_at=datetime.datetime(2026, 7, 22, 12, 0, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url=None,
        truncated_context_message_count=3,
        truncated_context_size=256,
        correction_of_revision_id=None,
    )


def _payload_from_create(create: EventCreate) -> EventPayload:
    """Restore payload type from EventCreate."""
    match create.kind:
        case EventKind.USER_MESSAGE:
            return UserMessagePayload.model_validate(create.payload)
        case EventKind.CLIENT_TOOL_RESULT:
            return ClientToolResultPayload.model_validate(create.payload)
        case EventKind.COMPACTION_MARKER:
            return CompactionMarkerPayload.model_validate(create.payload)
        case EventKind.COMPACTION_SUMMARY:
            return CompactionSummaryPayload.model_validate(create.payload)
        case EventKind.TURN_MARKER:
            return TurnMarkerPayload.model_validate(create.payload)
        case EventKind.RUN_MARKER:
            return RunMarkerPayload.model_validate(create.payload)
        case _:
            raise AssertionError(f"unsupported test payload kind: {create.kind}")


def test_external_message_is_visible_to_tokens_and_continuity() -> None:
    """External source metadata survives model-value and continuity rendering."""
    event = _event(
        "1",
        EventKind.EXTERNAL_CHANNEL_MESSAGE,
        _external_payload(),
    )

    value = filters._model_visible_event_value(  # pyright: ignore[reportPrivateUsage]
        event
    )
    text = filters._model_visible_event_text(  # pyright: ignore[reportPrivateUsage]
        event
    )

    assert isinstance(value, dict)
    assert value["message_type"] == "external_channel_message"
    assert value["authorization"] == "context_only"
    assert value["truncated_context"] == {"message_count": 3, "size": 256}
    attachments = value["attachments"]
    assert isinstance(attachments, dict)
    files = attachments["files"]
    assert isinstance(files, list)
    assert isinstance(files[0], dict)
    assert files[0]["file"] == "external-file:v1:slack:binding-1:F123"
    assert "secret-download" not in str(value)
    visible_bytes = filters._estimate_event_visible_bytes(  # pyright: ignore[reportPrivateUsage]
        event
    )
    without_files = event.model_copy(
        update={
            "payload": event.payload.model_copy(
                update={"attachment_metadata": {}},
            )
        }
    )
    assert visible_bytes > filters._estimate_event_visible_bytes(  # pyright: ignore[reportPrivateUsage]
        without_files
    )
    assert text is not None
    assert "Provider: slack" in text
    assert "Authorization: context_only" in text
    assert "context body" in text
    assert "Files:" in text
    assert "File: external-file:v1:slack:binding-1:F123" in text
    assert "secret-download" not in text
