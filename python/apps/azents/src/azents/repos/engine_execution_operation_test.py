"""Completed Engine execution lifecycle operation tests."""

import datetime
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.events.types import ActiveToolCall
from azents.repos.engine_execution_operation import (
    EngineExecutionOperationRepository,
)


class _SessionManager:
    """Expose transaction activity for completed-operation assertions."""

    def __init__(self) -> None:
        self.active = False
        self.transaction_count = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        """Yield one synthetic active transaction."""
        assert not self.active
        self.active = True
        self.transaction_count += 1
        try:
            yield AsyncSession()
        finally:
            self.active = False


@dataclass(frozen=True)
class _RunState:
    """Detached Run state returned by the focused repository."""

    status: AgentRunStatus
    model_call_started_at: datetime.datetime | None


class _RunRepository:
    """Record phase reads and mutations."""

    def __init__(
        self,
        manager: _SessionManager,
        *,
        status: AgentRunStatus = AgentRunStatus.RUNNING,
    ) -> None:
        self.manager = manager
        self.status = status
        self.updates: list[tuple[str, AgentRunPhase, list[ActiveToolCall] | None]] = []
        self.started_at = datetime.datetime.now(datetime.UTC)

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> _RunState:
        """Return configured current status inside the transaction."""
        del session, run_id
        assert self.manager.active
        return _RunState(status=self.status, model_call_started_at=None)

    async def update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> _RunState:
        """Record phase mutation inside the transaction."""
        del session
        assert self.manager.active
        self.updates.append((run_id, phase, active_tool_calls))
        return _RunState(
            status=self.status,
            model_call_started_at=self.started_at,
        )


class _ModelFilePinRepository:
    """Record ModelFile pin admission."""

    def __init__(self, manager: _SessionManager) -> None:
        self.manager = manager
        self.pins: list[tuple[str, str, list[str]]] = []

    async def pin_many(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        model_file_ids: Sequence[str],
    ) -> None:
        """Record pins while the completed operation is active."""
        del session
        assert self.manager.active
        self.pins.append((session_id, run_id, list(model_file_ids)))


async def test_phase_update_closes_transaction_before_returning() -> None:
    """Ordinary phase update returns only after transaction closure."""
    manager = _SessionManager()
    runs = _RunRepository(manager)
    repository = EngineExecutionOperationRepository(
        session_manager=manager,
        run_repository=runs,
        model_file_pin_repository=None,
    )

    started_at = await repository.update_phase(
        run_id="run-1",
        phase=AgentRunPhase.PREPARING_INPUT,
    )

    assert started_at == runs.started_at
    assert not manager.active
    assert manager.transaction_count == 1
    assert runs.updates == [("run-1", AgentRunPhase.PREPARING_INPUT, None)]


async def test_conditional_phase_update_skips_non_running_run() -> None:
    """STOPPING guard preserves a Run that already became terminal."""
    manager = _SessionManager()
    runs = _RunRepository(manager, status=AgentRunStatus.COMPLETED)
    repository = EngineExecutionOperationRepository(
        session_manager=manager,
        run_repository=runs,
        model_file_pin_repository=None,
    )

    result = await repository.update_phase_if_running(
        run_id="run-1",
        phase=AgentRunPhase.STOPPING,
        active_tool_calls=[],
    )

    assert result.updated is False
    assert result.model_call_started_at is None
    assert not manager.active
    assert runs.updates == []


async def test_model_file_pin_closes_transaction_before_returning() -> None:
    """ModelFile pin admission is one completed repository operation."""
    manager = _SessionManager()
    pins = _ModelFilePinRepository(manager)
    repository = EngineExecutionOperationRepository(
        session_manager=manager,
        run_repository=_RunRepository(manager),
        model_file_pin_repository=pins,
    )

    await repository.pin_model_files(
        session_id="session-1",
        run_id="run-1",
        model_file_ids=["file-1", "file-2"],
    )

    assert not manager.active
    assert pins.pins == [("session-1", "run-1", ["file-1", "file-2"])]
