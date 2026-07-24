"""AgentRuntimeRepository tests."""

import datetime

import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_runtime.data import AgentRuntimeFailurePatch
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
    *,
    runtime_provider_id: str | None = None,
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
        runtime_provider_id=runtime_provider_id,
    )
    session.add(agent)
    await session.flush()
    return agent.id


class TestAgentRuntimeRepository:
    """AgentRuntimeRepository tests."""

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

    async def test_ensure_for_agent_uses_default_provider_for_new_runtime(
        self, rdb_session: AsyncSession
    ) -> None:
        """Create Runtime with default provider when Agent provider is empty."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-default-provider-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-default-provider",
        )
        repo = AgentRuntimeRepository()

        runtime = await repo.ensure_for_agent(
            rdb_session,
            agent_id,
            default_runtime_provider_id="system-kubernetes",
        )

        assert runtime.runtime_provider_id == "system-kubernetes"

    async def test_ensure_for_agent_backfills_default_provider_for_existing_runtime(
        self, rdb_session: AsyncSession
    ) -> None:
        """Fill default provider when existing Runtime provider is empty."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-backfill-provider-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-backfill-provider",
        )
        repo = AgentRuntimeRepository()
        created = await repo.ensure_for_agent(rdb_session, agent_id)
        assert created.runtime_provider_id is None

        runtime = await repo.ensure_for_agent(
            rdb_session,
            agent_id,
            default_runtime_provider_id="system-kubernetes",
        )

        assert runtime.id == created.id
        assert runtime.runtime_provider_id == "system-kubernetes"

    async def test_ensure_for_agent_preserves_explicit_provider(
        self, rdb_session: AsyncSession
    ) -> None:
        """Explicit provider on Agent is not overwritten by default provider."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-runtime-explicit-provider-ws"
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "agent-runtime-explicit-provider",
            runtime_provider_id="workspace-provider",
        )
        repo = AgentRuntimeRepository()

        runtime = await repo.ensure_for_agent(
            rdb_session,
            agent_id,
            default_runtime_provider_id="system-kubernetes",
        )

        assert runtime.runtime_provider_id == "workspace-provider"

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
        requested = await repo.request_terminal_delete(rdb_session, runtime.id)

        assert requested is not None
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
        finalizable = await repo.get_terminal_delete_acknowledged(
            rdb_session, runtime.id
        )
        late_runner = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            runner_generation=1,
        )
        late_provider = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            provider_generation=2,
            observed_generation=requested.desired_generation,
            workspace_path="/workspace/agent",
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

    async def test_record_provider_and_runner_state(
        self, rdb_session: AsyncSession
    ) -> None:
        """Store Provider/Runner observed state and workspace path."""
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
            workspace_path="/workspace/agent",
        )
        runner_runtime = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.READY,
            4,
            failure=AgentRuntimeFailurePatch(
                generation=4, code="runner_failed", message="Runner failed"
            ),
        )

        assert provider_runtime is not None
        assert provider_runtime.provider_observed_state == (
            RuntimeProviderObservedState.RUNNING
        )
        assert provider_runtime.provider_observed_generation == 3
        assert provider_runtime.workspace_path == "/workspace/agent"
        assert runner_runtime is not None
        assert runner_runtime.runner_state == RuntimeRunnerState.READY
        assert runner_runtime.runner_generation == 4
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
            workspace_path="/workspace/current",
        )
        assert current is not None

        stale = await repo.record_provider_observed_state(
            rdb_session,
            runtime.id,
            RuntimeProviderObservedState.FAILED,
            1,
            command.desired_generation - 1,
            workspace_path="/workspace/stale",
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
        assert reloaded.workspace_path == "/workspace/current"
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
            workspace_path="/workspace/current",
        )

        assert updated is not None
        assert updated.provider_generation == 1
        assert updated.provider_observed_generation == command.desired_generation
        assert updated.provider_observed_state == RuntimeProviderObservedState.RUNNING
        assert updated.workspace_path == "/workspace/current"

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
        )
        assert current is not None

        stale = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.DISCONNECTED,
            1,
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
        )
        assert current is not None

        disconnected = await repo.record_runner_state(
            rdb_session,
            runtime.id,
            RuntimeRunnerState.DISCONNECTED,
            2,
        )

        assert disconnected is not None
        assert disconnected.runner_generation == 2
        assert disconnected.runner_state == RuntimeRunnerState.DISCONNECTED

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
            runtime_provider_id="provider-1",
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
        dispatched = await repo.mark_provider_observe_dispatched(
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
            runtime_provider_id="provider-1",
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
