"""One SessionRunner selects private execution without public projections/effects."""

import asyncio
import datetime
from collections.abc import Awaitable, Callable

import pytest

from azents.broker.types import SessionWakeUp
from azents.core.enums import AgentRunStatus
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
    MemoryExecutionAuthorityError,
    MemoryExecutionBinding,
)
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.session_execution import CanonicalExecutionSnapshotError
from azents.worker.run.memory_execution import MemoryRunExecutor
from azents.worker.run.results import RunExecutionResult
from azents.worker.session.supervisor import RunStopController
from azents.worker.worker_test import _Host, _make_session_runner


def _binding(session_id: str) -> MemoryExecutionBinding:
    return MemoryExecutionBinding(
        unit_id="u" * 32,
        unit=ConsolidationUnitKey(
            workspace_id="w" * 32,
            agent_id="a" * 32,
            scope=ConsolidationScope.TEAM,
            associated_user_id=None,
        ),
        session_id=session_id,
        deadline_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
        execution_policy=HistoricalMemoryExecutionConfig(),
        started_turns=0,
        accepted=None,
    )


class _MemoryRepository(MemoryExecutionRepository):
    def __init__(
        self, *, replacement: MemoryExecutionBinding | None, fail: bool
    ) -> None:
        self.replacement = replacement
        self.fail = fail
        self.claimed: list[SessionExecutionOwner] = []

    async def load_binding(self, session_id: str) -> MemoryExecutionBinding | None:
        return _binding(session_id)

    async def recover_worker_execution(
        self, binding: MemoryExecutionBinding, owner: SessionExecutionOwner
    ) -> MemoryExecutionBinding | None:
        self.claimed.append(owner)
        assert owner.session_id == binding.session_id and owner.owner_generation == 1
        if self.fail:
            raise MemoryExecutionAuthorityError(
                "Current private execution is unavailable"
            )
        return self.replacement


class _MemoryExecutor(MemoryRunExecutor):
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.archived: list[str] = []

    async def execute(
        self,
        binding: MemoryExecutionBinding,
        *,
        owner_generation: int,
        shutdown_event: asyncio.Event,
        stop_controller: RunStopController,
        check_stop: Callable[[], Awaitable[bool]],
        drain_stop_signals: Callable[[], None],
    ) -> RunExecutionResult:
        assert owner_generation == 1
        assert not await check_stop()
        self.executed.append(binding.session_id)
        return RunExecutionResult(
            toolkits=[],
            terminal_event_observed=True,
            no_actionable_work=False,
            run_id="actual-memory-run",
            terminal_run_status=AgentRunStatus.COMPLETED,
        )

    async def archive_previous(
        self, binding: MemoryExecutionBinding, *, owner_generation: int
    ) -> None:
        assert owner_generation == 1
        self.archived.append(binding.session_id)


@pytest.mark.parametrize("case", ["first", "replacement", "retired", "authority-lost"])
async def test_private_routing_never_uses_public_snapshot_idle_hook_or_finalizer(
    case: str,
) -> None:
    host = _Host()
    host.snapshot_error = CanonicalExecutionSnapshotError(
        "Public projection must not load"
    )
    runner = _make_session_runner(host)
    replacement = (
        _binding("session-001" if case == "first" else "new-private-session")
        if case in ("first", "replacement")
        else None
    )
    repository = _MemoryRepository(
        replacement=replacement, fail=case == "authority-lost"
    )
    executor = _MemoryExecutor()
    runner.memory_execution_repository = repository
    runner.memory_run_executor = executor
    runner.enqueue(SessionWakeUp(session_id="session-001"))
    await asyncio.wait_for(runner.run(), timeout=5)
    assert runner.terminated and host.owner_generation_claims == 1
    assert repository.claimed == [SessionExecutionOwner("session-001", 1)]
    assert host.processed_messages == []
    assert host.idle_continuation_calls == []
    assert host.finalize_unhandled_calls == []
    assert host.parent_result_activity_run_ids == []
    if case == "first":
        assert executor.executed == ["session-001"]
        assert executor.archived == []
    elif case == "replacement":
        assert executor.executed == []
        assert executor.archived == ["session-001"]
        assert host.handover_messages == [
            SessionWakeUp(session_id="new-private-session")
        ]
    elif case == "retired":
        assert executor.executed == [] and executor.archived == ["session-001"]
        assert host.handover_messages == []
    else:
        assert executor.executed == executor.archived == host.handover_messages == []
