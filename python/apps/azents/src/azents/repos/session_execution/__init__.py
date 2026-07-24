"""Postgres projection for canonical Session execution authority."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionStatus,
    SessionAgentKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.input_buffer import RDBInputBuffer
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.workspace import RDBWorkspace

from .data import CanonicalExecutionSnapshot, PendingCommandSnapshot


class CanonicalExecutionSnapshotError(ValueError):
    """Raised when durable Session execution authority is invalid or stale."""


class CanonicalExecutionOwnerGenerationStaleError(CanonicalExecutionSnapshotError):
    """Raised when a Worker no longer owns the claimed Session generation."""


class SessionExecutionRepository:
    """Load the canonical durable identity for one claimed Session execution."""

    async def load_canonical_snapshot(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        owner_generation: int,
    ) -> CanonicalExecutionSnapshot:
        """Lock and validate execution authority and expected durable work."""
        agent_session = await session.scalar(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .with_for_update()
        )
        if agent_session is None:
            raise CanonicalExecutionSnapshotError("AgentSession not found")
        if agent_session.status is not AgentSessionStatus.ACTIVE:
            raise CanonicalExecutionSnapshotError("AgentSession is not active")
        if agent_session.owner_generation != owner_generation:
            raise CanonicalExecutionOwnerGenerationStaleError(
                "Session owner generation is stale"
            )

        agent = await session.get(RDBAgent, agent_session.agent_id)
        if agent is None:
            raise CanonicalExecutionSnapshotError("Session Agent not found")
        if agent.workspace_id != agent_session.workspace_id:
            raise CanonicalExecutionSnapshotError("Session Agent Workspace mismatch")
        if (
            agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or not agent.enabled
        ):
            raise CanonicalExecutionSnapshotError("Session Agent is not active")
        workspace = await session.get(RDBWorkspace, agent_session.workspace_id)
        if workspace is None:
            raise CanonicalExecutionSnapshotError("Session Workspace not found")

        current = await session.scalar(
            sa.select(RDBSessionAgent).where(
                RDBSessionAgent.agent_session_id == session_id
            )
        )
        if current is None:
            raise CanonicalExecutionSnapshotError("SessionAgent tree node not found")
        root = await session.get(RDBSessionAgent, current.root_session_agent_id)
        if root is None:
            raise CanonicalExecutionSnapshotError("Root SessionAgent not found")
        if (
            root.kind is not SessionAgentKind.ROOT
            or root.root_session_agent_id != root.id
            or root.parent_session_agent_id is not None
        ):
            raise CanonicalExecutionSnapshotError(
                "Root SessionAgent lineage is invalid"
            )
        if current.context_id != root.context_id:
            raise CanonicalExecutionSnapshotError(
                "SessionAgent context lineage is invalid"
            )
        context = await session.get(RDBSessionAgentContext, current.context_id)
        if context is None:
            raise CanonicalExecutionSnapshotError("SessionAgentContext not found")
        if (
            context.root_session_agent_id != root.id
            or context.agent_id != agent_session.agent_id
            or context.workspace_id != agent_session.workspace_id
        ):
            raise CanonicalExecutionSnapshotError(
                "SessionAgentContext authority mismatch"
            )
        root_session = await session.get(RDBAgentSession, root.agent_session_id)
        if root_session is None or root_session.status is not AgentSessionStatus.ACTIVE:
            raise CanonicalExecutionSnapshotError("Root AgentSession is not active")
        if (
            root_session.agent_id != agent_session.agent_id
            or root_session.workspace_id != agent_session.workspace_id
        ):
            raise CanonicalExecutionSnapshotError(
                "Root AgentSession authority mismatch"
            )
        self._validate_execution_mode(agent_session, current, root)
        await self._validate_parent_lineage(session, current, root)

        oldest_input = await session.scalar(
            sa.select(RDBInputBuffer.id)
            .where(RDBInputBuffer.session_id == session_id)
            .order_by(RDBInputBuffer.id.asc())
            .limit(1)
        )
        pending_command = self._pending_command(agent_session)
        recoverable_runs = list(
            (
                await session.scalars(
                    sa.select(RDBAgentRun)
                    .where(
                        RDBAgentRun.session_id == session_id,
                        RDBAgentRun.status.in_(
                            (AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
                        ),
                    )
                    .order_by(RDBAgentRun.created_at.asc())
                )
            ).all()
        )
        if len(recoverable_runs) > 1:
            raise CanonicalExecutionSnapshotError("Multiple recoverable AgentRuns")
        recoverable_run = recoverable_runs[0] if recoverable_runs else None
        pending_idle_run_id = agent_session.pending_idle_continuation_run_id
        if pending_idle_run_id is not None:
            pending_idle_run = await session.get(RDBAgentRun, pending_idle_run_id)
            if (
                pending_idle_run is None
                or pending_idle_run.session_id != session_id
                or pending_idle_run.status is not AgentRunStatus.COMPLETED
            ):
                raise CanonicalExecutionSnapshotError(
                    "Pending idle continuation Run is invalid"
                )

        return CanonicalExecutionSnapshot(
            session_id=session_id,
            root_session_id=root_session.id,
            workspace_id=workspace.id,
            workspace_handle=workspace.handle,
            agent_id=agent.id,
            session_agent_id=current.id,
            root_session_agent_id=root.id,
            session_agent_context_id=context.id,
            execution_mode=agent_session.session_kind,
            owner_generation=owner_generation,
            fifo_input_buffer_id=oldest_input,
            pending_command=pending_command,
            recoverable_run_id=(
                recoverable_run.id if recoverable_run is not None else None
            ),
            recoverable_run_status=(
                recoverable_run.status if recoverable_run is not None else None
            ),
            pending_idle_continuation_run_id=pending_idle_run_id,
        )

    def _pending_command(
        self, agent_session: RDBAgentSession
    ) -> PendingCommandSnapshot | None:
        """Return a complete command or reject a partially persisted command."""
        values = (
            agent_session.pending_command_id,
            agent_session.pending_command_name,
            agent_session.pending_command_payload,
            agent_session.pending_command_created_at,
        )
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise CanonicalExecutionSnapshotError("Pending command is incomplete")
        assert agent_session.pending_command_id is not None
        assert agent_session.pending_command_name is not None
        assert agent_session.pending_command_payload is not None
        assert agent_session.pending_command_created_at is not None
        return PendingCommandSnapshot(
            id=agent_session.pending_command_id,
            name=agent_session.pending_command_name,
            payload=agent_session.pending_command_payload,
            requester_user_id=agent_session.pending_command_requester_user_id,
            created_at=agent_session.pending_command_created_at,
        )

    def _validate_execution_mode(
        self,
        agent_session: RDBAgentSession,
        current: RDBSessionAgent,
        root: RDBSessionAgent,
    ) -> None:
        """Require root/subagent Session records to match their tree nodes."""
        if agent_session.session_kind is AgentSessionKind.ROOT:
            if current.id != root.id or current.kind is not SessionAgentKind.ROOT:
                raise CanonicalExecutionSnapshotError(
                    "Root SessionAgent mode is invalid"
                )
            return
        if agent_session.session_kind is AgentSessionKind.SUBAGENT:
            if (
                current.id == root.id
                or current.kind is not SessionAgentKind.SUBAGENT
                or current.parent_session_agent_id is None
            ):
                raise CanonicalExecutionSnapshotError(
                    "Subagent SessionAgent mode is invalid"
                )
            return
        raise CanonicalExecutionSnapshotError("Unknown AgentSession execution mode")

    async def _validate_parent_lineage(
        self,
        session: AsyncSession,
        current: RDBSessionAgent,
        root: RDBSessionAgent,
    ) -> None:
        """Reject detached, cross-root, or cyclic SessionAgent parent lineages."""
        seen = {current.id}
        node = current
        while node.id != root.id:
            parent_id = node.parent_session_agent_id
            if parent_id is None:
                raise CanonicalExecutionSnapshotError(
                    "SessionAgent parent lineage is broken"
                )
            if parent_id in seen:
                raise CanonicalExecutionSnapshotError(
                    "SessionAgent parent lineage is cyclic"
                )
            parent = await session.get(RDBSessionAgent, parent_id)
            if (
                parent is None
                or parent.root_session_agent_id != root.id
                or parent.context_id != root.context_id
            ):
                raise CanonicalExecutionSnapshotError(
                    "SessionAgent parent authority mismatch"
                )
            seen.add(parent.id)
            node = parent
