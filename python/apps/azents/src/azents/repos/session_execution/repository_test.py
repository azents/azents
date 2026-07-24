"""Canonical Session execution projection repository tests."""

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import CanonicalExecutionSnapshotError, SessionExecutionRepository


async def _create_execution_subject(
    session: AsyncSession,
    *,
    handle: str,
) -> tuple[RDBAgentSession, str]:
    """Create a complete active root Session authority fixture."""
    workspace_repository = WorkspaceRepository()
    result = await workspace_repository.create(
        session,
        WorkspaceCreate(name="Session execution test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await workspace_repository.resolve_id(session, handle)
    assert workspace_id is not None

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{handle}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Session execution test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model",
        ),
    )
    session.add(agent)
    await session.flush()

    created = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    agent_session = await session.get(RDBAgentSession, created.id)
    assert agent_session is not None
    return agent_session, agent.id


class TestSessionExecutionRepository:
    """Fail-closed tests for the canonical Session execution projection."""

    async def test_load_canonical_snapshot_rejects_stale_owner_generation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A wake-up cannot execute after durable ownership changes."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-stale-owner",
        )

        with pytest.raises(
            CanonicalExecutionSnapshotError,
            match="owner generation is stale",
        ):
            await SessionExecutionRepository().load_canonical_snapshot(
                rdb_session,
                session_id=agent_session.id,
                owner_generation=agent_session.owner_generation + 1,
            )

    async def test_load_canonical_snapshot_rejects_incomplete_pending_command(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A partial durable command is never projected for execution."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-partial-command",
        )
        agent_session.pending_command_id = "command-001"
        agent_session.pending_command_name = "compact"
        agent_session.pending_command_payload = {}
        agent_session.pending_command_created_at = None
        await rdb_session.flush()

        with pytest.raises(
            CanonicalExecutionSnapshotError,
            match="Pending command is incomplete",
        ):
            await SessionExecutionRepository().load_canonical_snapshot(
                rdb_session,
                session_id=agent_session.id,
                owner_generation=agent_session.owner_generation,
            )

    async def test_load_canonical_snapshot_rejects_invalid_pending_idle_run(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A pending idle fence must reference this Session's completed Run."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-invalid-idle",
        )
        agent_session.pending_idle_continuation_run_id = "missing-run-001"
        await rdb_session.flush()

        with pytest.raises(
            CanonicalExecutionSnapshotError,
            match="Pending idle continuation Run is invalid",
        ):
            await SessionExecutionRepository().load_canonical_snapshot(
                rdb_session,
                session_id=agent_session.id,
                owner_generation=agent_session.owner_generation,
            )

    async def test_load_canonical_snapshot_projects_only_matching_recoverable_run(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """The durable snapshot carries the unique Session-local recoverable Run."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-recoverable-run",
        )
        run = RDBAgentRun(
            session_id=agent_session.id,
            run_index=1,
            parent_agent_run_id=None,
            status=AgentRunStatus.RUNNING,
        )
        rdb_session.add(run)
        await rdb_session.flush()

        snapshot = await SessionExecutionRepository().load_canonical_snapshot(
            rdb_session,
            session_id=agent_session.id,
            owner_generation=agent_session.owner_generation,
        )

        assert snapshot.session_id == agent_session.id
        assert snapshot.agent_id == agent_session.agent_id
        assert snapshot.recoverable_run_id == run.id
        assert snapshot.recoverable_run_status is AgentRunStatus.RUNNING
