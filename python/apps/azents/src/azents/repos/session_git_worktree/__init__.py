"""Session Git worktree repository."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SessionGitWorktreeStatus
from azents.rdb.models.session_git_worktree import RDBSessionGitWorktree

from .data import SessionGitWorktree, SessionGitWorktreeCreate


class SessionGitWorktreeRepository:
    """Session Git worktree allocation repository."""

    async def create(
        self,
        session: AsyncSession,
        create: SessionGitWorktreeCreate,
    ) -> SessionGitWorktree:
        """Create a worktree allocation row."""
        rdb = RDBSessionGitWorktree(
            session_id=create.session_id,
            initialization_id=create.initialization_id,
            step_id=create.step_id,
            action_execution_id=create.action_execution_id,
            session_workspace_project_id=create.session_workspace_project_id,
            source_project_path=create.source_project_path,
            starting_ref=create.starting_ref,
            worktree_path=create.worktree_path,
            branch_name=create.branch_name,
            branch_created_by=create.branch_created_by,
            status=create.status,
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
        result = await session.execute(
            sa.select(RDBSessionGitWorktree)
            .where(RDBSessionGitWorktree.session_id == session_id)
            .order_by(RDBSessionGitWorktree.created_at, RDBSessionGitWorktree.id)
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
        result = await session.execute(
            sa.select(RDBSessionGitWorktree).where(
                RDBSessionGitWorktree.id == worktree_id,
                RDBSessionGitWorktree.session_id == session_id,
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
        result = await session.execute(
            sa.select(RDBSessionGitWorktree)
            .where(RDBSessionGitWorktree.session_id == session_id)
            .order_by(RDBSessionGitWorktree.created_at, RDBSessionGitWorktree.id)
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
            sa.select(RDBSessionGitWorktree.id).where(
                RDBSessionGitWorktree.id != excluding_id,
                sa.or_(
                    RDBSessionGitWorktree.worktree_path == worktree_path,
                    RDBSessionGitWorktree.branch_name == branch_name,
                ),
            )
        )
        return result.scalar_one_or_none() is not None

    async def update_target(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        worktree_path: str,
        branch_name: str,
    ) -> SessionGitWorktree:
        """Update pending allocation target names after collision suffixing."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        rdb.worktree_path = worktree_path
        rdb.branch_name = branch_name
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def mark_pending_for_retry(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
    ) -> SessionGitWorktree:
        """Reset a failed allocation so initialization can be retried."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        rdb.status = SessionGitWorktreeStatus.PENDING
        rdb.failure_summary = None
        rdb.cleanup_summary = None
        rdb.failed_at = None
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def mark_creating(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
    ) -> SessionGitWorktree:
        """Mark allocation as actively creating."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        rdb.status = SessionGitWorktreeStatus.CREATING
        rdb.failure_summary = None
        rdb.failed_at = None
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def mark_ready(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        base_commit: str,
        worktree_path: str,
        branch_name: str,
        ready_at: datetime.datetime,
    ) -> SessionGitWorktree:
        """Mark allocation ready after runner worktree creation."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        rdb.status = SessionGitWorktreeStatus.READY
        rdb.base_commit = base_commit
        rdb.worktree_path = worktree_path
        rdb.branch_name = branch_name
        rdb.failure_summary = None
        rdb.ready_at = ready_at
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def link_workspace_project(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        session_workspace_project_id: str,
    ) -> SessionGitWorktree:
        """Link allocation to its registered SessionWorkspaceProject row."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        rdb.session_workspace_project_id = session_workspace_project_id
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def mark_failed(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        failure_summary: str,
        failed_at: datetime.datetime,
    ) -> SessionGitWorktree:
        """Mark allocation failed."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        rdb.status = SessionGitWorktreeStatus.FAILED
        rdb.failure_summary = failure_summary
        rdb.failed_at = failed_at
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def mark_cleanup_pending(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
    ) -> SessionGitWorktree:
        """Mark allocation cleanup requested."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        if rdb.status is not SessionGitWorktreeStatus.CLEANED:
            rdb.status = SessionGitWorktreeStatus.CLEANUP_PENDING
            rdb.cleanup_summary = None
            rdb.cleaned_at = None
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def mark_cleaned(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        cleanup_summary: str,
        cleaned_at: datetime.datetime,
    ) -> SessionGitWorktree:
        """Mark allocation cleanup completed."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        rdb.status = SessionGitWorktreeStatus.CLEANED
        rdb.cleanup_summary = cleanup_summary
        rdb.cleaned_at = cleaned_at
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def mark_cleanup_failed(
        self,
        session: AsyncSession,
        *,
        worktree_id: str,
        cleanup_summary: str,
        failed_at: datetime.datetime,
    ) -> SessionGitWorktree:
        """Mark allocation cleanup failed."""
        rdb = await session.get(RDBSessionGitWorktree, worktree_id)
        if rdb is None:
            raise RuntimeError("SessionGitWorktree row is missing")
        rdb.status = SessionGitWorktreeStatus.CLEANUP_FAILED
        rdb.cleanup_summary = cleanup_summary
        rdb.failed_at = failed_at
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    def _build(self, rdb: RDBSessionGitWorktree) -> SessionGitWorktree:
        """Convert RDB row to domain model."""
        return SessionGitWorktree(
            id=rdb.id,
            session_id=rdb.session_id,
            initialization_id=rdb.initialization_id,
            step_id=rdb.step_id,
            action_execution_id=rdb.action_execution_id,
            session_workspace_project_id=rdb.session_workspace_project_id,
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
