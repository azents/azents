"""Bounded Team Session cutover replay repository tests."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionRunState

from .cutover_replay import SessionCutoverReplayRepository


class _Result:
    """SQLAlchemy result double returning configured content-free rows."""

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def all(self) -> list[SimpleNamespace]:
        """Return the configured row sequence."""
        return self.rows


class _Session:
    """Async session double retaining the generated query."""

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.statement: sa.Select[Any] | None = None

    async def execute(self, statement: object) -> _Result:
        """Record the content-free candidate projection query."""
        self.statement = cast(sa.Select[Any], statement)
        return _Result(self.rows)


def _row(session_id: str) -> SimpleNamespace:
    """Create one content-free candidate query row."""
    return SimpleNamespace(
        id=session_id,
        owner_generation=3,
        run_state=AgentSessionRunState.RUNNING,
        wake_input_present=True,
        fifo_input_buffer_id="input-1",
        pending_command_present=False,
        pending_command_id=None,
        pending_command_complete=True,
        recoverable_run_id=None,
        recoverable_run_count=0,
        pending_idle_continuation_run_id=None,
        stop_request_present=False,
        stop_request_id=None,
        stop_request_complete=True,
    )


@pytest.mark.asyncio
async def test_candidate_batch_uses_cursor_and_limit_without_content_tables() -> None:
    """Select one bounded deterministic page from durable execution state only."""
    session = _Session([_row("session-1"), _row("session-2")])
    repository = SessionCutoverReplayRepository()

    batch = await repository.read_candidate_batch(
        cast(AsyncSession, session),
        batch_size=1,
        after_session_id="session-0",
    )

    assert [candidate.session_id for candidate in batch.candidates] == ["session-1"]
    assert batch.next_session_cursor == "session-1"
    assert session.statement is not None
    compiled = str(
        session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "LIMIT 2" in compiled
    assert "input_buffers" in compiled
    assert "scheduling_mode = 'wake_session'" in compiled
    assert "agent_runs" in compiled
    assert "events" not in compiled
    assert "exchange_files" not in compiled
