"""Regression contracts for native mutation results and named repository outputs."""

import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import CursorResult

from azents.core.enums import EventKind
from azents.engine.events.types import Event, SystemErrorPayload
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    IdempotentChatWriteResult,
)
from azents.repos.mailbox.promotion import MailboxEventAppendResult
from azents.repos.mutation_result import mutation_result
from azents.repos.scheduled_task.schedule import CronCursorAdvance
from azents.repos.session.data import RefreshTokenSessionMatch, Session, TokenMatch


@pytest.mark.parametrize("rowcount", [0, 1, 3, -1])
def test_mutation_result_preserves_native_row_count(rowcount: int) -> None:
    """Narrow a native result without reinterpreting its affected-row evidence."""
    result = MagicMock(spec=CursorResult)
    result.rowcount = rowcount
    assert mutation_result(result) is result
    assert mutation_result(result).rowcount == rowcount


def test_mutation_result_rejects_a_non_cursor_contract() -> None:
    """Unexpected execution contracts remain visible rather than being cast away."""
    with pytest.raises(RuntimeError, match="did not return CursorResult"):
        mutation_result(object())


def test_named_results_distinguish_same_type_fields() -> None:
    """Caller-visible names retain ordering and meaning for same-typed fields."""
    now = datetime.datetime(2026, 10, 5, tzinfo=datetime.UTC)
    event = Event(
        id="e" * 32,
        session_id="session",
        kind=EventKind.SYSTEM_ERROR,
        payload=SystemErrorPayload(content="Test failure"),
        external_id=None,
        adapter=None,
        provider=None,
        model=None,
        native_format=None,
        created_at=now,
    )
    appended = MailboxEventAppendResult(ordered=[event], inserted=[])
    assert appended.ordered == [event]
    assert appended.inserted == []
    cursor = CronCursorAdvance(
        first_due=now, first_future=now + datetime.timedelta(hours=1)
    )
    assert cursor.first_due == now
    assert cursor.first_future > cursor.first_due


def test_named_write_and_refresh_results_use_declared_fields() -> None:
    """Named results preserve the original values without requiring persistence."""
    now = datetime.datetime(2026, 10, 5, tzinfo=datetime.UTC)
    request = ChatWriteRequest.model_construct(
        id="request",
        session_id="session",
        requester_user_id="user",
        creation_agent_id=None,
        client_request_id="client",
        payload={},
        created_at=now,
    )
    outcome = IdempotentChatWriteResult(record=request, created=False)
    assert outcome.record is request
    assert outcome.created is False
    session = Session.model_construct(id="session", user_id="user")
    matched = RefreshTokenSessionMatch(session=session, token_match=TokenMatch.PREVIOUS)
    assert matched.session is session
    assert matched.token_match is TokenMatch.PREVIOUS
