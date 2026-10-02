"""Actual PostgreSQL reconciliation groups, suppression and closed-effect proofs."""

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
import sqlalchemy as sa
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.runtime_profile import RuntimeConfigurationStateStatus
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationState
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationDesiredStateWrite,
    RuntimeConfigurationState,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_reconciliation import RuntimeReconciliationOperationRepository
from azents.repos.runtime_reconciliation_data import RuntimeObserveRepairInput
from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolRouteUnavailable,
    RuntimeProtocolStaleGeneration,
    RuntimeProviderCommand,
)
from azents.runtime.control_protocol.reconciler import (
    RuntimeLifecycleDispatchConfig,
    RuntimeLifecycleReconciler,
)
from azents.runtime.control_protocol.reconciler_test import (
    SessionBoundaryProbe,
    _create_agent,
    _dispatch_repository,
    _network_policy_drift_report,
    _prepare_start_dispatch,
    _provider_registration,
    _runner_credential_verifier,
)
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.testing.runtime_coordination import FakeRuntimeControlProtocolService


@dataclasses.dataclass(frozen=True)
class QueryCall:
    operation: str
    session: AsyncSession
    limit: int | None


class ObservedRuntimes(AgentRuntimeRepository):
    """Call genuine primitives on one observed Session, then inject a fault."""

    def __init__(
        self,
        probe: SessionBoundaryProbe,
        stage: str | None,
        error: BaseException | None,
    ) -> None:
        self.probe = probe
        self.stage = stage
        self.error = error
        self.calls: list[QueryCall] = []

    def point(self, operation: str, session: AsyncSession, limit: int | None) -> None:
        assert self.probe.active_contexts == 1
        assert session.in_transaction()
        self.calls.append(QueryCall(operation, session, limit))
        if self.stage == operation:
            assert self.error is not None
            raise self.error

    async def find_lifecycle_dispatch_candidates(
        self,
        session: AsyncSession,
        *,
        limit: int,
        retry_delay: timedelta = timedelta(seconds=60),
    ) -> list[AgentRuntime]:
        rows = await super().find_lifecycle_dispatch_candidates(
            session, limit=limit, retry_delay=retry_delay
        )
        self.point("lifecycle", session, limit)
        return rows

    async def find_provider_observe_candidates(
        self, session: AsyncSession, *, limit: int, observe_interval: timedelta
    ) -> list[AgentRuntime]:
        rows = await super().find_provider_observe_candidates(
            session, limit=limit, observe_interval=observe_interval
        )
        self.point("observe", session, limit)
        return rows

    async def find_configuration_adoption_candidates(
        self, session: AsyncSession, *, limit: int
    ) -> list[AgentRuntime]:
        rows = await super().find_configuration_adoption_candidates(
            session, limit=limit
        )
        self.point("adoption", session, limit)
        return rows

    async def get_by_id(
        self, session: AsyncSession, runtime_id: str
    ) -> AgentRuntime | None:
        row = await super().get_by_id(session, runtime_id)
        self.point("runtime_read", session, None)
        return row

    async def mark_provider_observe_requested(
        self, session: AsyncSession, runtime_id: str
    ) -> AgentRuntime | None:
        row = await super().mark_provider_observe_requested(session, runtime_id)
        self.point("marker", session, None)
        return row

    async def mark_start_timeouts(
        self, session: AsyncSession, *, stale_threshold: timedelta, limit: int
    ) -> list[AgentRuntime]:
        rows = await super().mark_start_timeouts(
            session, stale_threshold=stale_threshold, limit=limit
        )
        self.point("timeout", session, limit)
        return rows


class ObservedProfiles(RuntimeProfileRepository):
    def __init__(
        self, probe: SessionBoundaryProbe, error: BaseException | None
    ) -> None:
        self.probe = probe
        self.error = error
        self.sessions: list[AsyncSession] = []

    async def get_configuration_state(
        self, session: AsyncSession, *, runtime_id: str, for_update: bool = False
    ) -> RuntimeConfigurationState | None:
        state = await super().get_configuration_state(
            session, runtime_id=runtime_id, for_update=for_update
        )
        assert self.probe.active_contexts == 1 and session.in_transaction()
        self.sessions.append(session)
        if self.error is not None:
            raise self.error
        return state


@dataclasses.dataclass(frozen=True)
class ReconcileFixture:
    manager: SessionManager[AsyncSession]
    probe: SessionBoundaryProbe
    runtimes: ObservedRuntimes
    profiles: ObservedProfiles
    repository: RuntimeReconciliationOperationRepository
    runtime: AgentRuntime
    state: RuntimeConfigurationState


async def reconcile_fixture(
    manager: SessionManager[AsyncSession], name: str
) -> ReconcileFixture:
    prepared = await _prepare_start_dispatch(session_manager=manager, slug=name)
    async with manager() as session:
        state = await RuntimeProfileRepository().get_configuration_state(
            session, runtime_id=prepared.runtime.id
        )
        assert state is not None
    probe = SessionBoundaryProbe(manager)
    runtimes = ObservedRuntimes(probe, None, None)
    profiles = ObservedProfiles(probe, None)
    repository = RuntimeReconciliationOperationRepository(
        probe.session_manager, runtimes, profiles
    )
    return ReconcileFixture(
        manager, probe, runtimes, profiles, repository, prepared.runtime, state
    )


async def current(fixture: ReconcileFixture, id: str) -> AgentRuntime:
    async with fixture.manager() as session:
        value = await AgentRuntimeRepository().get_by_id(session, id)
        assert value is not None
        return value


async def running(fixture: ReconcileFixture, id: str) -> AgentRuntime:
    async with fixture.manager() as session:
        row = await AgentRuntimeRepository().get_by_id(session, id)
        assert row is not None
        await AgentRuntimeRepository().mark_lifecycle_dispatched(
            session, id, row.desired_generation
        )
        await AgentRuntimeRepository().record_provider_observed_state(
            session, id, RuntimeProviderObservedState.RUNNING, 1, row.desired_generation
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == id)
            .values(
                runner_state=RuntimeRunnerState.READY,
                last_state_change_at=sa.func.clock_timestamp()
                - sa.text("INTERVAL '10 minutes'"),
                provider_observed_at=sa.func.clock_timestamp()
                - sa.text("INTERVAL '10 minutes'"),
                provider_observe_requested_at=sa.func.clock_timestamp()
                - sa.text("INTERVAL '10 minutes'"),
            )
        )
    return await current(fixture, id)


async def pending_adoption(
    fixture: ReconcileFixture, id: str, *, acknowledged: bool
) -> RuntimeConfigurationState:
    async with fixture.manager() as session:
        repository = RuntimeProfileRepository()
        state = await repository.get_configuration_state(session, runtime_id=id)
        assert state is not None and state.desired.document is not None
        state = await repository.overwrite_desired_configuration_state(
            session,
            write=RuntimeConfigurationDesiredStateWrite(
                runtime_id=id,
                status=RuntimeConfigurationStateStatus.READY,
                target_generation=state.desired.target_generation,
                digest="e" * 64,
                document=state.desired.document,
                reason_code=None,
            ),
        )
        assert state is not None
        if acknowledged:
            assert state.desired.document is not None
            state = await repository.record_provider_configuration_evidence(
                session,
                runtime_id=id,
                provider_id=state.desired.document.provider_id,
                evidence=RuntimeConfigurationEvidence(
                    configuration_sequence=state.desired.sequence,
                    digest="e" * 64,
                    desired_generation=state.desired.target_generation,
                ),
                acknowledged_at=datetime.now(UTC),
            )
            assert state is not None
        return state


async def clone_runtime(fixture: ReconcileFixture, slug: str) -> AgentRuntime:
    async with fixture.manager() as session:
        agent_id = await _create_agent(session, fixture.runtime.workspace_id, slug)
        runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
        command = await AgentRuntimeRepository().set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None and fixture.state.desired.document is not None
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                runtime_provider_id="provider-1",
                runtime_provider_resource_id=fixture.state.desired.document.provider_id,
            )
        )
        state = await RuntimeProfileRepository().overwrite_desired_configuration_state(
            session,
            write=RuntimeConfigurationDesiredStateWrite(
                runtime_id=runtime.id,
                status=RuntimeConfigurationStateStatus.READY,
                target_generation=command.desired_generation,
                digest="d" * 64,
                document=fixture.state.desired.document,
                reason_code=None,
            ),
        )
        assert state is not None
        evidence = RuntimeConfigurationEvidence(
            configuration_sequence=state.desired.sequence,
            digest="d" * 64,
            desired_generation=command.desired_generation,
        )
        await RuntimeProfileRepository().record_provider_configuration_evidence(
            session,
            runtime_id=runtime.id,
            provider_id=fixture.state.desired.document.provider_id,
            evidence=evidence,
            acknowledged_at=datetime.now(UTC),
        )
        await RuntimeProfileRepository().record_runner_configuration_evidence(
            session,
            runtime_id=runtime.id,
            provider_id=fixture.state.desired.document.provider_id,
            evidence=evidence,
            observed_at=datetime.now(UTC),
        )
    return await current(fixture, runtime.id)


async def test_three_candidate_queries_share_session_and_preserve_sql_order_limits(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-three-lists")
    first = await running(fixture, fixture.runtime.id)
    second = await clone_runtime(fixture, "reconcile-other-agent")
    second = await running(fixture, second.id)
    await pending_adoption(fixture, first.id, acknowledged=False)
    await pending_adoption(fixture, second.id, acknowledged=False)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id.in_([first.id, second.id]))
            .values(
                last_lifecycle_command=RuntimeLifecycleCommandType.RESTART,
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            )
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == second.id)
            .values(
                last_state_change_at=sa.func.clock_timestamp()
                - sa.text("INTERVAL '9 minutes'"),
                provider_observed_at=sa.func.clock_timestamp()
                - sa.text("INTERVAL '9 minutes'"),
                provider_observe_requested_at=sa.func.clock_timestamp()
                - sa.text("INTERVAL '9 minutes'"),
            )
        )
    for limit in (0, 1, 2):
        fixture.runtimes.calls.clear()
        snapshot = await fixture.repository.collect_candidates(
            limit=limit,
            retry_delay=timedelta(seconds=15),
            observe_interval=timedelta(seconds=10),
        )
        expected = (first.id, second.id)[:limit]
        assert tuple(row.id for row in snapshot.lifecycle) == expected
        assert tuple(row.id for row in snapshot.observe) == expected
        assert tuple(row.id for row in snapshot.configuration_adoption) == expected
        assert [call.operation for call in fixture.runtimes.calls] == [
            "lifecycle",
            "observe",
            "adoption",
        ]
        assert all(call.limit == limit for call in fixture.runtimes.calls)
        assert all(
            call.session is fixture.runtimes.calls[0].session
            for call in fixture.runtimes.calls
        )
        fixture.probe.assert_no_active_transaction()
        assert isinstance(snapshot.lifecycle, tuple)
        assert dataclasses.is_dataclass(snapshot)


class ClosedStore(InMemoryRuntimeCoordinationStore):
    def __init__(self, fixture: ReconcileFixture, drift: bool) -> None:
        super().__init__()
        self.fixture = fixture
        self.drift = drift
        self.lookups = 0

    async def get_connection(
        self, *, kind: RuntimeConnectionKind, subject_id: str
    ) -> RuntimeConnectionRecord | None:
        self.fixture.probe.assert_no_active_transaction()
        self.lookups += 1
        if self.drift:
            async with self.fixture.manager() as session:
                await session.execute(
                    sa.update(RDBAgentRuntime)
                    .where(RDBAgentRuntime.id == self.fixture.runtime.id)
                    .values(desired_generation=RDBAgentRuntime.desired_generation + 1)
                )
            self.drift = False
        return await super().get_connection(kind=kind, subject_id=subject_id)


class ClosedProtocol(FakeRuntimeControlProtocolService):
    def __init__(
        self, store: ClosedStore, fixture: ReconcileFixture, error: BaseException | None
    ) -> None:
        super().__init__(store)
        self.fixture = fixture
        self.error = error
        self.commands: list[RuntimeProviderCommand] = []

    async def dispatch_provider_command(
        self, command: RuntimeProviderCommand, *, created_at: datetime
    ) -> (
        RuntimeDispatchResult
        | RuntimeProtocolRouteUnavailable
        | RuntimeProtocolStaleGeneration
    ):
        self.fixture.probe.assert_no_active_transaction()
        self.commands.append(command)
        result = await super().dispatch_provider_command(command, created_at=created_at)
        if self.error is not None:
            raise self.error
        return result


def reconciler(
    fixture: ReconcileFixture, store: ClosedStore, protocol: ClosedProtocol
) -> RuntimeLifecycleReconciler:
    return RuntimeLifecycleReconciler(
        repository=fixture.repository,
        dispatch_repository=_dispatch_repository(
            runtime_repository=fixture.runtimes,
            profile_repository=fixture.profiles,
            session_manager=fixture.probe.session_manager,
        ),
        coordination_store=store,
        control_protocol=protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
        ),
    )


async def test_periodic_marker_commits_even_when_no_provider_connection(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-marker-commit")
    runtime = await running(fixture, fixture.runtime.id)
    before = await current(fixture, runtime.id)
    store = ClosedStore(fixture, False)
    protocol = ClosedProtocol(store, fixture, None)
    assert not await reconciler(fixture, store, protocol)._dispatch_periodic_reconcile(
        runtime
    )
    after = await current(fixture, runtime.id)
    assert after.provider_observe_requested_at != before.provider_observe_requested_at
    assert (
        after.provider_connection_state is RuntimeProviderConnectionState.DISCONNECTED
    )
    assert protocol.commands == [] and store.lookups == 1
    assert fixture.profiles.sessions[0] is next(
        call.session for call in fixture.runtimes.calls if call.operation == "marker"
    )
    fixture.probe.assert_no_active_transaction()


async def test_periodic_acknowledged_pending_adoption_gate_skips_marker(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-profile-gate")
    runtime = await running(fixture, fixture.runtime.id)
    await pending_adoption(fixture, runtime.id, acknowledged=True)
    before = await current(fixture, runtime.id)
    assert not await fixture.repository.prepare_periodic_observation(runtime)
    assert await current(fixture, runtime.id) == before
    assert not any(call.operation == "marker" for call in fixture.runtimes.calls)
    fixture.probe.assert_no_active_transaction()


@pytest.mark.parametrize("kind", ["lifecycle", "adoption"])
async def test_reconcile_three_lists_suppress_duplicate_dispatch_and_timeout_is_last(
    rdb_session_manager: SessionManager[AsyncSession],
    kind: Literal["lifecycle", "adoption"],
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-suppression")
    await running(fixture, fixture.runtime.id)
    await pending_adoption(fixture, fixture.runtime.id, acknowledged=False)
    if kind == "lifecycle":
        async with rdb_session_manager() as session:
            await session.execute(
                sa.update(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == fixture.runtime.id)
                .values(
                    last_lifecycle_command=RuntimeLifecycleCommandType.RESTART,
                    provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                )
            )
    store = ClosedStore(fixture, False)
    protocol = ClosedProtocol(store, fixture, None)
    await protocol.register_provider(
        _provider_registration(), registered_at=datetime.now(UTC)
    )
    count = await reconciler(fixture, store, protocol).reconcile_once(limit=5)
    assert count == 1 and len(protocol.commands) == 1
    assert protocol.commands[0].command_type.value == (
        "restart" if kind == "lifecycle" else "update_configuration"
    )
    assert not any(call.operation == "marker" for call in fixture.runtimes.calls)
    assert fixture.runtimes.calls[-1].operation == "timeout"
    fixture.probe.assert_no_active_transaction()


@pytest.mark.parametrize("operation", ["candidates", "periodic", "adoption", "repair"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_actual_read_error_or_cancel_resolves_each_read_scope(
    rdb_session_manager: SessionManager[AsyncSession], operation: str, cancel: bool
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-read-fault")
    runtime = await running(fixture, fixture.runtime.id)
    error = asyncio.CancelledError() if cancel else RuntimeError("after actual read")
    if operation == "candidates":
        fixture.runtimes.stage = "observe"
        fixture.runtimes.error = error
    elif operation == "repair":
        fixture.runtimes.stage = "runtime_read"
        fixture.runtimes.error = error
    else:
        fixture.profiles.error = error
    with pytest.raises(type(error)):
        if operation == "candidates":
            await fixture.repository.collect_candidates(
                limit=5,
                retry_delay=timedelta(seconds=15),
                observe_interval=timedelta(seconds=10),
            )
        elif operation == "periodic":
            await fixture.repository.prepare_periodic_observation(runtime)
        elif operation == "adoption":
            await fixture.repository.load_adoption_state(runtime_id=runtime.id)
        else:
            await fixture.repository.load_observe_repair_target(repair_input(fixture))
    fixture.probe.assert_no_active_transaction()


def repair_input(fixture: ReconcileFixture) -> RuntimeObserveRepairInput:
    return RuntimeObserveRepairInput(
        runtime_id=fixture.runtime.id,
        provider_id="provider-1",
        provider_generation=1,
        observed_desired_generation=fixture.runtime.desired_generation,
        runtime_configuration=RuntimeConfigurationEvidence(
            configuration_sequence=fixture.state.desired.sequence,
            digest="d" * 64,
            desired_generation=fixture.runtime.desired_generation,
        ),
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "valid",
        "missing",
        "provider",
        "generation",
        "observed",
        "resource",
        "desired",
        "ready",
        "sequence",
        "digest",
    ],
)
async def test_observe_repair_exact_runtime_and_configuration_tuple_is_detached(
    rdb_session_manager: SessionManager[AsyncSession], invalid: str
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-repair-tuple")
    await running(fixture, fixture.runtime.id)
    input = repair_input(fixture)
    async with rdb_session_manager() as session:
        if invalid == "resource":
            await session.execute(
                sa.update(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == fixture.runtime.id)
                .values(runtime_provider_resource_id=None)
            )
        elif invalid == "desired":
            await session.execute(
                sa.update(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == fixture.runtime.id)
                .values(desired_state=RuntimeDesiredState.STOPPED)
            )
        elif invalid == "ready":
            await session.execute(
                sa.update(RDBRuntimeConfigurationState)
                .where(RDBRuntimeConfigurationState.runtime_id == fixture.runtime.id)
                .values(
                    desired_status=RuntimeConfigurationStateStatus.BLOCKED,
                    desired_reason_code="test-blocked",
                )
            )
    if invalid == "missing":
        input = dataclasses.replace(input, runtime_id="0" * 32)
    elif invalid == "provider":
        input = dataclasses.replace(input, provider_id="wrong-provider")
    elif invalid == "generation":
        input = dataclasses.replace(input, provider_generation=2)
    elif invalid == "observed":
        input = dataclasses.replace(
            input, observed_desired_generation=input.observed_desired_generation + 1
        )
    elif invalid in {"sequence", "digest"}:
        evidence = (
            dataclasses.replace(
                input.runtime_configuration,
                configuration_sequence=input.runtime_configuration.configuration_sequence
                + 1,
            )
            if invalid == "sequence"
            else dataclasses.replace(input.runtime_configuration, digest="f" * 64)
        )
        input = dataclasses.replace(input, runtime_configuration=evidence)
    target = await fixture.repository.load_observe_repair_target(input)
    assert (target is not None) == (invalid == "valid")
    if target is not None:
        assert target.id == fixture.runtime.id
        assert fixture.profiles.sessions[-1] is fixture.runtimes.calls[0].session
        assert target.model_dump(mode="json")["id"] == fixture.runtime.id
    fixture.probe.assert_no_active_transaction()


@pytest.mark.parametrize("mutation", ["marker", "timeout"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_mutation_failure_after_actual_write_rolls_back_only_that_operation(
    rdb_session_manager: SessionManager[AsyncSession], mutation: str, cancel: bool
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-write-fault")
    runtime = await running(fixture, fixture.runtime.id)
    if mutation == "timeout":
        async with rdb_session_manager() as session:
            await session.execute(
                sa.update(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == runtime.id)
                .values(
                    provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                    provider_observed_state=RuntimeProviderObservedState.STARTING,
                    runner_state=RuntimeRunnerState.UNKNOWN,
                )
            )
    before = await current(fixture, runtime.id)
    error = asyncio.CancelledError() if cancel else RuntimeError("after actual write")
    fixture.runtimes.stage = mutation
    fixture.runtimes.error = error
    with pytest.raises(type(error)):
        if mutation == "marker":
            await fixture.repository.prepare_periodic_observation(runtime)
        else:
            await fixture.repository.mark_start_timeouts(
                stale_threshold=timedelta(minutes=5), limit=5
            )
    assert any(call.operation == mutation for call in fixture.runtimes.calls)
    assert await current(fixture, runtime.id) == before
    fixture.probe.assert_no_active_transaction()


async def test_separate_timeout_commit_preserves_previous_observe_marker(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-timeout-commit")
    runtime = await running(fixture, fixture.runtime.id)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                provider_observed_state=RuntimeProviderObservedState.STARTING,
                runner_state=RuntimeRunnerState.UNKNOWN,
            )
        )
    assert await fixture.repository.prepare_periodic_observation(runtime)
    marker = (await current(fixture, runtime.id)).provider_observe_requested_at
    result = await fixture.repository.mark_start_timeouts(
        stale_threshold=timedelta(minutes=5), limit=1
    )
    assert result.count == 1
    timed_out = await current(fixture, runtime.id)
    assert timed_out.failure_code == "START_TIMEOUT"
    assert timed_out.provider_observe_requested_at == marker
    assert len(fixture.probe.completed_sessions) == 2
    fixture.probe.assert_no_active_transaction()


@pytest.mark.parametrize("cancel", [False, True])
async def test_periodic_dispatch_unknown_error_or_cancel_preserves_committed_marker(
    rdb_session_manager: SessionManager[AsyncSession], cancel: bool
) -> None:
    fixture = await reconcile_fixture(rdb_session_manager, "reconcile-dispatch-failure")
    runtime = await running(fixture, fixture.runtime.id)
    error = asyncio.CancelledError() if cancel else RuntimeError("outcome unknown")
    store = ClosedStore(fixture, False)
    protocol = ClosedProtocol(store, fixture, error)
    await protocol.register_provider(
        _provider_registration(), registered_at=datetime.now(UTC)
    )
    before = await current(fixture, runtime.id)
    with pytest.raises(type(error)):
        await reconciler(fixture, store, protocol)._dispatch_periodic_reconcile(runtime)
    after = await current(fixture, runtime.id)
    assert after.provider_observe_requested_at != before.provider_observe_requested_at
    assert after.provider_connection_state == before.provider_connection_state
    assert len(protocol.commands) == 1
    fixture.probe.assert_no_active_transaction()


async def test_repair_authority_revalidated_after_coordination_generation_drift(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    fixture = await reconcile_fixture(
        rdb_session_manager, "reconcile-coordination-drift"
    )
    await running(fixture, fixture.runtime.id)
    store = ClosedStore(fixture, True)
    protocol = ClosedProtocol(store, fixture, None)
    await protocol.register_provider(
        _provider_registration(), registered_at=datetime.now(UTC)
    )
    report = _network_policy_drift_report(
        runtime_id=fixture.runtime.id,
        desired_generation=fixture.runtime.desired_generation,
        configuration_sequence=fixture.state.desired.sequence,
    )
    assert not await reconciler(fixture, store, protocol).reconcile_observe_completion(
        report
    )
    assert store.lookups == 1 and protocol.commands == []
    assert (
        await current(fixture, fixture.runtime.id)
    ).desired_generation == fixture.runtime.desired_generation + 1
    fixture.probe.assert_no_active_transaction()
