"""Typed historical tool linkage regressions without database effects."""

import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import azents.repos.message as message_module
from azents.core.enums import EventKind
from azents.core.json_value import JSONValue
from azents.engine.events.historical_memory_projection import (
    HistoricalMemoryEvidence,
    HistoricalMemoryEvidenceTier,
)
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
)
from azents.rdb.models.event import RDBEvent
from azents.repos.message import MessageRepository, _HistoricalMemoryScanBudget
from azents.repos.message.repository_test import _native_artifact

_PAYLOAD_ADAPTER = TypeAdapter(dict[str, JSONValue])


def _row(
    kind: EventKind,
    payload: ClientToolCallPayload | ClientToolResultPayload,
    identifier: str,
) -> RDBEvent:
    """Create a detached persisted payload row with an explicit timestamp."""
    row = RDBEvent(
        session_id="s" * 32,
        kind=kind,
        payload=_PAYLOAD_ADAPTER.validate_python(payload.model_dump(mode="json")),
    )
    row.id = identifier
    row.created_at = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    return row


class _LinkedResultsRepository(MessageRepository):
    """Capture result-query identity while returning already selected rows."""

    def __init__(self, results: list[RDBEvent]) -> None:
        self.results = results
        self.requested_call_ids: list[tuple[str, ...]] = []

    async def _historical_memory_tool_results(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        tail_event_id: str,
        call_ids: tuple[str, ...],
        budget: _HistoricalMemoryScanBudget,
    ) -> list[RDBEvent]:
        del session, session_id, tail_event_id, budget
        self.requested_call_ids.append(call_ids)
        return self.results


async def test_registered_tool_linkage_uses_validated_payload_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decoded calls and results preserve linkage, projection, and row order."""
    call = _row(
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id="call-1",
            name="channel_action",
            arguments='{"mode":"finish","binding":"binding-1"}',
            wire_dialect="json_function",
            native_artifact=_native_artifact(),
        ),
        "1" * 32,
    )
    result = _row(
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="call-1",
            name="channel_action",
            wire_dialect="json_function",
            status="completed",
            output="done",
        ),
        "2" * 32,
    )
    projected_events: list[Event] = []

    def project(
        event: Event,
        *,
        client_results: dict[str, ClientToolResultPayload] | None = None,
    ) -> HistoricalMemoryEvidence:
        assert isinstance(event.payload, ClientToolCallPayload)
        assert client_results is not None
        linked = client_results[event.payload.call_id]
        assert isinstance(linked, ClientToolResultPayload)
        assert linked.output == "done"
        projected_events.append(event)
        return HistoricalMemoryEvidence(
            event_id=event.id,
            source_index=0,
            tier=HistoricalMemoryEvidenceTier.ASSISTANT,
            text="conversation evidence",
        )

    monkeypatch.setattr(message_module, "project_historical_memory_event", project)
    session = AsyncMock(spec=AsyncSession)
    page = Mock()
    page.scalars.return_value = [call]
    session.execute.return_value = page
    repository = _LinkedResultsRepository([result])
    rows = await repository._list_historical_memory_registered_tools(
        session,
        session_id="s" * 32,
        tail_event_id="f" * 32,
        tool_names=("channel_action",),
        limit=1,
    )
    assert rows == [call, result]
    assert repository.requested_call_ids == [("call-1",)]
    assert len(projected_events) == 1
    session.execute.assert_awaited_once()


async def test_invalid_call_payload_fails_before_result_linkage() -> None:
    """A malformed persisted call cannot become a raw-JSON query identity."""
    call = _row(
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id="call-1",
            name="channel_action",
            arguments="{}",
            wire_dialect="json_function",
            native_artifact=_native_artifact(),
        ),
        "1" * 32,
    )
    del call.payload["call_id"]
    session = AsyncMock(spec=AsyncSession)
    page = Mock()
    page.scalars.return_value = [call]
    session.execute.return_value = page
    repository = _LinkedResultsRepository([])
    with pytest.raises(ValidationError):
        await repository._list_historical_memory_registered_tools(
            session,
            session_id="s" * 32,
            tail_event_id="f" * 32,
            tool_names=("channel_action",),
            limit=1,
        )
    assert repository.requested_call_ids == []
