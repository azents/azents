"""Session Git worktree repository."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SessionGitWorktreeStatus
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContextGitWorktree

from .data import SessionGitWorktree, SessionGitWorktreeCreate


class SessionGitWorktreeRepository:
    """Session Git worktree allocation repository."""

    async def create(
        self,
        session: AsyncSession,
        create: SessionGitWorktreeCreate,
    ) -> SessionGitWorktree:
        """Create a worktree allocation row."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=create.session_id,
        )
        session_agent_id = await self._get_session_agent_id(
            session,
            session_id=create.session_id,
        )
        rdb = RDBSessionAgentContextGitWorktree(
            session_agent_context_id=context_id,
            source_project_path=create.source_project_path,
            starting_ref=create.starting_ref,
            worktree_path=create.worktree_path,
            branch_name=create.branch_name,
            branch_created_by=create.branch_created_by,
            status=create.status,
            created_by_session_agent_id=session_agent_id,
            created_by_agent_session_id=create.session_id,
            action_execution_id=create.action_execution_id,
            session_agent_context_project_id=create.session_workspace_project_id,
        )
        rdb.id = create.id
        session.add(rdb)
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def get_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> SessionGitWorktree | None:
        """Fetch the earliest worktree allocation by AgentSession ID."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = await session.execute(
            sa.select(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.session_agent_context_id == context_id
            )
            .order_by(
                RDBSessionAgentContextGitWorktree.created_at,
                RDBSessionAgentContextGitWorktree.id,
            )
            .limit(1)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_id_for_session(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        session_id: str,
    ) -> SessionGitWorktree | None:
        """Fetch one worktree allocation by ID and AgentSession ID."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = await session.execute(
            sa.select(RDBSessionAgentContextGitWorktree).where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.session_agent_context_id
                == context_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def lock_by_id(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
    ) -> SessionGitWorktree | None:
        """Fetch one allocation under a row lock for lifecycle transitions."""
        rdb = await session.scalar(
            sa.select(RDBSessionAgentContextGitWorktree)
            .where(RDBSessionAgentContextGitWorktree.id == worktree_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return None if rdb is None else self._build(rdb)

    async def get_by_action_execution_id(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> SessionGitWorktree | None:
        """Fetch one worktree allocation by action execution identity."""
        result = await session.execute(
            sa.select(RDBSessionAgentContextGitWorktree).where(
                RDBSessionAgentContextGitWorktree.action_execution_id
                == action_execution_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[SessionGitWorktree]:
        """List worktree allocations for an AgentSession."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = await session.execute(
            sa.select(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.session_agent_context_id == context_id
            )
            .order_by(
                RDBSessionAgentContextGitWorktree.created_at,
                RDBSessionAgentContextGitWorktree.id,
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def target_exists(
        self,
        session: AsyncSession,
        *,
        worktree_path: str,
        branch_name: str,
        excluding_id: str,
    ) -> bool:
        """Return whether another allocation already owns a target path or branch."""
        result = await session.execute(
            sa.select(RDBSessionAgentContextGitWorktree.id).where(
                RDBSessionAgentContextGitWorktree.id != excluding_id,
                sa.or_(
                    RDBSessionAgentContextGitWorktree.worktree_path == worktree_path,
                    RDBSessionAgentContextGitWorktree.branch_name == branch_name,
                ),
            )
        )
        return result.scalar_one_or_none() is not None

    async def update_target_if_pending(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        worktree_path: str,
        branch_name: str,
    ) -> SessionGitWorktree | None:
        """Update target names only while the action owns a pending allocation."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status
                == SessionGitWorktreeStatus.PENDING,
            )
            .values(
                worktree_path=worktree_path,
                branch_name=branch_name,
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        return await self._get_after_conditional_update(session, updated_id)

    async def mark_pending_after_collision_if_creating(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
    ) -> SessionGitWorktree | None:
        """Return a creating allocation to pending for a collision retry."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status
                == SessionGitWorktreeStatus.CREATING,
            )
            .values(
                status=SessionGitWorktreeStatus.PENDING,
                failure_summary=None,
                failed_at=None,
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        return await self._get_after_conditional_update(session, updated_id)

    async def mark_creating_if_pending(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
    ) -> SessionGitWorktree | None:
        """Atomically claim a pending allocation for Runner creation."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status
                == SessionGitWorktreeStatus.PENDING,
            )
            .values(
                status=SessionGitWorktreeStatus.CREATING,
                failure_summary=None,
                failed_at=None,
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        return await self._get_after_conditional_update(session, updated_id)

    async def mark_ready_if_creating(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        base_commit: str,
        worktree_path: str,
        branch_name: str,
        ready_at: datetime.datetime,
    ) -> SessionGitWorktree | None:
        """Atomically mark a still-creating allocation ready."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status
                == SessionGitWorktreeStatus.CREATING,
            )
            .values(
                status=SessionGitWorktreeStatus.READY,
                base_commit=base_commit,
                worktree_path=worktree_path,
                branch_name=branch_name,
                failure_summary=None,
                ready_at=ready_at,
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        rdb = await session.scalar(
            sa.select(RDBSessionAgentContextGitWorktree)
            .where(RDBSessionAgentContextGitWorktree.id == updated_id)
            .execution_options(populate_existing=True)
        )
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row disappeared after update")
        return self._build(rdb)

    async def link_workspace_project_if_ready(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        session_workspace_project_id: str,
    ) -> SessionGitWorktree | None:
        """Link a Project only while the allocation remains ready."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status
                == SessionGitWorktreeStatus.READY,
            )
            .values(
                session_agent_context_project_id=session_workspace_project_id,
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        return await self._get_after_conditional_update(session, updated_id)

    async def mark_failed_if_active(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        failure_summary: str,
        failed_at: datetime.datetime,
    ) -> SessionGitWorktree | None:
        """Mark an action-owned allocation failed without overriding cleanup."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status.in_(
                    (
                        SessionGitWorktreeStatus.PENDING,
                        SessionGitWorktreeStatus.CREATING,
                        SessionGitWorktreeStatus.READY,
                    )
                ),
            )
            .values(
                status=SessionGitWorktreeStatus.FAILED,
                failure_summary=failure_summary,
                failed_at=failed_at,
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        return await self._get_after_conditional_update(session, updated_id)

    async def mark_cleanup_pending(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
    ) -> SessionGitWorktree:
        """Request cleanup without overwriting a concurrently cleaned row."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status
                != SessionGitWorktreeStatus.CLEANED,
            )
            .values(
                status=SessionGitWorktreeStatus.CLEANUP_PENDING,
                cleanup_summary=None,
                cleaned_at=None,
                updated_at=sa.func.clock_timestamp(),
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is not None:
            await session.flush()
            return await self._get_after_conditional_update(session, updated_id)
        rdb = await session.scalar(
            sa.select(RDBSessionAgentContextGitWorktree)
            .where(RDBSessionAgentContextGitWorktree.id == worktree_id)
            .execution_options(populate_existing=True)
        )
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        return self._build(rdb)

    async def reopen_cleaned_after_late_create(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
    ) -> SessionGitWorktree | None:
        """Reopen cleanup when a create result arrives after cleanup completed."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status
                == SessionGitWorktreeStatus.CLEANED,
            )
            .values(
                status=SessionGitWorktreeStatus.CLEANUP_PENDING,
                cleanup_summary=None,
                cleaned_at=None,
                updated_at=sa.func.clock_timestamp(),
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        return await self._get_after_conditional_update(session, updated_id)

    async def mark_cleaned_if_cleanup_owned(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        cleanup_summary: str,
        cleaned_at: datetime.datetime,
        expected_updated_at: datetime.datetime,
    ) -> SessionGitWorktree | None:
        """Mark cleanup completed without reviving non-cleanup authority."""
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(
                RDBSessionAgentContextGitWorktree.id == worktree_id,
                RDBSessionAgentContextGitWorktree.status.in_(
                    (
                        SessionGitWorktreeStatus.CLEANUP_PENDING,
                        SessionGitWorktreeStatus.CLEANUP_FAILED,
                    )
                ),
                RDBSessionAgentContextGitWorktree.updated_at == expected_updated_at,
            )
            .values(
                status=SessionGitWorktreeStatus.CLEANED,
                cleanup_summary=cleanup_summary,
                cleaned_at=cleaned_at,
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        return await self._get_after_conditional_update(session, updated_id)

    async def mark_cleanup_failed_if_pending(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        cleanup_summary: str,
        failed_at: datetime.datetime,
        expected_updated_at: datetime.datetime | None = None,
    ) -> SessionGitWorktree | None:
        """Mark only an in-flight cleanup failed; completed cleanup always wins."""
        conditions = [
            RDBSessionAgentContextGitWorktree.id == worktree_id,
            RDBSessionAgentContextGitWorktree.status
            == SessionGitWorktreeStatus.CLEANUP_PENDING,
        ]
        if expected_updated_at is not None:
            conditions.append(
                RDBSessionAgentContextGitWorktree.updated_at == expected_updated_at
            )
        updated_id = await session.scalar(
            sa.update(RDBSessionAgentContextGitWorktree)
            .where(*conditions)
            .values(
                status=SessionGitWorktreeStatus.CLEANUP_FAILED,
                cleanup_summary=cleanup_summary,
                failed_at=failed_at,
            )
            .returning(RDBSessionAgentContextGitWorktree.id)
        )
        if updated_id is None:
            return None
        await session.flush()
        return await self._get_after_conditional_update(session, updated_id)

    async def _get_context_id_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> str:
        """Fetch SessionAgentContext ID for an AgentSession."""
        result = await session.execute(
            sa.select(RDBSessionAgent.context_id).where(
                RDBSessionAgent.agent_session_id == session_id,
            )
        )
        context_id = result.scalar_one_or_none()
        if context_id is None:
            raise ValueError("SessionAgentContext not found for AgentSession")
        return context_id

    async def _get_session_agent_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> str:
        """Fetch SessionAgent ID for an AgentSession."""
        result = await session.execute(
            sa.select(RDBSessionAgent.id).where(
                RDBSessionAgent.agent_session_id == session_id,
            )
        )
        session_agent_id = result.scalar_one_or_none()
        if session_agent_id is None:
            raise ValueError("SessionAgent not found for AgentSession")
        return session_agent_id

    async def _get_after_conditional_update(
        self,
        session: AsyncSession,
        updated_id: str,
    ) -> SessionGitWorktree:
        """Reload a row changed by a conditional lifecycle update."""
        rdb = await session.scalar(
            sa.select(RDBSessionAgentContextGitWorktree)
            .where(RDBSessionAgentContextGitWorktree.id == updated_id)
            .execution_options(populate_existing=True)
        )
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row disappeared after update")
        return self._build(rdb)

    def _build(
        self,
        rdb: RDBSessionAgentContextGitWorktree,
    ) -> SessionGitWorktree:
        """Convert RDB row to domain model."""
        if rdb.created_by_agent_session_id is None:
            raise ValueError("SessionGitWorktree creator AgentSession is missing")
        return SessionGitWorktree(
            id=rdb.id,
            session_id=rdb.created_by_agent_session_id,
            session_agent_context_id=rdb.session_agent_context_id,
            created_by_session_agent_id=rdb.created_by_session_agent_id,
            created_by_agent_session_id=rdb.created_by_agent_session_id,
            action_execution_id=rdb.action_execution_id,
            session_workspace_project_id=rdb.session_agent_context_project_id,
            source_project_path=rdb.source_project_path,
            starting_ref=rdb.starting_ref,
            base_commit=rdb.base_commit,
            worktree_path=rdb.worktree_path,
            branch_name=rdb.branch_name,
            branch_created_by=rdb.branch_created_by,
            status=rdb.status,
            failure_summary=rdb.failure_summary,
            cleanup_summary=rdb.cleanup_summary,
            ready_at=rdb.ready_at,
            failed_at=rdb.failed_at,
            cleaned_at=rdb.cleaned_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
