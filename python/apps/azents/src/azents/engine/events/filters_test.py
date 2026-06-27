"""Event filter/compaction tests."""

import datetime
from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind, ExchangeFileStatus, ModelFileStatus
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
    ClientToolResultPayload,
    CompactionMarkerPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
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
from azents.engine.run.errors import CompactionFailedError
from azents.repos.agent_execution.data import EventCreate


class _Session(AsyncSession):
    """AsyncSession for tests."""


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

    async def move_model_input_head(
        self,
        session: AsyncSession,
        session_id: str,
        event_id: str,
    ) -> object:
        """Record head movement."""
        del session, session_id
        self.head_event_id = event_id
        return object()


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


async def test_compactor_appends_summary_and_moves_head() -> None:
    """Compaction moves head to summary id without deleting old events."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="old"),
        ),
        _event(
            "2",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="recent"),
        ),
    ]
    transcript_repo = _TranscriptRepo(events)
    session_repo = _SessionRepo()

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return summary result."""
        del summary_budget
        assert [event.id for event in old_events] == [events[0].id]
        return f"summary:{old_events[0].id}"

    summary = await EventCompactor(
        transcript_repo=transcript_repo,
        session_repo=session_repo,
    ).compact(
        _Session(),
        session_id="session-1",
        transcript=events,
        compaction_id="compact-1",
        summarize=summarize,
        protected_token_budget=0,
        reason="manual_command",
    )

    assert summary is not None
    assert session_repo.head_event_id == summary.id
    assert len(transcript_repo.events) == 4
    assert [event.model_order for event in transcript_repo.events] == [
        1000,
        2000,
        1001,
        1002,
    ]
    model_input_events = sorted(
        (
            event
            for event in transcript_repo.events
            if event.model_order >= summary.model_order
        ),
        key=lambda event: event.model_order,
    )
    assert [event.payload for event in model_input_events] == [
        summary.payload,
        events[1].payload,
    ]
    started_payload = transcript_repo.events[2].payload
    assert isinstance(started_payload, CompactionMarkerPayload)
    assert started_payload.reason == "manual_command"
    payload = summary.payload
    assert isinstance(payload, CompactionSummaryPayload)
    assert payload.covered_until_event_id == f"{1:032d}"
    assert payload.reason == "manual_command"


async def test_compactor_propagates_summary_failure() -> None:
    """Summary failure propagates instead of being hidden as success."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="old"),
        ),
        _event(
            "2",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="recent"),
        ),
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
        await EventCompactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ).compact(
            _Session(),
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
            protected_token_budget=0,
        )

    assert session_repo.head_event_id is None
    assert len(transcript_repo.events) == 4
    started_marker = transcript_repo.events[-2]
    assert started_marker.kind == EventKind.COMPACTION_MARKER
    started_payload = started_marker.payload
    assert isinstance(started_payload, CompactionMarkerPayload)
    assert started_payload.status == "started"
    failed_marker = transcript_repo.events[-1]
    assert failed_marker.kind == EventKind.COMPACTION_MARKER
    failed_payload = failed_marker.payload
    assert isinstance(failed_payload, CompactionMarkerPayload)
    assert failed_payload.status == "failed"
    assert failed_payload.reason == "summary_failed"
    assert failed_payload.error == "provider unavailable"


async def test_compactor_raises_when_summary_is_empty() -> None:
    """Empty summary leaves failed marker and propagates failure to caller."""
    events = [
        _event(
            "1",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="old"),
        ),
        _event(
            "2",
            EventKind.USER_MESSAGE,
            UserMessagePayload(content="recent"),
        ),
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
        await EventCompactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ).compact(
            _Session(),
            session_id="session-1",
            transcript=events,
            compaction_id="compact-1",
            summarize=summarize,
            protected_token_budget=0,
        )

    assert session_repo.head_event_id is None
    assert len(transcript_repo.events) == 4
    failed_marker = transcript_repo.events[-1]
    assert failed_marker.kind == EventKind.COMPACTION_MARKER
    payload = failed_marker.payload
    assert isinstance(payload, CompactionMarkerPayload)
    assert payload.status == "failed"
    assert payload.reason == "empty_summary"


async def test_auto_compaction_runs_when_threshold_is_exceeded() -> None:
    """Auto compaction returns summary and protected tail over threshold."""
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

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Return summary result."""
        del summary_budget
        assert [event.id for event in old_events] == [events[0].id]
        return f"summary:{old_events[0].id}"

    result = await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=EventCompactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ),
        summarize=summarize,
        max_input_tokens=10,
        protection_ratio=0.1,
        compaction_id_factory=lambda: "compact-1",
    ).apply(_Session(), events)

    assert session_repo.head_event_id is not None
    assert len(result) == 2
    assert result[0].kind == EventKind.COMPACTION_SUMMARY
    marker_payload = transcript_repo.events[2].payload
    assert isinstance(marker_payload, CompactionMarkerPayload)
    assert marker_payload.reason == "auto_threshold_exceeded"
    summary_payload = result[0].payload
    assert isinstance(summary_payload, CompactionSummaryPayload)
    assert summary_payload.reason == "auto_threshold_exceeded"
    assert result[1].payload == events[1].payload


async def test_auto_compaction_emits_started_before_summary_call() -> None:
    """Auto compaction calls start callback before long summary call."""
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
    calls: list[str] = []

    async def on_compaction_started() -> None:
        calls.append("started")

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
        compactor=EventCompactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ),
        summarize=summarize,
        max_input_tokens=10,
        protection_ratio=0.1,
        compaction_id_factory=lambda: "compact-1",
        on_compaction_started=on_compaction_started,
    ).apply(_Session(), events)

    assert calls == ["started", "summarize"]


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

    async def summarize(
        old_events: Sequence[Event],
        max_tokens: int,
    ) -> str:
        """Return summary result."""
        del old_events, max_tokens
        return "summary"

    filter_ = EventAutoCompactionFilter(
        session_id="session-1",
        compactor=EventCompactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ),
        summarize=summarize,
        max_input_tokens=10,
        protection_ratio=0.1,
        compaction_id_factory=lambda: "compact-1",
    )

    await filter_.apply(_Session(), events)

    assert filter_.was_compacted is True


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

    async def summarize(
        old_events: Sequence[Event],
        summary_budget: object,
    ) -> str:
        """Summary function that should not be called."""
        del old_events, summary_budget
        raise AssertionError("summarize should not be called")

    result = await EventAutoCompactionFilter(
        session_id="session-1",
        compactor=EventCompactor(
            transcript_repo=transcript_repo,
            session_repo=_SessionRepo(),
        ),
        summarize=summarize,
        max_input_tokens=1000,
        protection_ratio=0.3,
        compaction_id_factory=lambda: "compact-1",
    ).apply(_Session(), events)

    assert result == events


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
        compactor=EventCompactor(
            transcript_repo=transcript_repo,
            session_repo=_SessionRepo(),
        ),
        summarize=summarize,
        max_input_tokens=1000,
        protection_ratio=0.3,
        compaction_id_factory=lambda: "compact-1",
    ).apply(_Session(), events)

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
        compactor=EventCompactor(
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ),
        summarize=summarize,
        max_input_tokens=100,
        protection_ratio=0.1,
        compaction_id_factory=lambda: "compact-1",
    ).apply(_Session(), events)

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
