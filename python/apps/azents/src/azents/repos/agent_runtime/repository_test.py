"""AgentRuntimeRepository tests."""

import asyncio
import datetime
from contextlib import suppress
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingOrigin,
    RuntimeProviderConnectionState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderObservedState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
    RuntimeRunnerState,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime.data import AgentRuntimeFailurePatch
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentRuntimeRepository


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="AgentRuntime test", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(
    session: AsyncSession,
    workspace_id: str,
    slug: str,
) -> str:
    """Create Agent for tests."""

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="AgentRuntime test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
    )
    session.add(agent)
    await session.flush()
    return agent.id


class TestAgentRuntimeRepository:
    """AgentRuntimeRepository tests."""

    async def test_runtime_selection_lock_serializes_selection_not_state_reports(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Selection updates wait while independent Runtime reports proceed."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        workspace_id: str | None = None
        agent_id: str | None = None
        runtime_id: str | None = None
        report_task: asyncio.Task[object] | None = None
        update_task: asyncio.Task[object] | None = None

        try:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as setup_session:
                workspace_id = await _create_workspace(
                    setup_session,
                    f"runtime-selection-lock-{suffix}",
                )
                agent_id = await _create_agent(
                    setup_session,
                    workspace_id,
                    f"runtime-selection-lock-{suffix}",
                )
                runtime = await AgentRuntimeRepository().ensure_for_agent(
                    setup_session,
                    agent_id,
                )
                runtime_id = runtime.id
                await setup_session.commit()

            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as selection_session:
                locked = await AgentRepository().get_runtime_selection_input_for_update(
                    selection_session,
                    agent_id,
                )
                assert locked is not None
                update_started = asyncio.Event()

                async def update_selection() -> object:
                    async with AsyncSession(
                        rdb_engine,
                        expire_on_commit=False,
                    ) as update_session:
                        update_started.set()
                        result = await update_session.execute(
                            sa.update(RDBAgent)
                            .where(RDBAgent.id == agent_id)
                            .values(
                                runtime_profile_selection_version=(
                                    RDBAgent.runtime_profile_selection_version + 1
                                )
                            )
                            .returning(RDBAgent.runtime_profile_selection_version)
                        )
                        await update_session.commit()
                        return result.scalar_one()

                async def record_state() -> object:
                    async with AsyncSession(
                        rdb_engine,
                        expire_on_commit=False,
                    ) as report_session:
                        updated = await (
                            AgentRuntimeRepository().record_provider_connection_state(
                                report_session,
                                runtime_id,
                                RuntimeProviderConnectionState.CONNECTED,
                            )
                        )
                        await report_session.commit()
                        return updated

                update_task = asyncio.create_task(update_selection())
                await asyncio.wait_for(update_started.wait(), timeout=5)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(update_task),
                        timeout=0.1,
                    )

                report_task = asyncio.create_task(record_state())
                updated = await asyncio.wait_for(report_task, timeout=5)
                assert updated is not None
                await selection_session.commit()
                updated_version = await asyncio.wait_for(update_task, timeout=5)
                assert updated_version == locked.runtime_profile_selection_version + 1
        finally:
            if report_task is not None and not report_task.done():
                report_task.cancel()
                with suppress(asyncio.CancelledError):
                    await report_task
            if update_task is not None and not update_task.done():
                update_task.cancel()
                with suppress(asyncio.CancelledError):
                    await update_task
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as cleanup_session:
                if runtime_id is not None:
                    await cleanup_session.execute(
                        sa.delete(RDBAgentRuntime).where(
                            RDBAgentRuntime.id == runtime_id
                        )
                    )
                if agent_id is not None:
                    await cleanup_session.execute(
                        sa.delete(RDBAgent).where(RDBAgent.id == agent_id)
                    )
                if workspace_id is not None:
                    await cleanup_session.execute(
                        sa.delete(RDBLLMProviderIntegration).where(
                            RDBLLMProviderIntegration.workspace_id == workspace_id
                        )
                    )
                    await cleanup_session.execute(
                        sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
                    )
                await cleanup_session.commit()

    async def test_ensure_for_agent_creates_one_runtime(
        self, rdb_session: AsyncSession
    ) -> None:
        """Create only one AgentRuntime per Agent."""
        workspace_id = await _create_workspace(rdb_session, "agent-runtime-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "agent-runtime-model")
        repo = AgentRuntimeRepository()

        first = await repo.ensure_for_agent(rdb_session, agent_id)
        second = await repo.ensure_for_agent(rdb_session, agent_id)

        assert first.id == second.id
        assert first.agent_id == agent_id
        assert first.workspace_id == workspace_id
        assert first.desired_state == RuntimeDesiredState.STOPPED
        assert first.desired_generation == 0
        assert first.last_lifecycle_dispatch_generation == 0
        assert first.provider_observed_state == RuntimeProviderObservedState.UNKNOWN
        assert (
            first.provider_connection_state
            == RuntimeProviderConnectionState.DISCONNECTED
        )
        assert first.runner_state == RuntimeRunnerState.UNKNOWN

    async def test_attach_provider_binding_upgrades_exact_legacy_runtime(
        self, rdb_session: AsyncSession
    ) -> None:
        """Attach durable identity only when the historical logical ID matches."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-attach-provider-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-attach-provider",
        )
        repository = AgentRuntimeRepository()
        runtime = await repository.ensure_for_agent(rdb_session, agent_id)
        provider = await RuntimeProviderRepository().create(
            rdb_session,
            RuntimeProviderCreate(
                provider_id="system-kubernetes",
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.KUBERNETES,
                display_name="Kubernetes",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )

        bound = await repository.attach_provider_binding(
            rdb_session,
            runtime_id=runtime.id,
            provider_logical_id=provider.provider_id,
            provider_resource_id=provider.id,
            binding_origin=RuntimeProviderBindingOrigin.MIGRATION,
            binding_evidence={"origin": "migration"},
        )

        assert bound is not None
        assert bound.runtime_provider_resource_id == provider.id
        assert bound.provider_binding_origin is RuntimeProviderBindingOrigin.MIGRATION
        assert bound.provider_binding_evidence == {"origin": "migration"}

        conflicting = await repository.attach_provider_binding(
            rdb_session,
            runtime_id=runtime.id,
            provider_logical_id="different-provider",
            provider_resource_id=provider.id,
            binding_origin=RuntimeProviderBindingOrigin.MIGRATION,
            binding_evidence={"origin": "conflict"},
        )
        assert conflicting is None

    async def test_get_by_agent_id_returns_existing_runtime(
        self, rdb_session: AsyncSession
    ) -> None:
        """Fetch existing AgentRuntime by Agent ID."""
        workspace_id = await _create_workspace(rdb_session, "agent-runtime-get-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "agent-runtime-get")
        repo = AgentRuntimeRepository()
        created = await repo.ensure_for_agent(rdb_session, agent_id)

        loaded = await repo.get_by_agent_id(rdb_session, agent_id)

        assert loaded is not None
        assert loaded.id == created.id

    async def test_set_desired_state_increments_generation(
        self, rdb_session: AsyncSession
    ) -> None:
        """lifecycle command increments desired generation."""
        workspace_id = await _create_workspace(rdb_session, "agent-runtime-desired-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-desired"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime_with_workspace = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            runner_generation=1,
            expected_desired_generation=runtime.desired_generation,
            workspace_path="/runtime/old-home",
        )
        assert runtime_with_workspace is not None

        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )

        assert command is not None
        assert command.runtime.desired_state == RuntimeDesiredState.RUNNING
        assert command.runtime.desired_generation == 1
        assert (
            command.runtime.last_lifecycle_command == RuntimeLifecycleCommandType.START
        )
        assert command.runtime.workspace_path is None

    async def test_repeated_stop_keeps_desired_generation(
        self, rdb_session: AsyncSession
    ) -> None:
        """Repeating an already targeted STOP is idempotent."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-repeat-stop-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-repeat-stop",
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)

        first = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
        )
        assert first is not None
        repeated = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
        )

        assert repeated is not None
        assert repeated.desired_generation == first.desired_generation
        assert repeated.runtime.desired_generation == first.runtime.desired_generation

    async def test_terminal_delete_acknowledgement_fences_finalization(
        self, rdb_session: AsyncSession
    ) -> None:
        """Terminal deletion fences lifecycle and late Provider state changes."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-terminal-delete-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-terminal-delete"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime_with_workspace = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            runner_generation=1,
            expected_desired_generation=runtime.desired_generation,
            workspace_path="/runtime/old-home",
        )
        assert runtime_with_workspace is not None
        requested = await repo.request_terminal_delete(rdb_session, runtime.id)

        assert requested is not None
        assert requested.workspace_path is None
        assert (
            requested.terminal_delete_requested_generation
            == requested.desired_generation
        )
        assert (
            await repo.get_terminal_delete_acknowledged(rdb_session, runtime.id) is None
        )

        repeated_request = await repo.request_terminal_delete(rdb_session, runtime.id)
        stale_acknowledgement = await repo.record_terminal_delete_acknowledgement(
            rdb_session,
            runtime.id,
            provider_generation=1,
            acknowledged_generation=requested.desired_generation - 1,
        )
        acknowledged = await repo.record_terminal_delete_acknowledgement(
            rdb_session,
            runtime.id,
            provider_generation=1,
            acknowledged_generation=requested.desired_generation,
        )
        repeated_acknowledgement = await repo.record_terminal_delete_acknowledgement(
            rdb_session,
            runtime.id,
            provider_generation=2,
            acknowledged_generation=requested.desired_generation,
        )
        finalizable = await repo.get_terminal_delete_acknowledged(
            rdb_session, runtime.id
        )
        late_runner = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            runner_generation=1,
            expected_desired_generation=requested.desired_generation,
            workspace_path="/runtime/home",
        )
        late_provider = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            provider_generation=2,
            observed_generation=requested.desired_generation,
        )
        blocked_lifecycle_command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        repeated_acknowledged_request = await repo.request_terminal_delete(
            rdb_session,
            runtime.id,
        )

        assert repeated_request is not None
        assert repeated_request.desired_generation == requested.desired_generation
        assert stale_acknowledgement is None
        assert acknowledged is not None
        assert repeated_acknowledgement is None
        assert acknowledged.terminal_delete_acknowledgement_kind is (
            RuntimeTerminalDeleteAcknowledgementKind.PROVIDER_REPORT
        )
        assert finalizable is not None
        assert finalizable.workspace_path is None
        assert late_runner is None
        assert late_provider is None
        assert blocked_lifecycle_command is None
        assert repeated_acknowledged_request is not None
        assert (
            repeated_acknowledged_request.terminal_delete_requested_generation
            == requested.desired_generation
        )
        assert (
            repeated_acknowledged_request.terminal_delete_acknowledged_generation
            == requested.desired_generation
        )
        assert repeated_acknowledged_request.terminal_delete_acknowledgement_kind is (
            RuntimeTerminalDeleteAcknowledgementKind.PROVIDER_REPORT
        )

    async def test_no_physical_binding_acknowledgement_never_dispatches(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A never-bound logical Runtime terminalizes without Provider work."""
        workspace_id = await _create_workspace(
            rdb_session,
            "agent-runtime-no-physical-binding-ws",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-no-physical-binding",
        )
        repository = AgentRuntimeRepository()
        runtime = await repository.ensure_for_agent(rdb_session, agent_id)

        acknowledged = (
            await repository.request_terminal_delete_without_physical_binding(
                rdb_session,
                runtime.id,
            )
        )
        repeated = await repository.request_terminal_delete_without_physical_binding(
            rdb_session,
            runtime.id,
        )
        candidates = await repository.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(0),
        )

        assert acknowledged is not None
        assert repeated is not None
        assert repeated.desired_generation == acknowledged.desired_generation
        assert acknowledged.desired_generation == runtime.desired_generation + 1
        assert acknowledged.last_lifecycle_command is None
        assert acknowledged.provider_observed_state is (
            RuntimeProviderObservedState.UNKNOWN
        )
        assert acknowledged.provider_observed_at is None
        assert acknowledged.runner_state is RuntimeRunnerState.UNKNOWN
        assert (
            acknowledged.last_lifecycle_dispatch_generation
            == acknowledged.desired_generation
        )
        assert (
            acknowledged.terminal_delete_requested_generation
            == acknowledged.desired_generation
        )
        assert (
            acknowledged.terminal_delete_acknowledged_generation
            == acknowledged.desired_generation
        )
        assert acknowledged.terminal_delete_acknowledgement_kind is (
            RuntimeTerminalDeleteAcknowledgementKind.NO_PHYSICAL_BINDING
        )
        assert all(candidate.id != runtime.id for candidate in candidates)

    @pytest.mark.parametrize(
        "evidence_values",
        [
            {"runtime_provider_id": "historical-provider"},
            {"provider_binding_origin": (RuntimeProviderBindingOrigin.AGENT_EXPLICIT)},
            {"provider_binding_evidence": {"source": "historical"}},
            {"provider_generation": 1},
            {"provider_observed_state": RuntimeProviderObservedState.RUNNING},
            {"provider_observed_generation": 1},
            {"provider_observed_at": datetime.datetime.now(datetime.UTC)},
            {"provider_observe_requested_at": datetime.datetime.now(datetime.UTC)},
            {"last_lifecycle_dispatch_generation": 1},
            {"provider_connection_state": (RuntimeProviderConnectionState.CONNECTED)},
            {"runner_state": RuntimeRunnerState.READY},
            {"runner_generation": 1},
            {"workspace_path": "/runtime/historical-workspace"},
            {
                "failure_generation": 0,
                "failure_code": "historical_failure",
                "failure_message": "Historical Runtime failure",
            },
        ],
    )
    async def test_no_physical_binding_rejects_observation_or_dispatch_evidence(
        self,
        rdb_session: AsyncSession,
        evidence_values: dict[str, object],
    ) -> None:
        """Any prior observation or route evidence requires physical deletion."""
        workspace_id = await _create_workspace(
            rdb_session,
            f"agent-runtime-no-binding-proof-{uuid4().hex[:8]}",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            f"agent-runtime-no-binding-proof-{uuid4().hex[:8]}",
        )
        repository = AgentRuntimeRepository()
        runtime = await repository.ensure_for_agent(rdb_session, agent_id)
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(**evidence_values)
        )

        acknowledged = (
            await repository.request_terminal_delete_without_physical_binding(
                rdb_session,
                runtime.id,
            )
        )
        reloaded = await repository.get_by_id(rdb_session, runtime.id)

        assert acknowledged is None
        assert reloaded is not None
        assert reloaded.terminal_delete_requested_generation is None
        assert reloaded.terminal_delete_acknowledged_generation is None

    async def test_rearm_preserves_identity_and_clears_incarnation_state(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Exact deletion acknowledgement permits one higher-generation rearm."""
        workspace_id = await _create_workspace(
            rdb_session,
            "agent-runtime-rearm-ws",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-rearm",
        )
        repository = AgentRuntimeRepository()
        runtime = await repository.ensure_for_agent(rdb_session, agent_id)
        provider = await RuntimeProviderRepository().create(
            rdb_session,
            RuntimeProviderCreate(
                provider_id="system-kubernetes-rearm",
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.KUBERNETES,
                display_name="Kubernetes rearm",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
        bound = await repository.attach_provider_binding(
            rdb_session,
            runtime_id=runtime.id,
            provider_logical_id=provider.provider_id,
            provider_resource_id=provider.id,
            binding_origin=RuntimeProviderBindingOrigin.AGENT_EXPLICIT,
            binding_evidence={"origin": "add"},
        )
        assert bound is not None
        observed = await repository.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            provider_generation=2,
            observed_generation=runtime.desired_generation,
        )
        assert observed is not None
        ready = await repository.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            runner_generation=3,
            expected_desired_generation=runtime.desired_generation,
            workspace_path="/runtime/old-home",
        )
        assert ready is not None
        requested = await repository.request_terminal_delete(
            rdb_session,
            runtime.id,
        )
        assert requested is not None
        acknowledged = await repository.record_terminal_delete_acknowledgement(
            rdb_session,
            runtime.id,
            provider_generation=4,
            acknowledged_generation=requested.desired_generation,
        )
        assert acknowledged is not None

        provider_conflict = await repository.rearm_terminally_deleted(
            rdb_session,
            runtime_id=runtime.id,
            expected_terminal_generation=requested.desired_generation,
            provider_logical_id="different-provider",
            provider_resource_id=provider.id,
        )
        rearmed = await repository.rearm_terminally_deleted(
            rdb_session,
            runtime_id=runtime.id,
            expected_terminal_generation=requested.desired_generation,
            provider_logical_id=provider.provider_id,
            provider_resource_id=provider.id,
        )
        late_provider = await repository.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            provider_generation=4,
            observed_generation=requested.desired_generation,
        )

        assert provider_conflict is None
        assert rearmed is not None
        assert rearmed.id == runtime.id
        assert rearmed.desired_state is RuntimeDesiredState.STOPPED
        assert rearmed.desired_generation == requested.desired_generation + 1
        assert rearmed.last_lifecycle_command is None
        assert rearmed.last_lifecycle_dispatch_generation == rearmed.desired_generation
        assert rearmed.terminal_delete_requested_generation is None
        assert rearmed.terminal_delete_acknowledged_generation is None
        assert rearmed.terminal_delete_acknowledgement_kind is None
        assert rearmed.provider_observed_state is RuntimeProviderObservedState.UNKNOWN
        assert rearmed.provider_generation == acknowledged.provider_generation
        assert rearmed.provider_observed_generation == 0
        assert rearmed.provider_connection_state is (
            RuntimeProviderConnectionState.DISCONNECTED
        )
        assert rearmed.runner_state is RuntimeRunnerState.UNKNOWN
        assert rearmed.runner_generation == ready.runner_generation
        assert rearmed.workspace_path is None
        assert rearmed.configuration_sequence == runtime.configuration_sequence
        assert late_provider is None

    async def test_record_provider_and_runner_state(
        self, rdb_session: AsyncSession
    ) -> None:
        """Store Provider state and Runner-owned workspace path."""
        workspace_id = await _create_workspace(rdb_session, "agent-runtime-observed-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-observed"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)

        provider_runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            1,
            3,
        )
        runner_runtime = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            4,
            expected_desired_generation=runtime.desired_generation,
            workspace_path="/runtime/home",
            failure=AgentRuntimeFailurePatch(
                generation=4, code="runner_failed", message="Runner failed"
            ),
        )

        assert provider_runtime is not None
        assert provider_runtime.provider_observed_state == (
            RuntimeProviderObservedState.RUNNING
        )
        assert provider_runtime.provider_observed_generation == 3
        assert provider_runtime.workspace_path is None
        assert runner_runtime is not None
        assert runner_runtime.runner_state == RuntimeRunnerState.READY
        assert runner_runtime.runner_generation == 4
        assert runner_runtime.workspace_path == "/runtime/home"
        assert runner_runtime.failure_code == "runner_failed"

    async def test_stale_provider_report_is_ignored(
        self, rdb_session: AsyncSession
    ) -> None:
        """Older Provider report generations do not overwrite Runtime state."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-stale-provider-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-stale-provider"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        current = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            2,
            command.desired_generation,
        )
        assert current is not None

        stale = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.FAILED,
            1,
            command.desired_generation - 1,
            failure=AgentRuntimeFailurePatch(
                generation=command.desired_generation,
                code="STALE_PROVIDER_FAILURE",
                message="Stale provider failure",
            ),
        )

        reloaded = await repo.get_by_id(rdb_session, runtime.id)
        assert stale is None
        assert reloaded is not None
        assert reloaded.provider_generation == 2
        assert reloaded.provider_observed_generation == command.desired_generation
        assert reloaded.provider_observed_state == RuntimeProviderObservedState.RUNNING
        assert reloaded.workspace_path is None
        assert reloaded.failure_code is None

    async def test_current_provider_report_is_accepted(
        self, rdb_session: AsyncSession
    ) -> None:
        """Current Provider report generations can update Runtime state."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-current-provider-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-current-provider"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None

        updated = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            1,
            command.desired_generation,
        )

        assert updated is not None
        assert updated.provider_generation == 1
        assert updated.provider_observed_generation == command.desired_generation
        assert updated.provider_observed_state == RuntimeProviderObservedState.RUNNING
        assert updated.workspace_path is None

    async def test_stale_runner_report_is_ignored(
        self, rdb_session: AsyncSession
    ) -> None:
        """Older Runner generations do not overwrite Runtime availability."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-stale-runner-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-stale-runner"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        current = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            2,
            expected_desired_generation=runtime.desired_generation,
            workspace_path="/runtime/current",
        )
        assert current is not None

        stale = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.DISCONNECTED,
            1,
            expected_desired_generation=runtime.desired_generation,
            workspace_path="/runtime/stale",
            failure=AgentRuntimeFailurePatch(
                generation=runtime.desired_generation,
                code="STALE_RUNNER_FAILURE",
                message="Stale runner failure",
            ),
        )

        reloaded = await repo.get_by_id(rdb_session, runtime.id)
        assert stale is None
        assert reloaded is not None
        assert reloaded.runner_generation == 2
        assert reloaded.runner_state == RuntimeRunnerState.READY
        assert reloaded.failure_code is None

    async def test_same_runner_generation_report_is_accepted(
        self, rdb_session: AsyncSession
    ) -> None:
        """Same Runner generation can update state for stream-close reports."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-same-runner-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-same-runner"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        current = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            2,
            expected_desired_generation=runtime.desired_generation,
            workspace_path="/runtime/home",
        )
        assert current is not None

        disconnected = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.DISCONNECTED,
            2,
            expected_desired_generation=runtime.desired_generation,
            workspace_path=None,
        )

        assert disconnected is not None
        assert disconnected.runner_generation == 2
        assert disconnected.runner_state == RuntimeRunnerState.DISCONNECTED
        assert disconnected.workspace_path is None

    async def test_lifecycle_dispatch_candidates_track_generation(
        self, rdb_session: AsyncSession
    ) -> None:
        """Dispatched desired generation is excluded from redispatch candidates."""
        workspace_id = await _create_workspace(rdb_session, "agent-runtime-dispatch-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-dispatch"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(seconds=0),
        )

        assert [candidate.id for candidate in candidates] == [runtime.id]

        updated = await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        assert updated is not None
        assert updated.last_lifecycle_dispatch_generation == command.desired_generation

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
        )
        assert candidates == []

    async def test_claim_lifecycle_dispatch_claims_generation_once(
        self, rdb_session: AsyncSession
    ) -> None:
        """Only one Control replica claims dispatch for same desired generation."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-claim-once-ws"
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "claim-once-agent")
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None

        first_claim = await repo.claim_lifecycle_dispatch(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        second_claim = await repo.claim_lifecycle_dispatch(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )

        assert first_claim is not None
        assert (
            first_claim.last_lifecycle_dispatch_generation == command.desired_generation
        )
        assert second_claim is None

    async def test_claim_lifecycle_dispatch_throttles_dropped_start_retry(
        self, rdb_session: AsyncSession
    ) -> None:
        """Dropped start retry also does not duplicate dispatch right after claim."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-claim-dropped-start-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "claim-dropped-start-agent"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STOPPED,
            1,
            0,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                last_state_change_at=(
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=2)
                )
            )
        )

        retry_claim = await repo.claim_lifecycle_dispatch(
            rdb_session,
            runtime.id,
            command.desired_generation,
            retry_delay=datetime.timedelta(minutes=1),
        )
        duplicate_claim = await repo.claim_lifecycle_dispatch(
            rdb_session,
            runtime.id,
            command.desired_generation,
            retry_delay=datetime.timedelta(minutes=1),
        )

        assert retry_claim is not None
        assert duplicate_claim is None

    async def test_stop_command_preempts_dispatched_start(
        self, rdb_session: AsyncSession
    ) -> None:
        """STOP desired generation dispatches regardless of in-progress START."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-stop-preempts-start-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-stop-preempts-start"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STOPPED,
            1,
            0,
        )
        assert runtime is not None
        start_command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert start_command is not None
        start_claim = await repo.claim_lifecycle_dispatch(
            rdb_session,
            runtime.id,
            start_command.desired_generation,
            retry_delay=datetime.timedelta(minutes=1),
        )
        assert start_claim is not None

        stop_command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
        )
        assert stop_command is not None

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(minutes=1),
        )
        stop_claim = await repo.claim_lifecycle_dispatch(
            rdb_session,
            runtime.id,
            stop_command.desired_generation,
            retry_delay=datetime.timedelta(minutes=1),
        )

        assert [candidate.id for candidate in candidates] == [runtime.id]
        assert stop_claim is not None
        assert stop_claim.last_lifecycle_command == RuntimeLifecycleCommandType.STOP
        assert (
            stop_claim.last_lifecycle_dispatch_generation
            == stop_command.desired_generation
        )

    async def test_lifecycle_dispatch_candidates_throttle_dropped_start(
        self, rdb_session: AsyncSession
    ) -> None:
        """Do not redispatch start generation before retry cooldown."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-throttle-dropped-start-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-throttle-dropped-start"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STOPPED,
            1,
            0,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        updated = await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        assert updated is not None

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
        )

        assert candidates == []

    async def test_lifecycle_dispatch_candidates_retry_dropped_start(
        self, rdb_session: AsyncSession
    ) -> None:
        """Redispatch when connected Provider did not observe start generation."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-dropped-start-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-dropped-start"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STOPPED,
            1,
            0,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        updated = await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        assert updated is not None

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(seconds=0),
        )

        assert [candidate.id for candidate in candidates] == [runtime.id]

    async def test_lifecycle_dispatch_candidates_retry_current_generation_failure(
        self, rdb_session: AsyncSession
    ) -> None:
        """Redispatch dropped start after Provider current-generation failure."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-current-failure-retry-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-current-failure-retry"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STOPPED,
            1,
            0,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        await repo.record_runtime_failure(
            rdb_session,
            runtime.id,
            AgentRuntimeFailurePatch(
                generation=command.desired_generation,
                code="KubernetesApiRequestError",
                message="Kubernetes API request failed",
            ),
        )

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(seconds=0),
        )

        assert [candidate.id for candidate in candidates] == [runtime.id]

    async def test_stale_runtime_failure_does_not_overwrite_current_generation(
        self, rdb_session: AsyncSession
    ) -> None:
        """A previous lifecycle generation cannot replace the current failure."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-stale-failure-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-stale-failure",
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        start = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert start is not None
        stop = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
        )
        assert stop is not None
        current = await repo.record_runtime_failure(
            rdb_session,
            runtime.id,
            AgentRuntimeFailurePatch(
                generation=stop.desired_generation,
                code="CURRENT_FAILURE",
                message="Current lifecycle failed",
            ),
        )
        stale = await repo.record_runtime_failure(
            rdb_session,
            runtime.id,
            AgentRuntimeFailurePatch(
                generation=start.desired_generation,
                code="STALE_FAILURE",
                message="Previous lifecycle failed late",
            ),
        )
        reloaded = await repo.get_by_id(rdb_session, runtime.id)

        assert current is not None
        assert stale is None
        assert reloaded is not None
        assert reloaded.failure_generation == stop.desired_generation
        assert reloaded.failure_code == "CURRENT_FAILURE"
        assert reloaded.failure_message == "Current lifecycle failed"

    async def test_lifecycle_dispatch_candidates_retry_current_generation_starting(
        self, rdb_session: AsyncSession
    ) -> None:
        """If RUNNING desired stalls at STARTING, redispatch same generation start."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-current-starting-retry-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-current-starting-retry"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STARTING,
            1,
            command.desired_generation,
        )
        assert runtime is not None

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(seconds=0),
        )
        retry_claim = await repo.claim_lifecycle_dispatch(
            rdb_session,
            runtime.id,
            command.desired_generation,
            retry_delay=datetime.timedelta(seconds=0),
        )

        assert [candidate.id for candidate in candidates] == [runtime.id]
        assert retry_claim is not None

    async def test_lifecycle_dispatch_candidates_retry_current_generation_stopping(
        self, rdb_session: AsyncSession
    ) -> None:
        """If RUNNING desired stalls at STOPPING, redispatch same generation start."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-current-stopping-retry-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-current-stopping-retry"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STOPPING,
            1,
            command.desired_generation,
        )
        assert runtime is not None

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(seconds=0),
        )
        retry_claim = await repo.claim_lifecycle_dispatch(
            rdb_session,
            runtime.id,
            command.desired_generation,
            retry_delay=datetime.timedelta(seconds=0),
        )

        assert [candidate.id for candidate in candidates] == [runtime.id]
        assert retry_claim is not None

    async def test_identical_provider_report_preserves_lifecycle_retry_clock(
        self, rdb_session: AsyncSession
    ) -> None:
        """Same Provider report does not update start retry baseline time."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-identical-report-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-identical-report",
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STARTING,
            1,
            command.desired_generation,
        )
        assert runtime is not None
        old_state_change_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(last_state_change_at=old_state_change_at)
        )

        reported = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STARTING,
            1,
            command.desired_generation,
        )
        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(minutes=1),
        )

        assert reported is not None
        assert reported.last_state_change_at == old_state_change_at
        assert [candidate.id for candidate in candidates] == [runtime.id]

    async def test_provider_observe_candidates_use_provider_observe_clock(
        self, rdb_session: AsyncSession
    ) -> None:
        """Provider observe interval is separated from unrelated runtime update."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-observe-candidate-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-observe-candidate",
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(runtime_provider_id="provider-1")
        )
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        old_observe_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_observed_at=old_observe_at,
                provider_observe_requested_at=old_observe_at,
            )
        )

        candidates = await repo.find_provider_observe_candidates(
            rdb_session,
            limit=10,
            observe_interval=datetime.timedelta(minutes=1),
        )
        dispatched = await repo.mark_provider_observe_requested(
            rdb_session,
            runtime.id,
        )
        throttled = await repo.find_provider_observe_candidates(
            rdb_session,
            limit=10,
            observe_interval=datetime.timedelta(minutes=1),
        )

        assert [candidate.id for candidate in candidates] == [runtime.id]
        assert dispatched is not None
        assert dispatched.provider_observe_requested_at is not None
        assert throttled == []

    async def test_provider_observe_rechecks_stopping_runtime(
        self, rdb_session: AsyncSession
    ) -> None:
        """Stopped desired state is observed until the Provider reports stopped."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-observe-stopping-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-observe-stopping",
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(runtime_provider_id="provider-1")
        )
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
        )
        assert command is not None
        await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STOPPING,
            1,
            command.desired_generation,
        )
        assert runtime is not None
        old_observe_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_observed_at=old_observe_at,
                provider_observe_requested_at=old_observe_at,
            )
        )
        disconnected = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.DISCONNECTED,
        )

        candidates = await repo.find_provider_observe_candidates(
            rdb_session,
            limit=10,
            observe_interval=datetime.timedelta(minutes=1),
        )
        stopped_runtime = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.STOPPED,
            1,
            command.desired_generation,
        )
        converged = await repo.find_provider_observe_candidates(
            rdb_session,
            limit=10,
            observe_interval=datetime.timedelta(seconds=0),
        )

        assert [candidate.id for candidate in candidates] == [runtime.id]
        assert disconnected is not None
        assert stopped_runtime is not None
        assert stopped_runtime.runner_state == RuntimeRunnerState.DISCONNECTED
        assert converged == []

    async def test_lifecycle_dispatch_candidates_skip_start_timeout_failure(
        self, rdb_session: AsyncSession
    ) -> None:
        """Control start timeout failure is excluded from redispatch candidates."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-start-timeout-no-retry-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-start-timeout-no-retry"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        await repo.record_runtime_failure(
            rdb_session,
            runtime.id,
            AgentRuntimeFailurePatch(
                generation=command.desired_generation,
                code="START_TIMEOUT",
                message="Runtime did not become running before timeout",
            ),
        )

        candidates = await repo.find_lifecycle_dispatch_candidates(
            rdb_session,
            limit=10,
            retry_delay=datetime.timedelta(seconds=0),
        )

        assert candidates == []

    async def test_mark_start_timeouts_marks_stale_start_failed(
        self, rdb_session: AsyncSession
    ) -> None:
        """Runtime exceeding timeout after START converges to failed in Control."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-start-timeout-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-start-timeout"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        dispatched = await repo.mark_lifecycle_dispatched(
            rdb_session,
            runtime.id,
            command.desired_generation,
        )
        assert dispatched is not None
        old_state_change_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(last_state_change_at=old_state_change_at)
        )

        timed_out = await repo.mark_start_timeouts(
            rdb_session,
            stale_threshold=datetime.timedelta(minutes=5),
            limit=10,
        )

        assert [item.id for item in timed_out] == [runtime.id]
        assert (
            timed_out[0].provider_observed_state == RuntimeProviderObservedState.FAILED
        )
        assert timed_out[0].failure_generation == command.desired_generation
        assert timed_out[0].failure_code == "START_TIMEOUT"

    async def test_mark_start_timeouts_skips_undispatched_generation(
        self, rdb_session: AsyncSession
    ) -> None:
        """A desired generation cannot time out before reaching its Provider."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-undispatched-timeout-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-runtime-undispatched-timeout"
        )
        repo = AgentRuntimeRepository()
        runtime = await repo.ensure_for_agent(rdb_session, agent_id)
        runtime = await repo.record_provider_connection_state(
            rdb_session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await repo.set_desired_state(
            rdb_session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        old_state_change_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await rdb_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(last_state_change_at=old_state_change_at)
        )

        timed_out = await repo.mark_start_timeouts(
            rdb_session,
            stale_threshold=datetime.timedelta(minutes=5),
            limit=10,
        )
        current = await repo.get_by_id(rdb_session, runtime.id)

        assert timed_out == []
        assert current is not None
        assert current.failure_code is None
