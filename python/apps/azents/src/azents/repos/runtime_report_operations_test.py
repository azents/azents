"""PostgreSQL report atomicity, normal stale commits and closed effect boundaries."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal, NamedTuple

import pytest
import sqlalchemy as sa
from azents_runtime_control.provider import (
    RuntimeProviderObservedState as SharedProviderState,
)
from azents_runtime_control.provider import RuntimeProviderReport
from azents_runtime_control.runner import RunnerStateReport
from azents_runtime_control.runner import RuntimeRunnerState as SharedRunnerState
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationStateStatus,
)
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationState
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeFailurePatch
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationDesiredStateWrite,
    RuntimeConfigurationState,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_report_data import ProviderReportInput, RunnerReportInput
from azents.repos.runtime_report_operations import RuntimeReportOperationRepository
from azents.runtime.control_protocol.grpc.state_sinks import (
    RuntimeProviderReportRepositorySink,
    RuntimeRunnerStateRepositorySink,
)
from azents.runtime.control_protocol.grpc.state_sinks_test import _create_runtime
from azents.runtime.control_server import (
    _RuntimeWebRunnerGenerationGate,
    _RuntimeWebRunnerStateSink,
)

_NOW = datetime(2026, 10, 2, tzinfo=UTC)
_MISSING = "0" * 32
_Stage = Literal[
    "provider_evidence",
    "runner_evidence",
    "observed",
    "connected",
    "runner",
    "clear",
    "terminal",
    "rearm",
]


class _InjectedWriteError(ValueError):
    """A deliberate failure after a genuine query has flushed its writes."""


@dataclasses.dataclass
class _Probe:
    stage: _Stage | None
    cancel: bool
    calls: list[str] = dataclasses.field(default_factory=list)
    promoted: bool = False

    def after(self, stage: _Stage, result: object) -> None:
        self.calls.append(stage)
        if self.stage != stage:
            return
        assert result is not None, "The fault must follow an actual successful write."
        if self.cancel:
            raise asyncio.CancelledError()
        raise _InjectedWriteError(stage)


class _RuntimeQueries(AgentRuntimeRepository):
    """Inject faults after, rather than instead of, actual PostgreSQL writes."""

    def __init__(self, probe: _Probe) -> None:
        self.probe = probe

    async def get_by_id(
        self, session: AsyncSession, runtime_id: str
    ) -> AgentRuntime | None:
        self.probe.calls.append("get")
        return await super().get_by_id(session, runtime_id)

    async def provider_report_matches_binding(
        self, session: AsyncSession, *, runtime_id: str, provider_logical_id: str
    ) -> bool:
        self.probe.calls.append("binding")
        return await super().provider_report_matches_binding(
            session, runtime_id=runtime_id, provider_logical_id=provider_logical_id
        )

    async def record_provider_observed_state(
        self,
        session: AsyncSession,
        runtime_id: str,
        observed_state: RuntimeProviderObservedState,
        provider_generation: int,
        observed_generation: int,
        *,
        failure: AgentRuntimeFailurePatch | None = None,
        clear_failure: bool = False,
    ) -> AgentRuntime | None:
        result = await super().record_provider_observed_state(
            session,
            runtime_id,
            observed_state,
            provider_generation,
            observed_generation,
            failure=failure,
            clear_failure=clear_failure,
        )
        self.probe.after("observed", result)
        return result

    async def record_provider_connection_state(
        self,
        session: AsyncSession,
        runtime_id: str,
        connection_state: RuntimeProviderConnectionState,
    ) -> AgentRuntime | None:
        result = await super().record_provider_connection_state(
            session, runtime_id, connection_state
        )
        self.probe.after("connected", result)
        return result

    async def record_runner_state(
        self,
        session: AsyncSession,
        runtime_id: str,
        runner_state: RuntimeRunnerState,
        runner_generation: int,
        *,
        expected_desired_generation: int,
        workspace_path: str | None,
        failure: AgentRuntimeFailurePatch | None = None,
    ) -> AgentRuntime | None:
        result = await super().record_runner_state(
            session,
            runtime_id,
            runner_state,
            runner_generation,
            expected_desired_generation=expected_desired_generation,
            workspace_path=workspace_path,
            failure=failure,
        )
        if result is not None:
            assert result.workspace_path == workspace_path
        self.probe.after("runner", result)
        return result

    async def clear_current_generation_failure(
        self, session: AsyncSession, runtime_id: str
    ) -> AgentRuntime | None:
        result = await super().clear_current_generation_failure(session, runtime_id)
        if result is not None:
            assert result.failure_code is None
        self.probe.after("clear", result)
        return result

    async def record_terminal_delete_acknowledgement(
        self,
        session: AsyncSession,
        runtime_id: str,
        *,
        provider_generation: int,
        acknowledged_generation: int,
    ) -> AgentRuntime | None:
        result = await super().record_terminal_delete_acknowledgement(
            session,
            runtime_id,
            provider_generation=provider_generation,
            acknowledged_generation=acknowledged_generation,
        )
        if result is not None:
            assert result.workspace_path is None
            assert result.runner_state is RuntimeRunnerState.DISCONNECTED
            assert result.failure_code is None
            assert result.terminal_delete_acknowledged_at is not None
        self.probe.after("terminal", result)
        return result

    async def complete_restart_handoff(
        self,
        session: AsyncSession,
        runtime_id: str,
        *,
        provider_generation: int,
        desired_generation: int,
    ) -> AgentRuntime | None:
        result = await super().complete_restart_handoff(
            session,
            runtime_id,
            provider_generation=provider_generation,
            desired_generation=desired_generation,
        )
        if result is not None:
            assert result.last_lifecycle_command is RuntimeLifecycleCommandType.START
            assert result.last_lifecycle_dispatch_generation == desired_generation - 1
        self.probe.after("rearm", result)
        return result


class _ProfileQueries(RuntimeProfileRepository):
    """Retain real evidence validation, locking and promotion before each fault."""

    def __init__(self, probe: _Probe) -> None:
        self.probe = probe

    async def record_provider_configuration_evidence(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
        acknowledged_at: datetime,
    ) -> RuntimeConfigurationState | None:
        result = await super().record_provider_configuration_evidence(
            session,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
            acknowledged_at=acknowledged_at,
        )
        if result is not None:
            assert result.desired.provider_reported_digest == evidence.digest
            self.probe.promoted = result.applied is not None
        self.probe.after("provider_evidence", result)
        return result

    async def record_runner_configuration_evidence(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
        observed_at: datetime,
    ) -> RuntimeConfigurationState | None:
        result = await super().record_runner_configuration_evidence(
            session,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
            observed_at=observed_at,
        )
        if result is not None:
            assert result.desired.runner_reported_digest == evidence.digest
            self.probe.promoted = result.applied is not None
        self.probe.after("runner_evidence", result)
        return result

    async def configuration_evidence_matches_current(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
    ) -> bool:
        self.probe.calls.append("current")
        return await super().configuration_evidence_matches_current(
            session, runtime_id=runtime_id, provider_id=provider_id, evidence=evidence
        )

    async def configuration_evidence_matches_applied(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
    ) -> bool:
        self.probe.calls.append("applied")
        return await super().configuration_evidence_matches_applied(
            session, runtime_id=runtime_id, provider_id=provider_id, evidence=evidence
        )


class _Boundary:
    """Observe real completed managers and the transaction state at external calls."""

    def __init__(self, manager: SessionManager[AsyncSession]) -> None:
        self.manager = manager
        self.opened: list[AsyncSession] = []
        self.active: list[AsyncSession] = []

    @asynccontextmanager
    async def session_manager(self) -> AsyncIterator[AsyncSession]:
        async with self.manager() as session:
            self.opened.append(session)
            self.active.append(session)
            try:
                yield session
            finally:
                self.active.remove(session)

    def closed(self) -> None:
        assert not self.active
        assert all(not session.in_transaction() for session in self.opened)


class _Snapshot(NamedTuple):
    runtime: AgentRuntime
    state: RuntimeConfigurationState


class _Fixture(NamedTuple):
    runtime_id: str
    provider_id: str
    evidence: RuntimeConfigurationEvidence
    operations: RuntimeReportOperationRepository
    boundary: _Boundary
    probe: _Probe


async def _fixture(
    manager: SessionManager[AsyncSession], *, stage: _Stage | None, cancel: bool
) -> _Fixture:
    queries = AgentRuntimeRepository()
    profiles = RuntimeProfileRepository()
    async with manager() as session:
        runtime_id = await _create_runtime(session, "report-operations")
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .values(desired_state=RuntimeDesiredState.RUNNING)
        )
        runtime = await queries.get_by_id(session, runtime_id)
        assert runtime is not None and runtime.runtime_provider_resource_id is not None
        provider_id = runtime.runtime_provider_resource_id
        document = RuntimeConfigurationDocument(
            schema_version=1,
            source_trace={},
            provider_id=provider_id,
            provider_capability_revision_id=None,
            infrastructure_profile_id="a" * 32,
            infrastructure_profile_version=1,
            workspace_runtime_profile_id="b" * 32,
            workspace_runtime_profile_version=1,
            agent_selection_version=1,
            required_capabilities=(),
            missing_capabilities=(),
            resolved_configuration={"schema_version": 1},
        )
        state = await profiles.overwrite_desired_configuration_state(
            session,
            write=RuntimeConfigurationDesiredStateWrite(
                runtime_id=runtime_id,
                status=RuntimeConfigurationStateStatus.READY,
                target_generation=runtime.desired_generation,
                digest="d" * 64,
                document=document,
                reason_code=None,
            ),
        )
        assert state is not None and state.desired.digest is not None
    probe = _Probe(stage=stage, cancel=cancel)
    boundary = _Boundary(manager)
    return _Fixture(
        runtime_id=runtime_id,
        provider_id=provider_id,
        evidence=RuntimeConfigurationEvidence(
            configuration_sequence=state.desired.sequence,
            digest=state.desired.digest,
            desired_generation=state.desired.target_generation,
        ),
        operations=RuntimeReportOperationRepository(
            session_manager=boundary.session_manager,
            runtime_repository=_RuntimeQueries(probe),
            profile_repository=_ProfileQueries(probe),
        ),
        boundary=boundary,
        probe=probe,
    )


async def _snapshot(
    manager: SessionManager[AsyncSession], fixture: _Fixture
) -> _Snapshot:
    async with manager() as session:
        runtime = await AgentRuntimeRepository().get_by_id(session, fixture.runtime_id)
        state = await RuntimeProfileRepository().get_configuration_state(
            session, runtime_id=fixture.runtime_id
        )
        assert runtime is not None and state is not None
        return _Snapshot(runtime, state)


def _provider(fixture: _Fixture) -> ProviderReportInput:
    return ProviderReportInput(
        runtime_id=fixture.runtime_id,
        provider_id="system-kubernetes",
        provider_generation=1,
        observed_state=RuntimeProviderObservedState.RUNNING,
        observed_desired_generation=fixture.evidence.desired_generation,
        provider_runtime_id="report-test-runtime",
        terminal_delete_acknowledged=False,
        runtime_configuration=fixture.evidence,
        reported_at=_NOW,
    )


def _runner(fixture: _Fixture) -> RunnerReportInput:
    return RunnerReportInput(
        runtime_id=fixture.runtime_id,
        runner_generation=1,
        runner_state=RuntimeRunnerState.READY,
        runner_stream_closed=False,
        unsupported_runner_state=None,
        workspace_path=" /runtime/home/../agent ",
        runtime_configuration=fixture.evidence,
        reported_at=_NOW,
    )


async def _ack(
    manager: SessionManager[AsyncSession],
    fixture: _Fixture,
    *,
    provider: bool,
    runner: bool,
    failure_code: str | None,
) -> None:
    async with manager() as session:
        profiles = RuntimeProfileRepository()
        if provider:
            assert await profiles.record_provider_configuration_evidence(
                session,
                runtime_id=fixture.runtime_id,
                provider_id=fixture.provider_id,
                evidence=fixture.evidence,
                acknowledged_at=_NOW,
            )
        if runner:
            assert await profiles.record_runner_configuration_evidence(
                session,
                runtime_id=fixture.runtime_id,
                provider_id=fixture.provider_id,
                evidence=fixture.evidence,
                observed_at=_NOW,
            )
        if failure_code is not None:
            assert await AgentRuntimeRepository().record_runtime_failure(
                session,
                fixture.runtime_id,
                AgentRuntimeFailurePatch(
                    generation=fixture.evidence.desired_generation,
                    code=failure_code,
                    message="Existing failure",
                ),
            )


@pytest.mark.parametrize("stage", ["provider_evidence", "observed", "connected"])
@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
async def test_provider_evidence_promotion_observation_connection_roll_back(
    rdb_session_manager: SessionManager[AsyncSession], stage: _Stage, cancel: bool
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=stage, cancel=cancel)
    await _ack(
        rdb_session_manager,
        fixture,
        provider=False,
        runner=True,
        failure_code="START_TIMEOUT",
    )
    before = await _snapshot(rdb_session_manager, fixture)
    with pytest.raises(asyncio.CancelledError if cancel else _InjectedWriteError):
        await fixture.operations.record_provider_report(
            _provider(fixture), configuration_acknowledgement_allowed=True
        )
    fixture.boundary.closed()
    assert fixture.probe.promoted
    assert stage in fixture.probe.calls
    assert await _snapshot(rdb_session_manager, fixture) == before


@pytest.mark.parametrize("stage", ["runner_evidence", "runner", "clear"])
@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
async def test_runner_evidence_promotion_path_failure_clear_roll_back(
    rdb_session_manager: SessionManager[AsyncSession], stage: _Stage, cancel: bool
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=stage, cancel=cancel)
    await _ack(
        rdb_session_manager,
        fixture,
        provider=True,
        runner=False,
        failure_code="RUNNER_OLD",
    )
    before = await _snapshot(rdb_session_manager, fixture)
    with pytest.raises(asyncio.CancelledError if cancel else _InjectedWriteError):
        await fixture.operations.record_runner_state(_runner(fixture))
    fixture.boundary.closed()
    assert fixture.probe.promoted
    assert stage in fixture.probe.calls
    assert await _snapshot(rdb_session_manager, fixture) == before


@pytest.mark.parametrize("stage", ["terminal", "connected"])
@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
async def test_terminal_ack_path_state_failure_and_connection_roll_back(
    rdb_session_manager: SessionManager[AsyncSession], stage: _Stage, cancel: bool
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=stage, cancel=cancel)
    async with rdb_session_manager() as session:
        requested = await AgentRuntimeRepository().request_terminal_delete(
            session, fixture.runtime_id
        )
        assert requested is not None
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == fixture.runtime_id)
            .values(
                workspace_path="/runtime/old",
                runner_state=RuntimeRunnerState.READY,
                failure_generation=requested.desired_generation,
                failure_code="RUNNER_OLD",
                failure_message="Existing failure",
            )
        )
    before = await _snapshot(rdb_session_manager, fixture)
    report = dataclasses.replace(
        _provider(fixture),
        observed_state=RuntimeProviderObservedState.STOPPED,
        provider_runtime_id=None,
        observed_desired_generation=requested.desired_generation,
        terminal_delete_acknowledged=True,
    )
    with pytest.raises(asyncio.CancelledError if cancel else _InjectedWriteError):
        await fixture.operations.record_provider_report(
            report, configuration_acknowledgement_allowed=True
        )
    fixture.boundary.closed()
    assert "terminal" in fixture.probe.calls
    assert "provider_evidence" not in fixture.probe.calls
    assert await _snapshot(rdb_session_manager, fixture) == before


@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
async def test_restart_rearm_rolls_back_without_undoing_completed_report(
    rdb_session_manager: SessionManager[AsyncSession], cancel: bool
) -> None:
    fixture = await _fixture(rdb_session_manager, stage="rearm", cancel=cancel)
    async with rdb_session_manager() as session:
        queries = AgentRuntimeRepository()
        command = await queries.set_desired_state(
            session,
            fixture.runtime_id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await queries.mark_lifecycle_dispatched(
            session, fixture.runtime_id, command.desired_generation
        )
        await queries.record_runtime_failure(
            session,
            fixture.runtime_id,
            AgentRuntimeFailurePatch(
                generation=command.desired_generation,
                code="PROVIDER_DISPATCH_FAILED",
                message="Existing failure",
            ),
        )
    report = dataclasses.replace(
        _provider(fixture),
        observed_state=RuntimeProviderObservedState.STOPPED,
        observed_desired_generation=command.desired_generation,
        provider_runtime_id=None,
    )
    await fixture.operations.record_provider_report(
        report, configuration_acknowledgement_allowed=False
    )
    fixture.boundary.closed()
    before = await _snapshot(rdb_session_manager, fixture)
    assert (
        before.runtime.provider_observed_state is RuntimeProviderObservedState.STOPPED
    )
    assert (
        before.runtime.provider_connection_state
        is RuntimeProviderConnectionState.CONNECTED
    )
    fixture.probe.calls.clear()
    with pytest.raises(asyncio.CancelledError if cancel else _InjectedWriteError):
        await fixture.operations.complete_restart_handoff(report)
    fixture.boundary.closed()
    assert fixture.probe.calls == ["binding", "rearm"]
    assert len(fixture.boundary.opened) == 2
    assert await _snapshot(rdb_session_manager, fixture) == before


@pytest.mark.parametrize("provider", [True, False], ids=["provider", "runner"])
async def test_normal_stale_cas_commits_already_reached_configuration_promotion(
    rdb_session_manager: SessionManager[AsyncSession], provider: bool
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await _ack(
        rdb_session_manager,
        fixture,
        provider=not provider,
        runner=provider,
        failure_code="RUNNER_OLD",
    )
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == fixture.runtime_id)
            .values(provider_generation=2 if provider else 0, runner_generation=2)
        )
    before = await _snapshot(rdb_session_manager, fixture)
    if provider:
        await fixture.operations.record_provider_report(
            _provider(fixture), configuration_acknowledgement_allowed=True
        )
        assert fixture.probe.calls == [
            "get",
            "binding",
            "provider_evidence",
            "observed",
        ]
    else:
        await fixture.operations.record_runner_state(_runner(fixture))
        assert fixture.probe.calls == ["get", "runner_evidence", "runner"]
    fixture.boundary.closed()
    after = await _snapshot(rdb_session_manager, fixture)
    assert after.runtime == before.runtime
    assert before.state.applied is None and after.state.applied is not None
    assert after.state.applied.sequence == fixture.evidence.configuration_sequence
    assert fixture.probe.promoted


async def test_provider_then_runner_keeps_query_order_and_detaches_results(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await fixture.operations.record_provider_report(
        _provider(fixture), configuration_acknowledgement_allowed=True
    )
    fixture.boundary.closed()
    assert fixture.probe.calls == [
        "get",
        "binding",
        "provider_evidence",
        "observed",
        "connected",
    ]
    await _ack(
        rdb_session_manager,
        fixture,
        provider=False,
        runner=False,
        failure_code="RUNNER_OLD",
    )
    fixture.probe.calls.clear()
    await fixture.operations.record_runner_state(_runner(fixture))
    fixture.boundary.closed()
    assert fixture.probe.calls == ["get", "runner_evidence", "runner", "clear"]
    after = await _snapshot(rdb_session_manager, fixture)
    assert after.runtime.workspace_path == "/runtime/agent"
    assert after.runtime.runner_state is RuntimeRunnerState.READY
    assert after.runtime.failure_code is None
    assert after.state.applied is not None


async def test_provider_missing_is_normal_runner_missing_and_binding_mismatch_raise(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await fixture.operations.record_provider_report(
        dataclasses.replace(_provider(fixture), runtime_id=_MISSING),
        configuration_acknowledgement_allowed=True,
    )
    fixture.boundary.closed()
    assert fixture.probe.calls == ["get"]
    with pytest.raises(ValueError, match="AgentRuntime not found"):
        await fixture.operations.record_runner_state(
            dataclasses.replace(_runner(fixture), runtime_id=_MISSING)
        )
    fixture.boundary.closed()
    before = await _snapshot(rdb_session_manager, fixture)
    with pytest.raises(ValueError, match="immutable Runtime Provider binding"):
        await fixture.operations.record_provider_report(
            dataclasses.replace(_provider(fixture), provider_id="another-provider"),
            configuration_acknowledgement_allowed=True,
        )
    fixture.boundary.closed()
    with pytest.raises(ValueError, match="immutable Runtime Provider binding"):
        await fixture.operations.complete_restart_handoff(
            dataclasses.replace(_provider(fixture), provider_id="another-provider")
        )
    fixture.boundary.closed()
    assert await _snapshot(rdb_session_manager, fixture) == before


@pytest.mark.parametrize("generation", [0, 2])
async def test_runner_previous_or_future_desired_generation_is_noop_before_evidence(
    rdb_session_manager: SessionManager[AsyncSession], generation: int
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == fixture.runtime_id)
            .values(desired_generation=1)
        )
    before = await _snapshot(rdb_session_manager, fixture)
    await fixture.operations.record_runner_state(
        dataclasses.replace(
            _runner(fixture),
            workspace_path="",
            runtime_configuration=dataclasses.replace(
                fixture.evidence, desired_generation=generation
            ),
        )
    )
    fixture.boundary.closed()
    assert fixture.probe.calls == ["get"]
    assert await _snapshot(rdb_session_manager, fixture) == before


async def test_stopped_streamclose_skips_path_and_configuration_before_generation_check(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == fixture.runtime_id)
            .values(desired_state=RuntimeDesiredState.STOPPED, workspace_path="/old")
        )
    await fixture.operations.record_runner_state(
        dataclasses.replace(
            _runner(fixture),
            runner_stream_closed=True,
            workspace_path="relative",
            unsupported_runner_state="stopping",
        )
    )
    fixture.boundary.closed()
    assert fixture.probe.calls == ["get", "runner"]
    after = await _snapshot(rdb_session_manager, fixture)
    assert after.runtime.runner_state is RuntimeRunnerState.DISCONNECTED
    assert after.runtime.workspace_path is None
    assert after.runtime.failure_code is None
    assert after.state.desired.runner_reported_digest is None


@pytest.mark.parametrize(
    ("path", "unsupported", "failure"),
    [
        ("", None, "RUNNER_WORKSPACE_PATH_MISSING"),
        ("relative/path", None, "RUNNER_WORKSPACE_PATH_INVALID"),
        ("/absolute", "stopping", "UNSUPPORTED_RUNNER_STATE"),
        ("", "stopping", "RUNNER_WORKSPACE_PATH_MISSING"),
    ],
)
async def test_path_and_unsupported_failures_still_commit_exact_configuration(
    rdb_session_manager: SessionManager[AsyncSession],
    path: str,
    unsupported: str | None,
    failure: str,
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await _ack(
        rdb_session_manager,
        fixture,
        provider=True,
        runner=False,
        failure_code=None,
    )
    await fixture.operations.record_runner_state(
        dataclasses.replace(
            _runner(fixture), workspace_path=path, unsupported_runner_state=unsupported
        )
    )
    fixture.boundary.closed()
    after = await _snapshot(rdb_session_manager, fixture)
    assert after.runtime.failure_code == failure
    assert after.runtime.runner_state is RuntimeRunnerState.FAILED
    assert after.state.applied is not None
    assert "clear" not in fixture.probe.calls


async def test_registration_accepts_current_or_retained_applied_without_fallback(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    assert await fixture.operations.validate_runner_registration(
        runtime_id=fixture.runtime_id, evidence=fixture.evidence
    )
    fixture.boundary.closed()
    assert fixture.probe.calls == ["get", "current"]
    await _ack(
        rdb_session_manager,
        fixture,
        provider=True,
        runner=True,
        failure_code=None,
    )
    async with rdb_session_manager() as session:
        state = await RuntimeProfileRepository().overwrite_desired_configuration_state(
            session,
            write=RuntimeConfigurationDesiredStateWrite(
                runtime_id=fixture.runtime_id,
                status=RuntimeConfigurationStateStatus.BLOCKED,
                target_generation=fixture.evidence.desired_generation,
                digest=None,
                document=None,
                reason_code="source_missing",
            ),
        )
        assert state is not None and state.applied is not None
    fixture.probe.calls.clear()
    assert await fixture.operations.validate_runner_registration(
        runtime_id=fixture.runtime_id, evidence=fixture.evidence
    )
    fixture.boundary.closed()
    assert fixture.probe.calls == ["get", "current", "applied"]
    assert not await fixture.operations.validate_runner_registration(
        runtime_id=fixture.runtime_id,
        evidence=dataclasses.replace(fixture.evidence, digest="e" * 64),
    )
    fixture.boundary.closed()
    assert not await fixture.operations.validate_runner_registration(
        runtime_id=_MISSING, evidence=fixture.evidence
    )
    fixture.boundary.closed()


async def test_heartbeat_returns_provider_first_pending_evidence_until_runner_ack(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    assert (
        await fixture.operations.configuration_evidence_for_runner_heartbeat(
            runtime_id=fixture.runtime_id
        )
        is None
    )
    fixture.boundary.closed()
    await fixture.operations.record_provider_report(
        _provider(fixture), configuration_acknowledgement_allowed=True
    )
    fixture.boundary.closed()
    pending = await fixture.operations.configuration_evidence_for_runner_heartbeat(
        runtime_id=fixture.runtime_id
    )
    fixture.boundary.closed()
    assert pending == fixture.evidence
    await fixture.operations.record_runner_state(_runner(fixture))
    fixture.boundary.closed()
    assert (
        await fixture.operations.configuration_evidence_for_runner_heartbeat(
            runtime_id=fixture.runtime_id
        )
        is None
    )
    fixture.boundary.closed()
    assert (
        await fixture.operations.configuration_evidence_for_runner_heartbeat(
            runtime_id=_MISSING
        )
        is None
    )
    fixture.boundary.closed()


@pytest.mark.parametrize(
    "mutation",
    [
        "no_binding",
        "missing_state",
        "future_target",
        "provider_digest",
        "runner_digest",
    ],
)
async def test_heartbeat_rechecks_exact_target_and_ack_predicates(
    rdb_session_manager: SessionManager[AsyncSession], mutation: str
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await _ack(
        rdb_session_manager,
        fixture,
        provider=True,
        runner=False,
        failure_code=None,
    )
    async with rdb_session_manager() as session:
        if mutation == "no_binding":
            await session.execute(
                sa.update(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == fixture.runtime_id)
                .values(runtime_provider_resource_id=None)
            )
        elif mutation == "missing_state":
            await RuntimeProfileRepository().clear_configuration_state(
                session, runtime_id=fixture.runtime_id
            )
        elif mutation == "future_target":
            await session.execute(
                sa.update(RDBRuntimeConfigurationState)
                .where(RDBRuntimeConfigurationState.runtime_id == fixture.runtime_id)
                .values(desired_target_generation=1)
            )
        elif mutation == "provider_digest":
            await session.execute(
                sa.update(RDBRuntimeConfigurationState)
                .where(RDBRuntimeConfigurationState.runtime_id == fixture.runtime_id)
                .values(provider_reported_digest="e" * 64)
            )
        else:
            assert mutation == "runner_digest"
            await session.execute(
                sa.update(RDBRuntimeConfigurationState)
                .where(RDBRuntimeConfigurationState.runtime_id == fixture.runtime_id)
                .values(runner_reported_digest=fixture.evidence.digest)
            )
    assert (
        await fixture.operations.configuration_evidence_for_runner_heartbeat(
            runtime_id=fixture.runtime_id
        )
        is None
    )
    fixture.boundary.closed()


class _GenerationGate(_RuntimeWebRunnerGenerationGate):
    """Spy on the real post-delegate generation projection contract."""

    def __init__(self, boundary: _Boundary) -> None:
        self.boundary = boundary
        self.marked: list[int] = []

    async def mark(self, *, runtime_id: str, runner_generation: int) -> None:
        self.boundary.closed()
        self.marked.append(runner_generation)


def _shared_runner(fixture: _Fixture) -> RunnerStateReport:
    return RunnerStateReport(
        runtime_id=fixture.runtime_id,
        runner_id="runner-test",
        runner_generation=1,
        runner_state=SharedRunnerState.BUSY,
        capabilities=(),
        active_operation_ids=(),
        health="ok",
        diagnostic={},
        workspace_path="/runtime/agent",
        reported_at=_NOW,
        runtime_configuration=fixture.evidence,
    )


def _shared_provider(fixture: _Fixture) -> RuntimeProviderReport:
    return RuntimeProviderReport(
        runtime_id=fixture.runtime_id,
        provider_id="system-kubernetes",
        provider_generation=1,
        observed_state=SharedProviderState.RUNNING,
        observed_desired_generation=fixture.evidence.desired_generation,
        provider_runtime_id="report-test-runtime",
        reason="ready",
        diagnostic={},
        reported_at=_NOW,
        terminal_delete_acknowledged=False,
        runtime_configuration=fixture.evidence,
        reconciliation=None,
    )


@pytest.mark.parametrize("outcome", ["success", "noop", "error", "cancel"])
async def test_generation_gate_runs_only_after_completed_delegate(
    rdb_session_manager: SessionManager[AsyncSession], outcome: str
) -> None:
    fixture = await _fixture(
        rdb_session_manager,
        stage="runner" if outcome in {"error", "cancel"} else None,
        cancel=outcome == "cancel",
    )
    gate = _GenerationGate(fixture.boundary)
    wrapper = _RuntimeWebRunnerStateSink(
        delegate=RuntimeRunnerStateRepositorySink(repository=fixture.operations),
        generation_gate=gate,
    )
    report = _shared_runner(fixture)
    if outcome == "noop":
        report = dataclasses.replace(
            report,
            runtime_configuration=dataclasses.replace(
                fixture.evidence, desired_generation=1
            ),
        )
    if outcome in {"error", "cancel"}:
        with pytest.raises(
            asyncio.CancelledError if outcome == "cancel" else _InjectedWriteError
        ):
            await wrapper.record_runner_state(report)
        fixture.boundary.closed()
        assert gate.marked == []
    else:
        await wrapper.record_runner_state(report)
        fixture.boundary.closed()
        assert gate.marked == [1]
        if outcome == "success":
            snapshot = await _snapshot(rdb_session_manager, fixture)
            assert snapshot.runtime.runner_state is RuntimeRunnerState.READY


@pytest.mark.parametrize("outcome", ["success", "orphan", "error", "cancel"])
async def test_provider_publisher_observes_closed_success_noop_error_cancel(
    rdb_session_manager: SessionManager[AsyncSession], outcome: str
) -> None:
    fixture = await _fixture(
        rdb_session_manager,
        stage="connected" if outcome in {"error", "cancel"} else None,
        cancel=outcome == "cancel",
    )
    sink = RuntimeProviderReportRepositorySink(repository=fixture.operations)
    report = _shared_provider(fixture)
    if outcome == "orphan":
        report = dataclasses.replace(report, runtime_id=_MISSING)
    published: list[str] = []

    def publish(value: str) -> None:
        fixture.boundary.closed()
        published.append(value)

    try:
        await sink.record_provider_report(
            report, configuration_acknowledgement_allowed=True
        )
    except asyncio.CancelledError:
        assert outcome == "cancel"
        publish("cancel")
    except _InjectedWriteError:
        assert outcome == "error"
        publish("error")
    else:
        publish(outcome)
    assert published == [outcome]


@pytest.mark.parametrize("observed_generation", [0, 2], ids=["lower", "future"])
async def test_provider_observed_generation_keeps_existing_monotonic_predicate(
    rdb_session_manager: SessionManager[AsyncSession], observed_generation: int
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await _ack(
        rdb_session_manager, fixture, provider=False, runner=True, failure_code=None
    )
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == fixture.runtime_id)
            .values(provider_observed_generation=1)
        )
    before = await _snapshot(rdb_session_manager, fixture)
    await fixture.operations.record_provider_report(
        dataclasses.replace(
            _provider(fixture), observed_desired_generation=observed_generation
        ),
        configuration_acknowledgement_allowed=True,
    )
    fixture.boundary.closed()
    after = await _snapshot(rdb_session_manager, fixture)
    assert after.state.applied is not None
    if observed_generation == 0:
        assert after.runtime == before.runtime
        assert fixture.probe.calls == [
            "get",
            "binding",
            "provider_evidence",
            "observed",
        ]
    else:
        assert after.runtime.provider_observed_generation == observed_generation
        assert (
            after.runtime.provider_observed_state
            is RuntimeProviderObservedState.RUNNING
        )
        assert (
            after.runtime.provider_connection_state
            is RuntimeProviderConnectionState.CONNECTED
        )


@pytest.mark.parametrize("provider", [True, False], ids=["provider", "runner"])
@pytest.mark.parametrize("blocked", [True, False], ids=["blocked", "changed-ready"])
async def test_reports_accept_retained_applied_without_acknowledging_new_desired(
    rdb_session_manager: SessionManager[AsyncSession], provider: bool, blocked: bool
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await _ack(
        rdb_session_manager, fixture, provider=True, runner=True, failure_code=None
    )
    before = await _snapshot(rdb_session_manager, fixture)
    async with rdb_session_manager() as session:
        state = await RuntimeProfileRepository().overwrite_desired_configuration_state(
            session,
            write=RuntimeConfigurationDesiredStateWrite(
                runtime_id=fixture.runtime_id,
                status=(
                    RuntimeConfigurationStateStatus.BLOCKED
                    if blocked
                    else RuntimeConfigurationStateStatus.READY
                ),
                target_generation=fixture.evidence.desired_generation,
                digest=None if blocked else "e" * 64,
                document=None if blocked else before.state.desired.document,
                reason_code="source_missing" if blocked else None,
            ),
        )
        assert state is not None and state.applied is not None
    if provider:
        await fixture.operations.record_provider_report(
            _provider(fixture), configuration_acknowledgement_allowed=True
        )
    else:
        await fixture.operations.record_runner_state(_runner(fixture))
    fixture.boundary.closed()
    after = await _snapshot(rdb_session_manager, fixture)
    assert after.state.applied == before.state.applied
    assert after.state.desired.sequence > fixture.evidence.configuration_sequence
    assert after.state.desired.provider_reported_digest is None
    assert after.state.desired.runner_reported_digest is None
    assert after.runtime.failure_code is None
    assert "applied" in fixture.probe.calls
    if not provider:
        assert after.runtime.workspace_path == "/runtime/agent"


@pytest.mark.parametrize("provider", [True, False], ids=["provider", "runner"])
@pytest.mark.parametrize(
    "binding", [True, False], ids=["mismatched-evidence", "missing-binding"]
)
async def test_bad_evidence_or_missing_binding_commits_existing_failure_policy(
    rdb_session_manager: SessionManager[AsyncSession], provider: bool, binding: bool
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    if not binding:
        async with rdb_session_manager() as session:
            await session.execute(
                sa.update(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == fixture.runtime_id)
                .values(runtime_provider_resource_id=None)
            )
    evidence = dataclasses.replace(fixture.evidence, digest="e" * 64)
    if provider:
        await fixture.operations.record_provider_report(
            dataclasses.replace(_provider(fixture), runtime_configuration=evidence),
            configuration_acknowledgement_allowed=True,
        )
    else:
        await fixture.operations.record_runner_state(
            dataclasses.replace(_runner(fixture), runtime_configuration=evidence)
        )
    fixture.boundary.closed()
    after = await _snapshot(rdb_session_manager, fixture)
    source = "PROVIDER" if provider else "RUNNER"
    assert after.runtime.failure_code == (
        f"RUNTIME_CONFIGURATION_{source}_EVIDENCE_MISMATCH"
        if binding
        else "RUNTIME_CONFIGURATION_PROVIDER_BINDING_MISSING"
    )
    assert after.state.desired.provider_reported_digest is None
    assert after.state.desired.runner_reported_digest is None
    assert after.state.applied is None
    if not provider:
        assert after.runtime.runner_state is RuntimeRunnerState.FAILED


@pytest.mark.parametrize(
    ("state", "allowed"),
    [
        (RuntimeProviderObservedState.STARTING, True),
        (RuntimeProviderObservedState.RUNNING, False),
    ],
)
async def test_provider_non_ack_reports_keep_configuration_and_failure_scope(
    rdb_session_manager: SessionManager[AsyncSession],
    state: RuntimeProviderObservedState,
    allowed: bool,
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await _ack(
        rdb_session_manager,
        fixture,
        provider=False,
        runner=False,
        failure_code="RUNTIME_CONFIGURATION_PROVIDER_OLD",
    )
    before = await _snapshot(rdb_session_manager, fixture)
    await fixture.operations.record_provider_report(
        dataclasses.replace(_provider(fixture), observed_state=state),
        configuration_acknowledgement_allowed=allowed,
    )
    fixture.boundary.closed()
    after = await _snapshot(rdb_session_manager, fixture)
    assert after.state == before.state
    assert after.runtime.failure_code == before.runtime.failure_code
    assert fixture.probe.calls == ["get", "binding", "observed", "connected"]


@pytest.mark.parametrize(
    ("code", "cleared"),
    [
        ("RUNNER_OLD", True),
        ("RUNTIME_CONFIGURATION_RUNNER_OLD", True),
        ("PROVIDER_OLD", False),
        ("OTHER_FAILURE", False),
    ],
)
async def test_runner_failure_clear_keeps_original_code_eligibility(
    rdb_session_manager: SessionManager[AsyncSession], code: str, cleared: bool
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    await _ack(
        rdb_session_manager,
        fixture,
        provider=True,
        runner=False,
        failure_code=code,
    )
    await fixture.operations.record_runner_state(_runner(fixture))
    fixture.boundary.closed()
    after = await _snapshot(rdb_session_manager, fixture)
    assert after.runtime.failure_code == (None if cleared else code)
    assert ("clear" in fixture.probe.calls) == cleared


async def test_terminal_ack_second_report_is_normal_noop_without_configuration(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    async with rdb_session_manager() as session:
        requested = await AgentRuntimeRepository().request_terminal_delete(
            session, fixture.runtime_id
        )
        assert requested is not None
    report = dataclasses.replace(
        _provider(fixture),
        observed_state=RuntimeProviderObservedState.STOPPED,
        provider_runtime_id=None,
        observed_desired_generation=requested.desired_generation,
        terminal_delete_acknowledged=True,
    )
    await fixture.operations.record_provider_report(
        report, configuration_acknowledgement_allowed=True
    )
    fixture.boundary.closed()
    first = await _snapshot(rdb_session_manager, fixture)
    fixture.probe.calls.clear()
    await fixture.operations.record_provider_report(
        report, configuration_acknowledgement_allowed=True
    )
    fixture.boundary.closed()
    assert fixture.probe.calls == ["get", "binding", "terminal"]
    assert await _snapshot(rdb_session_manager, fixture) == first


@pytest.mark.parametrize(
    "fence", ["provider-generation", "desired-generation", "terminal"]
)
async def test_restart_rearm_retains_exact_conditional_and_idempotent_outcomes(
    rdb_session_manager: SessionManager[AsyncSession], fence: str
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    async with rdb_session_manager() as session:
        command = await AgentRuntimeRepository().set_desired_state(
            session,
            fixture.runtime_id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
    report = dataclasses.replace(
        _provider(fixture),
        observed_state=RuntimeProviderObservedState.STOPPED,
        observed_desired_generation=command.desired_generation,
        provider_runtime_id=None,
    )
    await fixture.operations.record_provider_report(
        report, configuration_acknowledgement_allowed=False
    )
    fixture.boundary.closed()
    before = await _snapshot(rdb_session_manager, fixture)
    stale = dataclasses.replace(
        report,
        provider_generation=0 if fence == "provider-generation" else 1,
        observed_desired_generation=(
            0 if fence == "desired-generation" else command.desired_generation
        ),
    )
    if fence == "terminal":
        async with rdb_session_manager() as session:
            await AgentRuntimeRepository().request_terminal_delete(
                session, fixture.runtime_id
            )
        before = await _snapshot(rdb_session_manager, fixture)
    assert not await fixture.operations.complete_restart_handoff(stale)
    fixture.boundary.closed()
    assert await _snapshot(rdb_session_manager, fixture) == before
    if fence != "terminal":
        assert await fixture.operations.complete_restart_handoff(report)
        fixture.boundary.closed()
        after = await _snapshot(rdb_session_manager, fixture)
        assert not await fixture.operations.complete_restart_handoff(report)
        fixture.boundary.closed()
        assert await _snapshot(rdb_session_manager, fixture) == after
