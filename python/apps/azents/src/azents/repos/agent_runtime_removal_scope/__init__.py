"""Repository for Agent Runtime removal impact and product-state cleanup."""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionStatus,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionRunState,
    AgentSessionStatus,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.rdb.models.action_execution import RDBActionExecution
from azents.rdb.models.agent_automatic_project_item import (
    RDBAgentAutomaticProjectItem,
)
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.agent_project_catalog import RDBAgentProjectCatalogEntry
from azents.rdb.models.agent_project_default import RDBAgentProjectDefault
from azents.rdb.models.agent_project_preset import RDBAgentProjectPreset
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.git_worktree_cleanup_claim import RDBGitWorktreePathClaim
from azents.rdb.models.session_agent_context import (
    RDBSessionAgentContext,
    RDBSessionAgentContextGitWorktree,
    RDBSessionAgentContextProject,
)
from azents.rdb.models.toolkit_state import RDBToolkitState

from .data import (
    AgentRuntimeRemovalCleanupBatch,
    AgentRuntimeRemovalImpact,
    AgentRuntimeRemovalInterruption,
)

_RUNTIME_ACTION_TYPES = (
    "create_git_worktree",
    "cleanup_orphan_git_worktrees",
    "create_session_working_folder",
)
_ACTIVE_ACTION_STATUSES = (
    ActionExecutionStatus.PENDING,
    ActionExecutionStatus.RUNNING,
)
_ACTIVE_RUN_STATUSES = (AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
_RUNTIME_ONLY_TOOLKIT_STATE_NAMESPACES = ("claude_rules", "skill")
_REMOVAL_CANCELLATION_SUMMARY = "Cancelled because Agent Runtime removal was confirmed."
_REMOVAL_CLEANUP_SUMMARY = "Superseded by Agent Runtime removal."


class AgentRuntimeRemovalScopeRepository:
    """Own privacy-safe inventory, interruption, and Runtime-owned cleanup."""

    async def get_impact(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> AgentRuntimeRemovalImpact:
        """Return content-free aggregate active-work counts for one Agent."""
        active_root_session_count = await self._count_sessions(
            session,
            agent_id=agent_id,
            session_kind=AgentSessionKind.ROOT,
        )
        active_subagent_count = await self._count_sessions(
            session,
            agent_id=agent_id,
            session_kind=AgentSessionKind.SUBAGENT,
        )
        active_run_count = int(
            await session.scalar(
                sa.select(sa.func.count(RDBAgentRun.id))
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBAgentRun.session_id,
                )
                .where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgentRun.status.in_(_ACTIVE_RUN_STATUSES),
                )
            )
            or 0
        )
        queued_runtime_action_count = int(
            await session.scalar(
                sa.select(sa.func.count(RDBActionExecution.id))
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBActionExecution.session_id,
                )
                .where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBActionExecution.action_type.in_(_RUNTIME_ACTION_TYPES),
                    RDBActionExecution.status.in_(_ACTIVE_ACTION_STATUSES),
                )
            )
            or 0
        )
        return AgentRuntimeRemovalImpact(
            active_root_session_count=active_root_session_count,
            active_subagent_count=active_subagent_count,
            active_run_count=active_run_count,
            queued_runtime_action_count=queued_runtime_action_count,
        )

    async def interrupt_work(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        operation_id: str,
        now: datetime.datetime,
    ) -> AgentRuntimeRemovalInterruption:
        """Fence all Agent Session trees and terminalize Runtime actions."""
        active_run_session_ids = sa.select(RDBAgentRun.session_id).where(
            RDBAgentRun.status.in_(_ACTIVE_RUN_STATUSES)
        )
        stop_rows = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                sa.or_(
                    RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
                    RDBAgentSession.id.in_(active_run_session_ids),
                ),
            )
            .values(
                stop_requested_at=now,
                stop_requester_user_id=None,
                stop_request_id=operation_id,
            )
            .returning(RDBAgentSession.id)
        )
        stop_session_ids = tuple(stop_rows.scalars().all())

        cancelled_rows = await session.execute(
            sa.update(RDBActionExecution)
            .where(
                RDBActionExecution.session_id.in_(
                    sa.select(RDBAgentSession.id).where(
                        RDBAgentSession.agent_id == agent_id
                    )
                ),
                RDBActionExecution.action_type.in_(_RUNTIME_ACTION_TYPES),
                RDBActionExecution.status.in_(_ACTIVE_ACTION_STATUSES),
            )
            .values(
                status=ActionExecutionStatus.CANCELLED,
                cancelled_at=now,
                cancellation_summary=_REMOVAL_CANCELLATION_SUMMARY,
                updated_at=now,
            )
            .returning(RDBActionExecution.id)
        )
        cancelled_runtime_action_count = len(cancelled_rows.scalars().all())
        await session.flush()
        return AgentRuntimeRemovalInterruption(
            stop_session_ids=stop_session_ids,
            cancelled_runtime_action_count=cancelled_runtime_action_count,
            active_work_remaining=await self.has_active_work(
                session,
                agent_id=agent_id,
            ),
        )

    async def has_active_work(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> bool:
        """Return whether Agent work still blocks destructive cleanup."""
        running_session_exists = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
                )
            )
        )
        if running_session_exists:
            return True
        active_run_exists = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBAgentRun.session_id.in_(
                        sa.select(RDBAgentSession.id).where(
                            RDBAgentSession.agent_id == agent_id
                        )
                    ),
                    RDBAgentRun.status.in_(_ACTIVE_RUN_STATUSES),
                )
            )
        )
        if active_run_exists:
            return True
        return bool(
            await session.scalar(
                sa.select(
                    sa.exists().where(
                        RDBActionExecution.session_id.in_(
                            sa.select(RDBAgentSession.id).where(
                                RDBAgentSession.agent_id == agent_id
                            )
                        ),
                        RDBActionExecution.action_type.in_(_RUNTIME_ACTION_TYPES),
                        RDBActionExecution.status.in_(_ACTIVE_ACTION_STATUSES),
                    )
                )
            )
        )

    async def cleanup_batch(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        agent_runtime_id: str | None,
        operation_id: str,
        after_context_id: str | None,
        limit: int,
        now: datetime.datetime,
    ) -> AgentRuntimeRemovalCleanupBatch:
        """Invalidate and clean one monotonic root-context page."""
        statement = (
            sa.select(RDBSessionAgentContext)
            .where(RDBSessionAgentContext.agent_id == agent_id)
            .order_by(RDBSessionAgentContext.id)
            .limit(limit)
            .with_for_update()
        )
        if after_context_id is not None:
            statement = statement.where(RDBSessionAgentContext.id > after_context_id)
        contexts = list((await session.scalars(statement)).all())
        if not contexts:
            await self._cleanup_agent_runtime_projections(
                session,
                agent_id=agent_id,
                agent_runtime_id=agent_runtime_id,
            )
            await session.flush()
            return AgentRuntimeRemovalCleanupBatch(
                cursor_context_id=after_context_id,
                scanned_count=0,
                invalidated_count=0,
                completed=True,
            )

        context_ids = [context.id for context in contexts]
        await self._delete_context_runtime_metadata(
            session,
            context_ids=context_ids,
        )
        invalidated_count = 0
        for context in contexts:
            if context.working_folder_binding_state not in {
                SessionWorkingFolderBindingState.PENDING,
                SessionWorkingFolderBindingState.BOUND,
            }:
                continue
            context.working_folder_binding_state = (
                SessionWorkingFolderBindingState.INVALIDATED
            )
            context.working_folder_invalidated_by_removal_id = operation_id
            context.working_folder_invalidated_at = now
            if (
                context.working_folder_cleanup_status
                is SessionWorkingFolderCleanupStatus.PENDING
            ):
                context.working_folder_cleanup_status = (
                    SessionWorkingFolderCleanupStatus.FAILED
                )
                context.working_folder_cleanup_summary = _REMOVAL_CLEANUP_SUMMARY
                context.working_folder_cleanup_completed_at = now
            invalidated_count += 1
        await session.flush()
        return AgentRuntimeRemovalCleanupBatch(
            cursor_context_id=contexts[-1].id,
            scanned_count=len(contexts),
            invalidated_count=invalidated_count,
            completed=False,
        )

    async def require_cleanup_complete(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        agent_runtime_id: str | None,
    ) -> None:
        """Reject finalization while Runtime-owned product state remains."""
        pending_binding = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBSessionAgentContext.agent_id == agent_id,
                    RDBSessionAgentContext.working_folder_binding_state.in_(
                        (
                            SessionWorkingFolderBindingState.PENDING,
                            SessionWorkingFolderBindingState.BOUND,
                        )
                    ),
                )
            )
        )
        if pending_binding:
            raise RuntimeError("Agent Runtime Session binding cleanup is incomplete")

        automatic_project_policy_exists = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBAgentAutomaticProjectSetting.agent_id == agent_id,
                )
            )
        )
        if not automatic_project_policy_exists:
            raise RuntimeError("Agent automatic Project policy is missing")

        context_ids = sa.select(RDBSessionAgentContext.id).where(
            RDBSessionAgentContext.agent_id == agent_id
        )
        remaining = (
            (
                RDBSessionAgentContextGitWorktree,
                RDBSessionAgentContextGitWorktree.session_agent_context_id.in_(
                    context_ids
                ),
                "Session Git worktree metadata",
            ),
            (
                RDBSessionAgentContextProject,
                RDBSessionAgentContextProject.session_agent_context_id.in_(context_ids),
                "Session Project metadata",
            ),
            (
                RDBAgentAutomaticProjectItem,
                RDBAgentAutomaticProjectItem.agent_id == agent_id,
                "Agent automatic Project items",
            ),
            (
                RDBAgentProjectCatalogEntry,
                RDBAgentProjectCatalogEntry.agent_id == agent_id,
                "Agent Project catalog",
            ),
            (
                RDBAgentProjectDefault,
                RDBAgentProjectDefault.agent_id == agent_id,
                "Agent Project defaults",
            ),
            (
                RDBAgentProjectPreset,
                RDBAgentProjectPreset.agent_id == agent_id,
                "Agent Project presets",
            ),
        )
        for _, predicate, label in remaining:
            if await session.scalar(sa.select(sa.exists().where(predicate))):
                raise RuntimeError(f"{label} remains after Runtime removal")
        if agent_runtime_id is not None and await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBGitWorktreePathClaim.agent_runtime_id == agent_runtime_id
                )
            )
        ):
            raise RuntimeError("Git worktree path claims remain after Runtime removal")
        if await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBToolkitState.agent_id == agent_id,
                    RDBToolkitState.toolkit_namespace.in_(
                        _RUNTIME_ONLY_TOOLKIT_STATE_NAMESPACES
                    ),
                )
            )
        ):
            raise RuntimeError(
                "Runtime-only Toolkit State remains after Runtime removal"
            )
        if await self.has_active_work(session, agent_id=agent_id):
            raise RuntimeError("Agent Runtime work remains active")

    async def _count_sessions(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_kind: AgentSessionKind,
    ) -> int:
        """Count active Sessions of one kind without reading private metadata."""
        return int(
            await session.scalar(
                sa.select(sa.func.count(RDBAgentSession.id)).where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgentSession.session_kind == session_kind,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                )
            )
            or 0
        )

    async def _delete_context_runtime_metadata(
        self,
        session: AsyncSession,
        *,
        context_ids: Sequence[str],
    ) -> None:
        """Remove Runtime-owned Project and worktree metadata for one page."""
        await session.execute(
            sa.delete(RDBSessionAgentContextGitWorktree).where(
                RDBSessionAgentContextGitWorktree.session_agent_context_id.in_(
                    context_ids
                )
            )
        )
        await session.execute(
            sa.delete(RDBSessionAgentContextProject).where(
                RDBSessionAgentContextProject.session_agent_context_id.in_(context_ids)
            )
        )

    async def _cleanup_agent_runtime_projections(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        agent_runtime_id: str | None,
    ) -> None:
        """Remove Agent-level path projections after all contexts are covered."""
        if agent_runtime_id is not None:
            await session.execute(
                sa.delete(RDBGitWorktreePathClaim).where(
                    RDBGitWorktreePathClaim.agent_runtime_id == agent_runtime_id
                )
            )
        automatic_project_items_exist = sa.exists().where(
            RDBAgentAutomaticProjectItem.agent_id == agent_id
        )
        await session.execute(
            sa.update(RDBAgentAutomaticProjectSetting)
            .where(
                RDBAgentAutomaticProjectSetting.agent_id == agent_id,
                automatic_project_items_exist,
            )
            .values(
                revision=RDBAgentAutomaticProjectSetting.revision + 1,
                updated_by_workspace_user_id=None,
                updated_at=sa.func.now(),
            )
        )
        await session.execute(
            sa.delete(RDBAgentAutomaticProjectItem).where(
                RDBAgentAutomaticProjectItem.agent_id == agent_id
            )
        )
        for model in (
            RDBAgentProjectCatalogEntry,
            RDBAgentProjectDefault,
            RDBAgentProjectPreset,
        ):
            await session.execute(sa.delete(model).where(model.agent_id == agent_id))
        await session.execute(
            sa.delete(RDBToolkitState).where(
                RDBToolkitState.agent_id == agent_id,
                RDBToolkitState.toolkit_namespace.in_(
                    _RUNTIME_ONLY_TOOLKIT_STATE_NAMESPACES
                ),
            )
        )
