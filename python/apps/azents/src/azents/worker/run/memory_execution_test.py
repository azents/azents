"""Common Memory executor lifetime, quota handoff and accepted follow-up truth."""

import asyncio
import dataclasses
import datetime
from collections.abc import Awaitable, Callable
from typing import Annotated, NamedTuple
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from fastapi import Depends
from fastapi.dependencies.utils import get_dependant

from azents.broker.types import SessionWakeUp
from azents.core.config import Config
from azents.core.enums import AgentRunStatus, AgentSessionRunState
from azents.core.historical_memory_consolidation import (
    MemoryExecutionAuthorityError,
    MemoryExecutionPrincipal,
)
from azents.core.model_operation import ModelOperationState
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.model_messages import TransientModelMessage
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import ModelStreamCallContext
from azents.engine.provider_model_operation import PreparedModelOperation
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.historical_memory_execution import (
    RDBMemoryExecution,
    RDBMemoryUnit,
)
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.compaction_operation import CompactionOperationRepository
from azents.repos.engine_read import EngineModelReadRepository
from azents.repos.historical_memory_consolidation.operations_test import (
    _failure,
    _metadata,
    _principal,
    _repository,
)
from azents.repos.memory_execution_events import MemoryExecutionEventsRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_operation_completion import ModelOperationCompletionRepository
from azents.repos.session_archive_operations import SessionArchiveOperations
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.toolkit_state.engine import ToolWorkingSetStore
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.historical_memory.consolidation_host import (
    ConsolidationIterationHost,
)
from azents.services.historical_memory.consolidation_host_test import (
    _call,
    _never_stop,
    _ScriptedModel,
)
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
)
from azents.services.historical_memory.execution_context import (
    MemoryExecutionContextService,
)
from azents.services.model_metadata import ModelMetadataService
from azents.services.session_execution_files import ExecutionFileObservations
from azents.testing.consolidation import memory_execution_repository
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.types import require_instance
from azents.worker.run.memory_execution import MemoryRunExecutor
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.supervisor import RunStopController


@dataclasses.dataclass(kw_only=True)
class _ControlledModel(_ScriptedModel):
    error: ModelProviderFailure | None
    quota_after_turns: int | None
    entered: asyncio.Event | None
    release: asyncio.Event | None
    block_after_turns: int

    async def invoke(
        self,
        prepared: PreparedModelOperation,
        *,
        context: ModelStreamCallContext,
    ) -> NormalizedAdapterOutput[TransientModelMessage]:
        if (
            self.error is not None
            and self.quota_after_turns is not None
            and len(self.contexts) >= self.quota_after_turns
        ):
            raise self.error
        if (
            self.entered is not None
            and self.release is not None
            and len(self.contexts) >= self.block_after_turns
        ):
            self.entered.set()
            await self.release.wait()
        return await super().invoke(prepared, context=context)


@dataclasses.dataclass(frozen=True)
class _ScriptedExecutor(MemoryRunExecutor):
    script: list[list[TransientModelMessage]]
    quotas: list[int]
    host_models: list[_ControlledModel]
    entered: asyncio.Event | None
    release: asyncio.Event | None
    block_after_turns: int

    async def _create_host(
        self,
        principal: MemoryExecutionPrincipal,
        *,
        check_stop: Callable[[], Awaitable[bool]],
    ) -> ConsolidationIterationHost:
        operation = await self.models.begin(principal)
        model = _ControlledModel(
            self.script,
            close_failure=False,
            selection=operation.current_candidate.model_selection,
            error=_failure(
                operation, ModelProviderFailureCategory.QUOTA_OR_BILLING, model=None
            )
            if self.quotas
            else None,
            quota_after_turns=self.quotas[0] if self.quotas else None,
            entered=self.entered,
            release=self.release,
            block_after_turns=self.block_after_turns,
        )
        if self.quotas:
            self.quotas.pop()
        self.host_models.append(model)
        return ConsolidationIterationHost(
            principal,
            model,
            ConsolidationToolBindings(
                principal,
                self.files,
                self.executions,
                ExecutionFileObservations(principal.owner),
            ),
            self.executions,
            self.context_port,
            check_stop,
        )


class _ExecutorFixture(NamedTuple):
    executor: _ScriptedExecutor
    principal: MemoryExecutionPrincipal


async def _executor(
    manager: SessionManager[WriteSession],
    *,
    quotas: bool,
    deadline_seconds: float | None,
    block_after_turns: int,
) -> _ExecutorFixture:
    principal = await _principal(manager)
    executions = memory_execution_repository(manager)
    runs = AgentRunRepository()
    events = EventTranscriptRepository()
    records = SessionExecutionRecordRepository()
    completion = ModelOperationCompletionRepository(
        AgentSessionRepository(), runs, ModelCandidateHealthRepository(manager)
    )
    context = MemoryExecutionContextService(
        MemoryExecutionEventsRepository(
            manager, manager, executions, events, records, runs
        ),
        CompactionOperationRepository(
            manager, events, records, completion, ToolWorkingSetStore(manager), None
        ),
    )
    lifecycle = AsyncMock(spec=SessionLifecycleService)
    lifecycle.has_stop_request.return_value = False
    archives = AsyncMock(spec=SessionArchiveOperations)
    archives.archive.side_effect = RuntimeError("Postcommit archive fault")
    config = Mock(spec=Config)
    config.openai_responses_websocket_enabled = False
    entered = asyncio.Event() if deadline_seconds is not None else None
    release = asyncio.Event() if deadline_seconds is not None else None
    if deadline_seconds is not None:
        deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=deadline_seconds
        )
        async with manager() as session:
            await session.write_session.execute(
                sa.update(RDBMemoryExecution)
                .where(RDBMemoryExecution.session_id == principal.owner.session_id)
                .values(deadline_at=deadline)
            )
        binding = await executions.load_binding(principal.owner.session_id)
        assert binding is not None
        principal = dataclasses.replace(principal, binding=binding)
    executor = _ScriptedExecutor(
        executions,
        SessionExecutionFileRepository(manager),
        context,
        _repository(manager, _metadata()),
        require_instance(
            Mock(spec=EngineModelReadRepository), EngineModelReadRepository
        ),
        require_instance(
            Mock(spec=EngineRuntimeTokenResolver), EngineRuntimeTokenResolver
        ),
        require_instance(Mock(spec=ModelMetadataService), ModelMetadataService),
        require_instance(Mock(spec=ModelSDKFactories), ModelSDKFactories),
        make_test_model_stream_watchdog(),
        require_instance(config, Config),
        require_instance(lifecycle, SessionLifecycleService),
        require_instance(archives, SessionArchiveOperations),
        [
            [
                _call(
                    "write",
                    "write",
                    {
                        "path": "azents://execution/result.md",
                        "content": "# Current result",
                        "overwrite": False,
                    },
                ),
                _call(
                    "submit_memory",
                    "accepted",
                    {"path": "azents://execution/result.md"},
                ),
            ]
        ],
        [1] if quotas else [],
        [],
        entered,
        release,
        block_after_turns,
    )
    if quotas or block_after_turns:
        executor.script.insert(
            0,
            [
                _call(
                    "write",
                    "partial-draft",
                    {
                        "path": "azents://execution/unfinished.md",
                        "content": (
                            "Former host unfinished prose must never be replayed."
                        ),
                        "overwrite": False,
                    },
                )
            ],
        )
    return _ExecutorFixture(executor, principal)


@pytest.mark.parametrize("wake_failure", [False, True])
async def test_executor_quota_handoff_uses_clean_session_and_inherited_lifetime(
    rdb_session_manager: SessionManager[WriteSession],
    caplog: pytest.LogCaptureFixture,
    wake_failure: bool,
) -> None:
    executor, principal = await _executor(
        rdb_session_manager, quotas=True, deadline_seconds=None, block_after_turns=0
    )
    frozen = await executor.models.begin(principal)
    lifecycle = require_instance(executor.lifecycle, AsyncMock)
    if wake_failure:
        lifecycle.send_session_wake_up.side_effect = RuntimeError(
            "Synthetic postcommit wake fault"
        )
    result = await executor.execute(
        principal.binding,
        owner_generation=principal.owner.owner_generation,
        shutdown_event=asyncio.Event(),
        stop_controller=RunStopController(),
        check_stop=_never_stop,
        drain_stop_signals=lambda: None,
    )
    assert result.terminal_run_status is AgentRunStatus.FAILED
    assert len(executor.host_models) == 1
    wake = lifecycle.send_session_wake_up.call_args.args[0]
    assert isinstance(wake, SessionWakeUp)
    assert wake.session_id != principal.owner.session_id
    replacement = await executor.executions.load_binding(wake.session_id)
    assert replacement is not None and replacement.started_turns == 2
    assert replacement.deadline_at == principal.binding.deadline_at
    assert (
        "Former host unfinished prose" in (executor.host_models[0].prepared_inputs[-1])
    )
    if wake_failure:
        assert "candidate wake-up follow-up failed" in caplog.text
    async with rdb_session_manager() as session:
        pending = await session.read_session.scalar(
            sa.select(RDBAgentRun).where(RDBAgentRun.session_id == wake.session_id)
        )
        assert pending is not None and pending.status is AgentRunStatus.PENDING
        assert pending.model_operation_state is not None
        operation = ModelOperationState.model_validate(
            pending.model_operation_state
        ).foreground
        assert operation is not None and operation.operation_id == frozen.operation_id
        assert operation.current_candidate.model_selection.model_identifier == (
            "lightweight-second"
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBEvent)
                .where(RDBEvent.session_id == replacement.session_id)
            )
            == 0
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBSessionExecutionFile)
                .where(RDBSessionExecutionFile.session_id == replacement.session_id)
            )
            == 0
        )
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, replacement.session_id
        )
    recovered = await executor.executions.recover_worker_execution(
        replacement, SessionExecutionOwner(replacement.session_id, generation)
    )
    assert recovered == replacement
    result = await executor.execute(
        recovered,
        owner_generation=generation,
        shutdown_event=asyncio.Event(),
        stop_controller=RunStopController(),
        check_stop=_never_stop,
        drain_stop_signals=lambda: None,
    )
    assert result.terminal_run_status is AgentRunStatus.COMPLETED
    assert len(executor.host_models) == 2
    assert all(model.closed for model in executor.host_models)
    assert [model.selection.model_identifier for model in executor.host_models] == [
        "lightweight-first",
        "lightweight-second",
    ]
    final = await executor.executions.load_binding(replacement.session_id)
    assert final is not None and final.started_turns == 3 and final.accepted is not None
    assert final.deadline_at == principal.binding.deadline_at
    assert all(
        "Former host unfinished prose" not in request
        for request in executor.host_models[1].prepared_inputs
    )
    assert "archive follow-up failed" in caplog.text
    assert not executor.script


async def test_executor_absolute_deadline_cancels_blocked_model_without_acceptance(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    executor, principal = await _executor(
        rdb_session_manager, quotas=False, deadline_seconds=2, block_after_turns=0
    )
    task = asyncio.create_task(
        executor.execute(
            principal.binding,
            owner_generation=principal.owner.owner_generation,
            shutdown_event=asyncio.Event(),
            stop_controller=RunStopController(),
            check_stop=_never_stop,
            drain_stop_signals=lambda: None,
        )
    )
    assert executor.entered is not None
    async with asyncio.timeout(6):
        await executor.entered.wait()
        with pytest.raises(TimeoutError):
            await task
    final = await executor.executions.load_binding(principal.owner.session_id)
    assert final is not None and final.accepted is None and final.started_turns == 1
    assert executor.host_models[0].closed
    assert await executor.executions.current_result(final.unit) is None
    assert len(executor.script) == 1


@pytest.mark.parametrize("preceding_quota", [False, True])
async def test_shutdown_timeout_replacement_worker_keeps_lifetime_and_clean_inputs(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    preceding_quota: bool,
) -> None:
    """Actual supervisor timeout leaves the admission for a clean Worker takeover."""
    monkeypatch.setattr(
        "azents.worker.run.memory_execution.SHUTDOWN_COMPLETION_TIMEOUT", 0.01
    )
    executor, principal = await _executor(
        rdb_session_manager,
        quotas=preceding_quota,
        deadline_seconds=120,
        block_after_turns=1,
    )
    if preceding_quota:
        quota_result = await executor.execute(
            principal.binding,
            owner_generation=principal.owner.owner_generation,
            shutdown_event=asyncio.Event(),
            stop_controller=RunStopController(),
            check_stop=_never_stop,
            drain_stop_signals=lambda: None,
        )
        assert quota_result.terminal_run_status is AgentRunStatus.FAILED
        lifecycle = require_instance(executor.lifecycle, AsyncMock)
        wake = lifecycle.send_session_wake_up.call_args.args[0]
        assert isinstance(wake, SessionWakeUp)
        binding = await executor.executions.load_binding(wake.session_id)
        assert binding is not None
        async with rdb_session_manager() as session:
            generation = (
                await SessionExecutionRecordRepository().claim_owner_generation(
                    session, binding.session_id
                )
            )
        owner = SessionExecutionOwner(binding.session_id, generation)
        recovered = await executor.executions.recover_worker_execution(binding, owner)
        assert recovered == binding
        principal = await executor.executions.open_run(recovered, owner)
        executor.script.insert(
            0,
            [
                _call(
                    "write",
                    "candidate-partial-draft",
                    {
                        "path": "azents://execution/candidate-unfinished.md",
                        "content": (
                            "Former host unfinished prose from the quota candidate."
                        ),
                        "overwrite": False,
                    },
                )
            ],
        )
    frozen = await executor.models.begin(principal)
    assert frozen.cursor == (1 if preceding_quota else 0)
    shutdown = asyncio.Event()
    controller = RunStopController()
    task = asyncio.create_task(
        executor.execute(
            principal.binding,
            owner_generation=principal.owner.owner_generation,
            shutdown_event=shutdown,
            stop_controller=controller,
            check_stop=_never_stop,
            drain_stop_signals=lambda: None,
        )
    )
    assert executor.entered is not None and executor.release is not None
    async with asyncio.timeout(6):
        await executor.entered.wait()
        shutdown.set()
        result = await task
    assert controller.handover_stop_requested and not controller.user_stop_requested
    assert not result.terminal_event_observed and result.terminal_run_status is None
    assert "Engine task timed out after shutdown" in caplog.text
    assert executor.host_models[0].closed
    retained = await executor.executions.load_binding(principal.owner.session_id)
    assert retained is not None and retained.started_turns == (
        4 if preceding_quota else 2
    )
    assert retained.deadline_at == principal.binding.deadline_at
    async with rdb_session_manager() as session:
        unit = await session.read_session.get(RDBMemoryUnit, retained.unit_id)
        run = await session.read_session.get(RDBAgentRun, principal.run_id)
        current = await session.read_session.get(
            RDBAgentSession, principal.owner.session_id
        )
        assert unit is not None and unit.active_session_id == retained.session_id
        assert run is not None and run.status is AgentRunStatus.RUNNING
        assert current is not None and current.run_state is AgentSessionRunState.RUNNING
        agent = await session.write_session.get(
            RDBAgent, principal.binding.unit.agent_id
        )
        assert agent is not None
        integration_id = (
            frozen.current_candidate.model_selection.llm_provider_integration_id
        )
        changed = make_test_model_selection_dict(
            integration_id=integration_id,
            model_identifier="policy-changed-after-shutdown",
        )
        agent.model_selection = changed
        agent.lightweight_model_selection = changed
        agent.selectable_model_options = make_test_selectable_model_option_dicts(
            model_selection=changed, lightweight_model_selection=changed
        )
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, retained.session_id
        )
    replacement = await executor.executions.recover_worker_execution(
        retained, SessionExecutionOwner(retained.session_id, generation)
    )
    assert replacement is not None and replacement.session_id != retained.session_id
    assert replacement.deadline_at == retained.deadline_at
    assert replacement.started_turns == retained.started_turns
    with pytest.raises(MemoryExecutionAuthorityError):
        await executor.executions.authorize_execution(principal)
    async with rdb_session_manager() as session:
        pending = await session.read_session.scalar(
            sa.select(RDBAgentRun).where(
                RDBAgentRun.session_id == replacement.session_id
            )
        )
        assert pending is not None and pending.status is AgentRunStatus.PENDING
        assert pending.model_operation_state is not None
        transferred = ModelOperationState.model_validate(pending.model_operation_state)
        assert transferred.compaction is None
        operation = transferred.foreground
        assert operation is not None and operation.operation_id == frozen.operation_id
        assert operation.cursor == frozen.cursor
        assert [item.model_selection for item in operation.candidates] == [
            item.model_selection for item in frozen.candidates
        ]
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBEvent)
                .where(RDBEvent.session_id == replacement.session_id)
            )
            == 0
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBSessionExecutionFile)
                .where(RDBSessionExecutionFile.session_id == replacement.session_id)
            )
            == 0
        )
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, replacement.session_id
        )
    executor.release.set()
    result = await executor.execute(
        replacement,
        owner_generation=generation,
        shutdown_event=asyncio.Event(),
        stop_controller=RunStopController(),
        check_stop=_never_stop,
        drain_stop_signals=lambda: None,
    )
    assert result.terminal_run_status is AgentRunStatus.COMPLETED
    assert len(executor.host_models) == (3 if preceding_quota else 2)
    assert all(model.closed for model in executor.host_models)
    final = await executor.executions.load_binding(replacement.session_id)
    assert final is not None and final.accepted is not None
    assert final.started_turns == (5 if preceding_quota else 3)
    assert final.deadline_at == retained.deadline_at
    assert (
        executor.host_models[-1].selection == frozen.current_candidate.model_selection
    )
    assert all(
        "Former host unfinished prose" not in request
        for request in executor.host_models[-1].prepared_inputs
    )


async def test_explicit_user_stop_terminalizes_instead_of_retaining_takeover(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    executor, principal = await _executor(
        rdb_session_manager, quotas=False, deadline_seconds=120, block_after_turns=1
    )
    controller = RunStopController()
    task = asyncio.create_task(
        executor.execute(
            principal.binding,
            owner_generation=principal.owner.owner_generation,
            shutdown_event=asyncio.Event(),
            stop_controller=controller,
            check_stop=_never_stop,
            drain_stop_signals=lambda: None,
        )
    )
    assert executor.entered is not None
    async with asyncio.timeout(6):
        await executor.entered.wait()
        controller.request_user_stop()
        result = await task
    assert result.terminal_run_status is AgentRunStatus.CANCELLED
    async with rdb_session_manager() as session:
        unit = await session.read_session.get(RDBMemoryUnit, principal.binding.unit_id)
        run = await session.read_session.get(RDBAgentRun, principal.run_id)
        assert unit is not None and unit.active_session_id is None
        assert run is not None and run.status is AgentRunStatus.CANCELLED
    assert executor.host_models[0].closed


def test_memory_executor_common_dependency_graph_is_valid() -> None:
    def endpoint(
        executor: Annotated[MemoryRunExecutor, Depends(MemoryRunExecutor)],
    ) -> None:
        del executor

    assert get_dependant(path="/", call=endpoint).dependencies
