"""Session Workspace Project repository."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionStatus,
    AgentSessionKind,
    AgentSessionStatus,
    GitWorktreePathClaimOwnerKind,
    GitWorktreePathClaimState,
    SessionGitWorktreeStatus,
)
from azents.rdb.models.action_execution import RDBActionExecution
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.git_worktree_cleanup_claim import (
    RDBGitWorktreePathClaim,
)
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import (
    RDBSessionAgentContext,
    RDBSessionAgentContextGitWorktree,
    RDBSessionAgentContextProject,
)

from .data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
)


class SessionWorkspaceProjectRepository:
    """Session Workspace Project CRUD repository."""

    async def try_claim_agent_git_worktree(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        action_execution_id: str,
        owner_generation: int,
        worktree_path: str,
    ) -> bool:
        """Reserve one exact managed path for an Agent removal action."""
        await self.acquire_runtime_path_coordination_lock(
            session,
            runtime_id=runtime_id,
        )
        claim_paths = await self._list_blocking_cleanup_claim_paths(
            session,
            runtime_id=runtime_id,
        )
        if any(_paths_overlap(worktree_path, claim_path) for claim_path in claim_paths):
            return False
        await self.acquire_runtime_worktree_path_lock(
            session,
            runtime_id=runtime_id,
            worktree_path=worktree_path,
        )
        existing = await session.execute(
            sa.select(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.agent_runtime_id == runtime_id,
                RDBGitWorktreePathClaim.worktree_path == worktree_path,
            )
        )
        claim = existing.scalar_one_or_none()
        if claim is not None and await self._claim_blocks_path(session, claim=claim):
            return False
        now = datetime.now(UTC)
        if claim is None:
            claim = RDBGitWorktreePathClaim(
                agent_runtime_id=runtime_id,
                worktree_path=worktree_path,
                owner_kind=GitWorktreePathClaimOwnerKind.AGENT_ACTION,
                action_execution_id=action_execution_id,
                root_session_id=None,
                owner_generation=owner_generation,
                discovery_fingerprint=None,
                state=GitWorktreePathClaimState.CLAIMED,
                reason_code=None,
                summary=None,
                lease_until=now + timedelta(minutes=6),
            )
            session.add(claim)
        else:
            claim.owner_kind = GitWorktreePathClaimOwnerKind.AGENT_ACTION
            claim.action_execution_id = action_execution_id
            claim.root_session_id = None
            claim.owner_generation = owner_generation
            claim.discovery_fingerprint = None
            claim.state = GitWorktreePathClaimState.CLAIMED
            claim.reason_code = None
            claim.summary = None
            claim.lease_until = now + timedelta(minutes=6)
        await session.flush()
        return True

    async def mark_agent_git_worktree_claim_removing(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        worktree_path: str,
    ) -> None:
        """Transition one Agent removal claim into Runner mutation state."""
        await session.execute(
            sa.update(RDBGitWorktreePathClaim)
            .where(
                RDBGitWorktreePathClaim.owner_kind
                == GitWorktreePathClaimOwnerKind.AGENT_ACTION,
                RDBGitWorktreePathClaim.action_execution_id == action_execution_id,
                RDBGitWorktreePathClaim.worktree_path == worktree_path,
                RDBGitWorktreePathClaim.state == GitWorktreePathClaimState.CLAIMED,
            )
            .values(
                state=GitWorktreePathClaimState.REMOVING,
                lease_until=datetime.now(UTC) + timedelta(minutes=6),
            )
        )
        await session.flush()

    async def release_agent_git_worktree_claim(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        worktree_path: str,
        state: GitWorktreePathClaimState,
    ) -> None:
        """Record one Agent removal claim as terminal and non-blocking."""
        await session.execute(
            sa.update(RDBGitWorktreePathClaim)
            .where(
                RDBGitWorktreePathClaim.owner_kind
                == GitWorktreePathClaimOwnerKind.AGENT_ACTION,
                RDBGitWorktreePathClaim.action_execution_id == action_execution_id,
                RDBGitWorktreePathClaim.worktree_path == worktree_path,
            )
            .values(
                state=state,
                lease_until=datetime.now(UTC),
            )
        )
        await session.flush()

    async def release_nonremoving_agent_git_worktree_claims(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> None:
        """Release Agent claims that cannot own an in-flight Runner removal."""
        await session.execute(
            sa.delete(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.owner_kind
                == GitWorktreePathClaimOwnerKind.AGENT_ACTION,
                RDBGitWorktreePathClaim.action_execution_id == action_execution_id,
                RDBGitWorktreePathClaim.state != GitWorktreePathClaimState.REMOVING,
            )
        )
        await session.flush()

    async def try_claim_orphan_git_worktree(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        action_execution_id: str,
        owner_generation: int,
        worktree_path: str,
        discovery_fingerprint: str,
    ) -> Literal["claimed", "active_connection", "cleanup_in_progress"]:
        """Atomically protect or reserve one worktree path for manual removal."""
        await self.acquire_runtime_path_coordination_lock(
            session,
            runtime_id=runtime_id,
        )
        protected_paths = await self.list_active_connected_paths_by_runtime_id(
            session,
            runtime_id=runtime_id,
        )
        if any(
            _paths_overlap(worktree_path, protected_path)
            for protected_path in protected_paths
        ):
            return "active_connection"
        claim_paths = await self._list_blocking_cleanup_claim_paths(
            session,
            runtime_id=runtime_id,
        )
        if any(_paths_overlap(worktree_path, claim_path) for claim_path in claim_paths):
            return "cleanup_in_progress"
        await self.acquire_runtime_worktree_path_lock(
            session,
            runtime_id=runtime_id,
            worktree_path=worktree_path,
        )
        existing = await session.execute(
            sa.select(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.agent_runtime_id == runtime_id,
                RDBGitWorktreePathClaim.worktree_path == worktree_path,
            )
        )
        claim = existing.scalar_one_or_none()
        now = datetime.now(UTC)
        if claim is not None and await self._claim_blocks_path(session, claim=claim):
            return "cleanup_in_progress"
        if claim is None:
            claim = RDBGitWorktreePathClaim(
                agent_runtime_id=runtime_id,
                worktree_path=worktree_path,
                owner_kind=GitWorktreePathClaimOwnerKind.MANUAL_ACTION,
                action_execution_id=action_execution_id,
                root_session_id=None,
                owner_generation=owner_generation,
                discovery_fingerprint=discovery_fingerprint,
                state=GitWorktreePathClaimState.CLAIMED,
                reason_code=None,
                summary=None,
                lease_until=now + timedelta(minutes=6),
            )
            session.add(claim)
        else:
            claim.owner_kind = GitWorktreePathClaimOwnerKind.MANUAL_ACTION
            claim.action_execution_id = action_execution_id
            claim.root_session_id = None
            claim.owner_generation = owner_generation
            claim.discovery_fingerprint = discovery_fingerprint
            claim.state = GitWorktreePathClaimState.CLAIMED
            claim.reason_code = None
            claim.summary = None
            claim.lease_until = now + timedelta(minutes=6)
        await session.flush()
        return "claimed"

    async def mark_orphan_git_worktree_claim_removing(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        worktree_path: str,
    ) -> None:
        """Transition one manual cleanup claim into its Runner I/O state."""
        await session.execute(
            sa.update(RDBGitWorktreePathClaim)
            .where(
                RDBGitWorktreePathClaim.action_execution_id == action_execution_id,
                RDBGitWorktreePathClaim.worktree_path == worktree_path,
                RDBGitWorktreePathClaim.state == GitWorktreePathClaimState.CLAIMED,
            )
            .values(
                state=GitWorktreePathClaimState.REMOVING,
                lease_until=datetime.now(UTC) + timedelta(minutes=6),
            )
        )
        await session.flush()

    async def release_orphan_git_worktree_claim(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        worktree_path: str,
        state: GitWorktreePathClaimState,
    ) -> None:
        """Record one terminal worktree cleanup claim as non-blocking."""
        await session.execute(
            sa.update(RDBGitWorktreePathClaim)
            .where(
                RDBGitWorktreePathClaim.action_execution_id == action_execution_id,
                RDBGitWorktreePathClaim.worktree_path == worktree_path,
            )
            .values(
                state=state,
                lease_until=datetime.now(UTC),
            )
        )
        await session.flush()

    async def release_orphan_git_worktree_claims(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> None:
        """Release all cleanup claims held by a terminal action execution."""
        await session.execute(
            sa.delete(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.action_execution_id == action_execution_id,
            )
        )
        await session.flush()

    async def release_nonremoving_orphan_git_worktree_claims(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> None:
        """Release claims that cannot still own an in-flight Runner removal."""
        await session.execute(
            sa.delete(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.action_execution_id == action_execution_id,
                RDBGitWorktreePathClaim.state != GitWorktreePathClaimState.REMOVING,
            )
        )
        await session.flush()

    async def try_claim_archive_git_worktree(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        root_session_id: str,
        worktree_path: str,
    ) -> bool:
        """Reserve one archived worktree path before best-effort removal."""
        await self.acquire_runtime_path_coordination_lock(
            session,
            runtime_id=runtime_id,
        )
        await self.acquire_runtime_worktree_path_lock(
            session,
            runtime_id=runtime_id,
            worktree_path=worktree_path,
        )
        existing = await session.execute(
            sa.select(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.agent_runtime_id == runtime_id,
                RDBGitWorktreePathClaim.worktree_path == worktree_path,
            )
        )
        claim = existing.scalar_one_or_none()
        if claim is not None and await self._claim_blocks_path(session, claim=claim):
            return False
        now = datetime.now(UTC)
        if claim is None:
            session.add(
                RDBGitWorktreePathClaim(
                    agent_runtime_id=runtime_id,
                    worktree_path=worktree_path,
                    owner_kind=GitWorktreePathClaimOwnerKind.ARCHIVE_CLEANUP,
                    action_execution_id=None,
                    root_session_id=root_session_id,
                    owner_generation=None,
                    discovery_fingerprint=None,
                    state=GitWorktreePathClaimState.CLAIMED,
                    reason_code=None,
                    summary=None,
                    lease_until=now + timedelta(minutes=6),
                )
            )
        else:
            claim.owner_kind = GitWorktreePathClaimOwnerKind.ARCHIVE_CLEANUP
            claim.action_execution_id = None
            claim.root_session_id = root_session_id
            claim.owner_generation = None
            claim.discovery_fingerprint = None
            claim.state = GitWorktreePathClaimState.CLAIMED
            claim.reason_code = None
            claim.summary = None
            claim.lease_until = now + timedelta(minutes=6)
        await session.flush()
        return True

    async def release_archive_git_worktree_claim(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        root_session_id: str,
        worktree_path: str,
    ) -> None:
        """Release one archive cleanup claim after its attempt terminalizes."""
        await session.execute(
            sa.delete(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.agent_runtime_id == runtime_id,
                RDBGitWorktreePathClaim.root_session_id == root_session_id,
                RDBGitWorktreePathClaim.worktree_path == worktree_path,
                RDBGitWorktreePathClaim.owner_kind
                == GitWorktreePathClaimOwnerKind.ARCHIVE_CLEANUP,
            )
        )
        await session.flush()

    async def acquire_runtime_path_coordination_lock(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
    ) -> None:
        """Serialize Project attachment and cleanup claims for one Runtime."""
        await session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _runtime_path_coordination_lock_id(runtime_id)
                )
            )
        )

    async def acquire_runtime_worktree_path_lock(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        worktree_path: str,
    ) -> None:
        """Serialize destructive ownership of one exact Runtime worktree path."""
        await session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _runtime_worktree_path_lock_id(runtime_id, worktree_path)
                )
            )
        )

    async def has_blocking_git_worktree_claim(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        worktree_path: str,
    ) -> bool:
        """Return whether a destructive claim owns an overlapping target."""
        claim_paths = await self._list_blocking_cleanup_claim_paths(
            session,
            runtime_id=runtime_id,
        )
        return any(
            _paths_overlap(worktree_path, claim_path) for claim_path in claim_paths
        )

    async def _list_blocking_cleanup_claim_paths(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
    ) -> list[str]:
        """List currently live cleanup claims for one Runtime under its lock."""
        result = await session.execute(
            sa.select(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.agent_runtime_id == runtime_id,
                RDBGitWorktreePathClaim.state.in_(
                    [
                        GitWorktreePathClaimState.CLAIMED,
                        GitWorktreePathClaimState.REMOVING,
                    ]
                ),
            )
        )
        claims = result.scalars().all()
        return [
            claim.worktree_path
            for claim in claims
            if await self._claim_blocks_path(session, claim=claim)
        ]

    async def create_project(
        self,
        session: AsyncSession,
        create: SessionWorkspaceProjectCreate,
    ) -> SessionWorkspaceProject:
        """Create Project row."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=create.session_id,
        )
        runtime_id = await self._get_runtime_id_by_context_id(
            session,
            context_id=context_id,
        )
        if runtime_id is not None:
            await self.acquire_runtime_path_coordination_lock(
                session,
                runtime_id=runtime_id,
            )
            claim_paths = await self._list_blocking_cleanup_claim_paths(
                session,
                runtime_id=runtime_id,
            )
            if any(
                _paths_overlap(create.path, claim_path) for claim_path in claim_paths
            ):
                raise SessionWorkspaceProjectCleanupInProgress(create.path)
        rdb = RDBSessionAgentContextProject(
            session_agent_context_id=context_id,
            path=create.path,
        )
        session.add(rdb)
        await session.flush()
        await session.refresh(rdb)
        return self._build_project(rdb, session_id=create.session_id)

    async def get_project_by_id(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> SessionWorkspaceProject | None:
        """Fetch Project by ID."""
        result = await session.execute(
            sa.select(
                RDBSessionAgentContextProject,
                RDBSessionAgent.agent_session_id,
            )
            .join(
                RDBSessionAgentContext,
                RDBSessionAgentContext.id
                == RDBSessionAgentContextProject.session_agent_context_id,
            )
            .join(
                RDBSessionAgent,
                RDBSessionAgent.id == RDBSessionAgentContext.root_session_agent_id,
            )
            .where(RDBSessionAgentContextProject.id == project_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        rdb, session_id = row
        return self._build_project(rdb, session_id=session_id)

    async def get_project_by_path(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        path: str,
    ) -> SessionWorkspaceProject | None:
        """Fetch Project by AgentSession and path."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = await session.execute(
            sa.select(RDBSessionAgentContextProject).where(
                RDBSessionAgentContextProject.session_agent_context_id == context_id,
                RDBSessionAgentContextProject.path == path,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_project(rdb, session_id=session_id)

    async def lock_project_by_id(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        context_id: str,
        session_id: str,
    ) -> SessionWorkspaceProject | None:
        """Lock one exact Project in the admission-pinned Session context."""
        result = await session.execute(
            sa.select(RDBSessionAgentContextProject)
            .where(
                RDBSessionAgentContextProject.id == project_id,
                RDBSessionAgentContextProject.session_agent_context_id == context_id,
            )
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_project(rdb, session_id=session_id)

    async def get_runtime_id_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> str | None:
        """Resolve the Runtime bound to one SessionAgentContext."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        return await self._get_runtime_id_by_context_id(
            session,
            context_id=context_id,
        )

    async def list_projects(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """Fetch Project list of AgentSession ordered by path."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = await session.execute(
            sa.select(RDBSessionAgentContextProject)
            .where(RDBSessionAgentContextProject.session_agent_context_id == context_id)
            .order_by(RDBSessionAgentContextProject.path)
        )
        return [
            self._build_project(rdb, session_id=session_id) for rdb in result.scalars()
        ]

    async def list_active_connected_paths_by_runtime_id(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
    ) -> list[str]:
        """List paths connected to active root contexts on one Agent Runtime."""
        active_contexts = (
            sa.select(RDBSessionAgentContext.id)
            .join(
                RDBSessionAgent,
                RDBSessionAgent.id == RDBSessionAgentContext.root_session_agent_id,
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBSessionAgent.agent_session_id,
            )
            .where(
                RDBSessionAgentContext.agent_runtime_id == runtime_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
        )
        project_paths = sa.select(RDBSessionAgentContextProject.path).where(
            RDBSessionAgentContextProject.session_agent_context_id.in_(active_contexts)
        )
        worktree_paths = sa.select(
            RDBSessionAgentContextGitWorktree.worktree_path
        ).where(
            RDBSessionAgentContextGitWorktree.session_agent_context_id.in_(
                active_contexts
            ),
            RDBSessionAgentContextGitWorktree.status
            != SessionGitWorktreeStatus.CLEANED,
        )
        result = await session.execute(project_paths.union(worktree_paths))
        return sorted(set(result.scalars()))

    async def delete_project(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        session_id: str,
    ) -> bool:
        """Delete Project row."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBSessionAgentContextProject).where(
                    RDBSessionAgentContextProject.id == project_id,
                    RDBSessionAgentContextProject.session_agent_context_id
                    == context_id,
                )
            ),
        )
        await session.flush()
        return result.rowcount > 0

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

    async def _get_runtime_id_by_context_id(
        self,
        session: AsyncSession,
        *,
        context_id: str,
    ) -> str | None:
        """Resolve the Runtime bound to a SessionAgentContext."""
        result = await session.execute(
            sa.select(RDBSessionAgentContext.agent_runtime_id).where(
                RDBSessionAgentContext.id == context_id,
            )
        )
        return result.scalar_one_or_none()

    async def _claim_blocks_path(
        self,
        session: AsyncSession,
        *,
        claim: RDBGitWorktreePathClaim,
    ) -> bool:
        """Return whether a claim remains live after stale-owner verification."""
        if claim.state not in {
            GitWorktreePathClaimState.CLAIMED,
            GitWorktreePathClaimState.REMOVING,
        }:
            return False
        if claim.lease_until > datetime.now(UTC):
            return True
        if claim.owner_kind == GitWorktreePathClaimOwnerKind.ARCHIVE_CLEANUP:
            return False
        if claim.action_execution_id is None or claim.owner_generation is None:
            return False
        result = await session.execute(
            sa.select(
                RDBActionExecution.status,
                RDBAgentSession.owner_generation,
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBActionExecution.session_id,
            )
            .where(RDBActionExecution.id == claim.action_execution_id)
        )
        row = result.one_or_none()
        if row is None:
            return False
        action_status, session_owner_generation = row
        return (
            action_status
            in {ActionExecutionStatus.PENDING, ActionExecutionStatus.RUNNING}
            and session_owner_generation == claim.owner_generation
        )

    def _build_project(
        self,
        rdb: RDBSessionAgentContextProject,
        *,
        session_id: str,
    ) -> SessionWorkspaceProject:
        """Convert RDB Project row to domain model."""
        return SessionWorkspaceProject(
            id=rdb.id,
            session_id=session_id,
            session_agent_context_id=rdb.session_agent_context_id,
            path=rdb.path,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )


class SessionWorkspaceProjectCleanupInProgress(RuntimeError):
    """A manual cleanup currently owns the requested Project path."""

    def __init__(self, path: str) -> None:
        super().__init__("Project path is being removed by manual worktree cleanup.")
        self.path = path


def _runtime_path_coordination_lock_id(runtime_id: str) -> int:
    """Derive a stable signed lock ID for one Runtime path namespace."""
    digest = hashlib.sha256(
        f"runtime-worktree-path-coordination:{runtime_id}".encode()
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _runtime_worktree_path_lock_id(runtime_id: str, worktree_path: str) -> int:
    """Derive a stable signed lock ID for one Runtime worktree target."""
    digest = hashlib.sha256(
        f"runtime-worktree-path:{runtime_id}:{worktree_path}".encode()
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _paths_overlap(left: str, right: str) -> bool:
    """Return whether two absolute POSIX paths share an ancestor boundary."""
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path.is_relative_to(right_path)
        or right_path.is_relative_to(left_path)
    )
