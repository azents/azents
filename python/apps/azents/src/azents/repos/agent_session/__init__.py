"""AgentSession repository."""

import asyncio
import datetime
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
from azcommon.uuid import uuid7
from psycopg.errors import LockNotAvailable
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection, SelectableModelSettings
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionEndReason,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    SessionAgentKind,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.session_handle import generate_session_handle
from azents.core.session_working_folder import build_session_working_folder_path
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.agent_session_unread_run import RDBAgentSessionUnreadRun
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext

from .data import (
    AgentSession,
    AgentSessionCreate,
    AgentSessionEnsureTeamPrimaryResult,
    AgentSessionPage,
    AgentSessionProjectionPage,
    AgentSessionSidebarSummary,
    AgentSessionUnreadTerminalRunProjection,
    PendingSessionCommand,
    SessionAgent,
    SessionWorkingFolderContext,
)

SESSION_HANDLE_INSERT_ATTEMPTS = 10
_ROOT_SESSION_AGENT_NAME = "root"
_ROOT_SESSION_AGENT_PATH = "/root"
_DEFAULT_SESSION_AGENT_TYPE = "default"
_CHILD_SESSION_AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_OWNER_GENERATION_LOCK_RETRY_SECONDS = 0.01


def validate_session_agent_child_name(name: str) -> None:
    """Validate a child SessionAgent name segment."""
    if not _CHILD_SESSION_AGENT_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "SessionAgent name must start with a letter or number and contain "
            "only letters, numbers, underscores, or hyphens"
        )


def _join_session_agent_path(parent_path: str, child_name: str) -> str:
    """Build a canonical child path."""
    return f"{parent_path}/{child_name}"


@dataclass(frozen=True)
class ModelFileGCLaggingSession:
    """AgentSession with ModelFile GC cursor lag."""

    session_id: str
    head_event_id: str
    head_model_order: int
    cursor_model_order: int


class AgentSessionRepository:
    """AgentSession CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentSessionCreate,
    ) -> AgentSession:
        """Create AgentSession."""
        self._validate_create(create)
        lifecycle_status = await session.scalar(
            sa.select(RDBAgent.lifecycle_status).where(RDBAgent.id == create.agent_id)
        )
        if lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            raise ValueError("Agent is not active for Session creation")
        for _ in range(SESSION_HANDLE_INSERT_ATTEMPTS):
            result = await session.execute(
                pg_insert(RDBAgentSession)
                .values(
                    id=uuid7().hex,
                    workspace_id=create.workspace_id,
                    agent_id=create.agent_id,
                    handle=generate_session_handle(),
                    session_kind=create.session_kind,
                    status=AgentSessionStatus.ACTIVE,
                    title=create.title,
                    primary_kind=create.primary_kind,
                    product_mode=create.product_mode,
                    associated_user_id=create.associated_user_id,
                    start_reason=create.start_reason,
                )
                .on_conflict_do_nothing(index_elements=[RDBAgentSession.handle])
                .returning(RDBAgentSession)
            )
            rdb = result.scalar_one_or_none()
            if rdb is not None:
                if create.session_kind is AgentSessionKind.ROOT:
                    await self._create_root_session_agent_tree(
                        session,
                        agent_session_id=rdb.id,
                        root_session_handle=rdb.handle,
                        workspace_id=rdb.workspace_id,
                        agent_id=rdb.agent_id,
                    )
                await session.flush()
                return self._build(rdb)

        raise RuntimeError("AgentSession handle generation exhausted retry attempts")

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Fetch AgentSession by ID."""
        rdb = await session.get(RDBAgentSession, agent_session_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_by_ids(
        self,
        session: AsyncSession,
        *,
        agent_session_ids: Sequence[str],
    ) -> dict[str, AgentSession]:
        """Fetch AgentSessions by ID."""
        ids = list(dict.fromkeys(agent_session_ids))
        if not ids:
            return {}
        result = await session.execute(
            sa.select(RDBAgentSession).where(RDBAgentSession.id.in_(ids))
        )
        return {rdb.id: self._build(rdb) for rdb in result.scalars()}

    async def get_session_agent_by_session_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> SessionAgent | None:
        """Fetch SessionAgent linked to an AgentSession."""
        rdb = await session.scalar(
            sa.select(RDBSessionAgent).where(
                RDBSessionAgent.agent_session_id == agent_session_id
            )
        )
        if rdb is None:
            return None
        return self._build_session_agent(rdb)

    async def get_working_folder_context_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> SessionWorkingFolderContext | None:
        """Load stored working-folder ownership for one SessionAgent."""
        result = await session.execute(
            sa.select(RDBSessionAgentContext)
            .join(
                RDBSessionAgent,
                RDBSessionAgent.context_id == RDBSessionAgentContext.id,
            )
            .where(RDBSessionAgent.agent_session_id == session_id)
        )
        context = result.scalar_one_or_none()
        if context is None:
            return None
        return self._build_working_folder_context(context)

    async def mark_working_folder_cleanup_pending(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
    ) -> SessionWorkingFolderContext | None:
        """Mark one root Session working-folder cleanup pending under row lock."""
        result = await session.execute(
            sa.select(RDBSessionAgentContext)
            .join(
                RDBSessionAgent,
                RDBSessionAgent.context_id == RDBSessionAgentContext.id,
            )
            .where(RDBSessionAgent.agent_session_id == root_session_id)
            .with_for_update()
        )
        context = result.scalar_one_or_none()
        if (
            context is None
            or context.working_folder_cleanup_status
            is not SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
        ):
            return None
        context.working_folder_cleanup_status = (
            SessionWorkingFolderCleanupStatus.PENDING
        )
        context.working_folder_cleanup_summary = None
        context.working_folder_cleanup_completed_at = None
        await session.flush()
        return self._build_working_folder_context(context)

    async def complete_working_folder_cleanup(
        self,
        session: AsyncSession,
        *,
        context_id: str,
        status: SessionWorkingFolderCleanupStatus,
        summary: str,
        completed_at: datetime.datetime,
    ) -> bool:
        """Terminalize one pending Session working-folder cleanup attempt."""
        if status not in {
            SessionWorkingFolderCleanupStatus.SUCCEEDED,
            SessionWorkingFolderCleanupStatus.FAILED,
        }:
            raise ValueError("Working-folder cleanup status must be terminal")
        if len(summary) > 500:
            raise ValueError("Working-folder cleanup summary exceeds 500 characters")
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBSessionAgentContext)
                .where(
                    RDBSessionAgentContext.id == context_id,
                    RDBSessionAgentContext.working_folder_cleanup_status
                    == SessionWorkingFolderCleanupStatus.PENDING,
                )
                .values(
                    working_folder_cleanup_status=status,
                    working_folder_cleanup_summary=summary,
                    working_folder_cleanup_completed_at=completed_at,
                )
            ),
        )
        await session.flush()
        return result.rowcount == 1

    async def get_root_session_agent_by_session_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> SessionAgent | None:
        """Fetch root SessionAgent for the tree containing an AgentSession."""
        current = await self.get_session_agent_by_session_id(session, agent_session_id)
        if current is None:
            return None
        rdb = await session.get(RDBSessionAgent, current.root_session_agent_id)
        if rdb is None:
            return None
        return self._build_session_agent(rdb)

    async def get_session_agent_by_id(
        self,
        session: AsyncSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Fetch SessionAgent by ID."""
        rdb = await session.get(RDBSessionAgent, session_agent_id)
        if rdb is None:
            return None
        return self._build_session_agent(rdb)

    async def lock_session_agent_by_id(
        self,
        session: AsyncSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Fetch SessionAgent by ID with a row lock."""
        result = await session.execute(
            sa.select(RDBSessionAgent)
            .where(RDBSessionAgent.id == session_agent_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_session_agent(rdb)

    async def list_session_agent_tree(
        self,
        session: AsyncSession,
        *,
        root_session_agent_id: str,
    ) -> list[SessionAgent]:
        """Fetch all SessionAgents in a root tree ordered by path."""
        result = await session.execute(
            sa.select(RDBSessionAgent)
            .where(RDBSessionAgent.root_session_agent_id == root_session_agent_id)
            .order_by(RDBSessionAgent.path.asc())
        )
        return [self._build_session_agent(rdb) for rdb in result.scalars()]

    async def list_descendant_session_agents(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
        include_self: bool,
    ) -> list[SessionAgent]:
        """Fetch descendants for a SessionAgent inside its root tree."""
        current = await session.get(RDBSessionAgent, session_agent_id)
        if current is None:
            raise ValueError("SessionAgent not found")
        descendant_prefix = f"{current.path}/"
        conditions = [
            RDBSessionAgent.root_session_agent_id == current.root_session_agent_id,
            RDBSessionAgent.path.startswith(descendant_prefix, autoescape=True),
        ]
        if include_self:
            conditions = [
                RDBSessionAgent.root_session_agent_id == current.root_session_agent_id,
                sa.or_(
                    RDBSessionAgent.id == current.id,
                    RDBSessionAgent.path.startswith(descendant_prefix, autoescape=True),
                ),
            ]
        result = await session.execute(
            sa.select(RDBSessionAgent)
            .where(*conditions)
            .order_by(RDBSessionAgent.path.asc())
        )
        return [self._build_session_agent(rdb) for rdb in result.scalars()]

    async def get_session_agent_by_path(
        self,
        session: AsyncSession,
        *,
        root_session_agent_id: str,
        path: str,
    ) -> SessionAgent | None:
        """Fetch a SessionAgent by canonical path inside one root tree."""
        if (
            not path.startswith(f"{_ROOT_SESSION_AGENT_PATH}/")
            and path != _ROOT_SESSION_AGENT_PATH
        ):
            raise ValueError("SessionAgent path must be absolute under /root")
        rdb = await session.scalar(
            sa.select(RDBSessionAgent).where(
                RDBSessionAgent.root_session_agent_id == root_session_agent_id,
                RDBSessionAgent.path == path,
            )
        )
        if rdb is None:
            return None
        return self._build_session_agent(rdb)

    async def resolve_session_agent_path(
        self,
        session: AsyncSession,
        *,
        current_session_agent_id: str,
        path: str,
    ) -> SessionAgent | None:
        """Resolve an absolute or current-agent-relative SessionAgent path."""
        current = await session.get(RDBSessionAgent, current_session_agent_id)
        if current is None:
            raise ValueError("SessionAgent not found")

        if path == ".":
            resolved_path = current.path
        elif path.startswith("/"):
            resolved_path = path
        else:
            for segment in path.split("/"):
                validate_session_agent_child_name(segment)
            resolved_path = f"{current.path}/{path}"

        if not (
            resolved_path == _ROOT_SESSION_AGENT_PATH
            or resolved_path.startswith(f"{_ROOT_SESSION_AGENT_PATH}/")
        ):
            return None
        return await self.get_session_agent_by_path(
            session,
            root_session_agent_id=current.root_session_agent_id,
            path=resolved_path,
        )

    async def create_child_session_agent(
        self,
        session: AsyncSession,
        *,
        parent_session_agent_id: str,
        name: str,
        agent_type: str,
        title: str | None,
        last_task_message: str | None,
    ) -> SessionAgent:
        """Create a child SessionAgent and linked hidden AgentSession."""
        validate_session_agent_child_name(name)
        root_session_agent_id = await session.scalar(
            sa.select(RDBSessionAgent.root_session_agent_id).where(
                RDBSessionAgent.id == parent_session_agent_id
            )
        )
        if root_session_agent_id is None:
            raise ValueError("Parent SessionAgent not found")
        root_agent = await session.scalar(
            sa.select(RDBSessionAgent)
            .where(
                RDBSessionAgent.id == root_session_agent_id,
                RDBSessionAgent.kind == SessionAgentKind.ROOT,
            )
            .with_for_update()
        )
        if root_agent is None:
            raise ValueError("Root SessionAgent not found")
        root_session = await session.get(
            RDBAgentSession,
            root_agent.agent_session_id,
            populate_existing=True,
        )
        if root_session is None or root_session.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Root AgentSession is not active")
        if root_session.stop_requested_at is not None:
            raise ValueError("Root AgentSession is stopping")
        parent_row = await session.execute(
            sa.select(RDBSessionAgent, RDBAgentSession)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBSessionAgent.agent_session_id,
            )
            .where(RDBSessionAgent.id == parent_session_agent_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        parent = parent_row.one_or_none()
        if parent is None:
            raise ValueError("Parent SessionAgent not found")
        parent_agent, parent_agent_session = parent
        if parent_agent.root_session_agent_id != root_agent.id:
            raise ValueError("Parent SessionAgent root changed")
        if parent_agent_session.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Parent AgentSession is not active")
        if parent_agent_session.stop_requested_at is not None:
            raise ValueError("Parent AgentSession is stopping")
        child_path = _join_session_agent_path(parent_agent.path, name)

        existing = await session.scalar(
            sa.select(RDBSessionAgent.id).where(
                RDBSessionAgent.root_session_agent_id
                == parent_agent.root_session_agent_id,
                RDBSessionAgent.path == child_path,
            )
        )
        if existing is not None:
            raise ValueError("SessionAgent sibling name already exists")

        child_agent_session = await self._create_linked_subagent_session(
            session,
            workspace_id=parent_agent_session.workspace_id,
            agent_id=parent_agent_session.agent_id,
            title=title,
        )
        rdb = RDBSessionAgent(
            context_id=parent_agent.context_id,
            root_session_agent_id=parent_agent.root_session_agent_id,
            agent_session_id=child_agent_session.id,
            kind=SessionAgentKind.SUBAGENT,
            name=name,
            path=child_path,
            agent_type=agent_type,
            parent_session_agent_id=parent_agent.id,
            last_task_message=last_task_message,
        )
        session.add(rdb)
        await session.flush()
        await session.refresh(rdb)
        return self._build_session_agent(rdb)

    async def update_session_agent_last_task_message(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
        last_task_message: str | None,
    ) -> SessionAgent | None:
        """Update the latest task/message preview for a SessionAgent."""
        result = await session.execute(
            sa.update(RDBSessionAgent)
            .where(RDBSessionAgent.id == session_agent_id)
            .values(last_task_message=last_task_message)
            .returning(RDBSessionAgent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build_session_agent(rdb)

    async def mark_session_agent_message_activity(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Record the latest agent-to-agent message activity time."""
        result = await session.execute(
            sa.update(RDBSessionAgent)
            .where(RDBSessionAgent.id == session_agent_id)
            .values(last_message_at=sa.func.now())
            .returning(RDBSessionAgent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build_session_agent(rdb)

    async def update_session_agent_observation_cursor(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
        parent_observed_run_index: int | None,
        parent_observed_event_id: str | None,
    ) -> SessionAgent | None:
        """Update the terminal-result observation cursor for a SessionAgent."""
        result = await session.execute(
            sa.update(RDBSessionAgent)
            .where(RDBSessionAgent.id == session_agent_id)
            .values(
                parent_observed_run_index=parent_observed_run_index,
                parent_observed_event_id=parent_observed_event_id,
            )
            .returning(RDBSessionAgent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build_session_agent(rdb)

    async def advance_session_agent_observation_cursor(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
        parent_session_agent_id: str,
        parent_observed_run_index: int,
        parent_observed_event_id: str | None,
    ) -> SessionAgent | None:
        """Advance a direct child's cursor without allowing regression."""
        result = await session.execute(
            sa.update(RDBSessionAgent)
            .where(
                RDBSessionAgent.id == session_agent_id,
                RDBSessionAgent.parent_session_agent_id == parent_session_agent_id,
                sa.or_(
                    RDBSessionAgent.parent_observed_run_index.is_(None),
                    RDBSessionAgent.parent_observed_run_index
                    < parent_observed_run_index,
                ),
            )
            .values(
                parent_observed_run_index=parent_observed_run_index,
                parent_observed_event_id=parent_observed_event_id,
            )
            .returning(RDBSessionAgent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build_session_agent(rdb)

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: str,
    ) -> list[AgentSession]:
        """Fetch workspace Team AgentSession list in latest-first order."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
            )
            .order_by(RDBAgentSession.updated_at.desc())
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_active_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> list[AgentSession]:
        """Fetch active Team Agent sessions with team primary first.

        Non-primary sessions are ordered by their most recent user-authored input,
        not by assistant/tool/system activity.
        """
        primary_order = sa.case(
            (RDBAgentSession.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY, 0),
            else_=1,
        )
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .order_by(
                primary_order,
                RDBAgentSession.pinned.desc(),
                RDBAgentSession.last_user_input_at.desc(),
                RDBAgentSession.updated_at.desc(),
                RDBAgentSession.id.asc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_active_user_by_agent_and_user(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        associated_user_id: str,
    ) -> list[AgentSession]:
        """Fetch active User Sessions owned by one User for an Agent."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.product_mode == AgentSessionProductMode.USER,
                RDBAgentSession.associated_user_id == associated_user_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .order_by(
                RDBAgentSession.last_user_input_at.desc(),
                RDBAgentSession.updated_at.desc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_active_user_roots_by_workspace_and_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        associated_user_id: str,
    ) -> list[AgentSession]:
        """Fetch active User root Sessions for one Workspace member."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.product_mode == AgentSessionProductMode.USER,
                RDBAgentSession.associated_user_id == associated_user_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .order_by(RDBAgentSession.created_at, RDBAgentSession.id)
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_user_roots_by_user(
        self,
        session: AsyncSession,
        *,
        associated_user_id: str,
    ) -> list[AgentSession]:
        """Fetch all User root Sessions owned by one User."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.product_mode == AgentSessionProductMode.USER,
                RDBAgentSession.associated_user_id == associated_user_id,
            )
            .order_by(RDBAgentSession.created_at, RDBAgentSession.id)
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def has_any_for_associated_user(
        self,
        session: AsyncSession,
        *,
        associated_user_id: str,
    ) -> bool:
        """Return whether any Session rows remain for an associated User."""
        return bool(
            await session.scalar(
                sa.select(
                    sa.exists().where(
                        RDBAgentSession.associated_user_id == associated_user_id
                    )
                )
            )
        )

    async def list_root_trees_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> list[AgentSession]:
        """List every root tree for Agent decommission reconciliation."""
        rows = (
            await session.execute(
                sa.select(RDBAgentSession)
                .where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                )
                .order_by(RDBAgentSession.created_at, RDBAgentSession.id)
            )
        ).scalars()
        return [self._build(row) for row in rows]

    async def has_any_for_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> bool:
        """Return whether any Session row remains for an Agent."""
        return bool(
            await session.scalar(
                sa.select(sa.exists().where(RDBAgentSession.agent_id == agent_id))
            )
        )

    async def list_active_unread_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        auto_archive_ttl_days: int,
    ) -> list[AgentSessionUnreadTerminalRunProjection]:
        """Fetch active roots with unread state and tree archive deadlines."""
        page = await self._list_active_unread_page_by_agent_id(
            session,
            agent_id,
            auto_archive_ttl_days=auto_archive_ttl_days,
            pinned=None,
            offset=0,
            limit=None,
        )
        return page.items

    async def _list_active_unread_page_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        auto_archive_ttl_days: int,
        pinned: bool | None,
        offset: int,
        limit: int | None,
    ) -> AgentSessionProjectionPage:
        """Fetch an active-root projection page with optional pin filtering."""
        primary_order = sa.case(
            (RDBAgentSession.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY, 0),
            else_=1,
        )
        tree_activity = (
            sa.select(
                RDBSessionAgent.root_session_agent_id.label("root_session_agent_id"),
                sa.func.max(RDBAgentSession.last_activity_at).label(
                    "latest_activity_at"
                ),
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBSessionAgent.agent_session_id,
            )
            .where(RDBAgentSession.agent_id == agent_id)
            .group_by(RDBSessionAgent.root_session_agent_id)
            .subquery()
        )
        filters = [
            RDBAgentSession.agent_id == agent_id,
            RDBAgentSession.session_kind == AgentSessionKind.ROOT,
            RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
            RDBAgentSession.status == AgentSessionStatus.ACTIVE,
        ]
        if pinned is not None:
            filters.append(RDBAgentSession.pinned.is_(pinned))
        total_count = await session.scalar(
            sa.select(sa.func.count()).select_from(RDBAgentSession).where(*filters)
        )
        query = (
            sa.select(
                RDBAgentSession,
                RDBAgentSessionUnreadRun.run_id,
                tree_activity.c.latest_activity_at,
            )
            .outerjoin(
                RDBAgentSessionUnreadRun,
                RDBAgentSessionUnreadRun.session_id == RDBAgentSession.id,
            )
            .outerjoin(
                RDBSessionAgent,
                RDBSessionAgent.agent_session_id == RDBAgentSession.id,
            )
            .outerjoin(
                tree_activity,
                tree_activity.c.root_session_agent_id
                == RDBSessionAgent.root_session_agent_id,
            )
            .where(*filters)
            .order_by(
                primary_order,
                RDBAgentSession.pinned.desc(),
                RDBAgentSession.last_user_input_at.desc(),
                RDBAgentSession.updated_at.desc(),
                RDBAgentSession.id.asc(),
            )
            .offset(offset)
        )
        if limit is not None:
            query = query.limit(limit)
        result = await session.execute(query)
        return AgentSessionProjectionPage(
            items=[
                AgentSessionUnreadTerminalRunProjection(
                    session=self._build(agent_session),
                    unread_terminal_run_id=unread_terminal_run_id,
                    auto_archive_after=(
                        None
                        if agent_session.primary_kind
                        == AgentSessionPrimaryKind.TEAM_PRIMARY
                        or agent_session.pinned
                        else (latest_activity_at or agent_session.last_activity_at)
                        + datetime.timedelta(days=auto_archive_ttl_days)
                    ),
                )
                for (
                    agent_session,
                    unread_terminal_run_id,
                    latest_activity_at,
                ) in result.tuples()
            ],
            total_count=total_count or 0,
        )

    async def list_active_unread_page_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        auto_archive_ttl_days: int,
        offset: int,
        limit: int,
    ) -> AgentSessionProjectionPage:
        """Fetch one ordered active-root page with list projections."""
        return await self._list_active_unread_page_by_agent_id(
            session,
            agent_id,
            auto_archive_ttl_days=auto_archive_ttl_days,
            pinned=None,
            offset=offset,
            limit=limit,
        )

    async def list_active_sidebar_summary_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        auto_archive_ttl_days: int,
        recent_limit: int,
    ) -> AgentSessionSidebarSummary:
        """Fetch pinned and bounded recent active-root sidebar projections."""
        pinned = await self._list_active_unread_page_by_agent_id(
            session,
            agent_id,
            auto_archive_ttl_days=auto_archive_ttl_days,
            pinned=True,
            offset=0,
            limit=None,
        )
        recent = await self._list_active_unread_page_by_agent_id(
            session,
            agent_id,
            auto_archive_ttl_days=auto_archive_ttl_days,
            pinned=False,
            offset=0,
            limit=recent_limit,
        )
        return AgentSessionSidebarSummary(
            pinned=pinned.items,
            recent=recent.items,
        )

    async def get_with_unread_terminal_run_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSessionUnreadTerminalRunProjection | None:
        """Fetch one Session with its shared unread Run boundary."""
        result = await session.execute(
            sa.select(RDBAgentSession, RDBAgentSessionUnreadRun.run_id)
            .outerjoin(
                RDBAgentSessionUnreadRun,
                RDBAgentSessionUnreadRun.session_id == RDBAgentSession.id,
            )
            .where(RDBAgentSession.id == agent_session_id)
        )
        row = result.tuples().one_or_none()
        if row is None:
            return None
        agent_session, unread_terminal_run_id = row
        return AgentSessionUnreadTerminalRunProjection(
            session=self._build(agent_session),
            unread_terminal_run_id=unread_terminal_run_id,
            auto_archive_after=None,
        )

    async def list_archived_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> list[AgentSession]:
        """Fetch archived Team root sessions in latest-archive-first order."""
        rows = (
            await session.execute(
                sa.select(RDBAgentSession)
                .where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
                    RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
                )
                .order_by(
                    RDBAgentSession.archived_at.desc(),
                    RDBAgentSession.updated_at.desc(),
                )
            )
        ).scalars()
        return [self._build(row) for row in rows]

    async def list_archived_page_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        offset: int,
        limit: int,
    ) -> AgentSessionPage:
        """Fetch one latest-archive-first root-session page."""
        filters = [
            RDBAgentSession.agent_id == agent_id,
            RDBAgentSession.session_kind == AgentSessionKind.ROOT,
            RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
            RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
        ]
        total_count = await session.scalar(
            sa.select(sa.func.count()).select_from(RDBAgentSession).where(*filters)
        )
        rows = (
            await session.execute(
                sa.select(RDBAgentSession)
                .where(*filters)
                .order_by(
                    RDBAgentSession.archived_at.desc(),
                    RDBAgentSession.updated_at.desc(),
                    RDBAgentSession.id.asc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        return AgentSessionPage(
            items=[self._build(row) for row in rows],
            total_count=total_count or 0,
        )

    async def list_auto_archive_candidates(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[AgentSession]:
        """List oldest active non-primary Team roots not protected by a pin."""
        rows = (
            await session.execute(
                sa.select(RDBAgentSession)
                .where(
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.primary_kind.is_(None),
                    RDBAgentSession.pinned.is_(False),
                )
                .order_by(RDBAgentSession.last_activity_at, RDBAgentSession.id)
                .limit(limit)
            )
        ).scalars()
        return [self._build(row) for row in rows]

    async def get_latest_active_non_primary(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> AgentSession | None:
        """Fetch newest active non-primary Team AgentSession by creation time."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.primary_kind.is_(None),
            )
            .order_by(RDBAgentSession.created_at.desc())
            .limit(1)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Fetch one AgentSession while serializing non-key admission updates."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == agent_session_id)
            # SQLAlchemy renders key_share=True as PostgreSQL
            # ``FOR NO KEY UPDATE``. Admission updates only non-key columns
            # such as run_state while allowing FK KEY SHARE references.
            .with_for_update(key_share=True)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def set_pinned(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        pinned: bool,
    ) -> AgentSession | None:
        """Set automatic-archive protection for one active root Session."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .values(pinned=pinned)
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def claim_owner_generation(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> int:
        """Claim ownership only while the authoritative root remains active.

        Session-owned transactions can already hold an AgentSession row before
        they reach the root tree lifecycle lock. Use non-blocking Session row
        locks and roll back the nested attempt so this root-first claim never
        completes an inverse lock cycle.
        """
        while True:
            try:
                async with session.begin_nested():
                    return await self._claim_owner_generation_once(
                        session,
                        agent_session_id,
                    )
            except OperationalError as exc:
                if not isinstance(exc.orig, LockNotAvailable):
                    raise
                await asyncio.sleep(_OWNER_GENERATION_LOCK_RETRY_SECONDS)

    async def _claim_owner_generation_once(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> int:
        """Attempt one root-first owner claim without waiting on Session rows."""
        root_session_agent_id = await session.scalar(
            sa.select(RDBSessionAgent.root_session_agent_id).where(
                RDBSessionAgent.agent_session_id == agent_session_id
            )
        )
        if root_session_agent_id is None:
            raise ValueError("AgentSession tree not found")
        root_agent = await session.scalar(
            sa.select(RDBSessionAgent)
            .where(
                RDBSessionAgent.id == root_session_agent_id,
                RDBSessionAgent.kind == SessionAgentKind.ROOT,
            )
            .with_for_update()
        )
        if root_agent is None:
            raise ValueError("Root SessionAgent not found")
        root_session = await session.scalar(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == root_agent.agent_session_id)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
        if root_session is None or root_session.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Root AgentSession is not active")

        if root_session.id == agent_session_id:
            claimed_session = root_session
        else:
            claimed_session = await session.scalar(
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id == agent_session_id)
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
        if (
            claimed_session is None
            or claimed_session.status is not AgentSessionStatus.ACTIVE
        ):
            raise ValueError("AgentSession not found")

        claimed_session.owner_generation += 1
        await session.flush()
        return claimed_session.owner_generation

    async def fence_purge_owner_generations(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> int:
        """Invalidate stale worker ownership for a root-authoritative purge tree."""
        if not session_ids:
            return 0
        fenced_ids = (
            await session.scalars(
                sa.update(RDBAgentSession)
                .where(RDBAgentSession.id.in_(session_ids))
                .values(owner_generation=RDBAgentSession.owner_generation + 1)
                .returning(RDBAgentSession.id)
            )
        ).all()
        await session.flush()
        return len(fenced_ids)

    async def list_session_agent_subtree_session_ids(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
    ) -> list[str]:
        """Fetch AgentSession IDs for the linked SessionAgent subtree."""
        linked_agent = await self.get_session_agent_by_session_id(
            session,
            agent_session_id,
        )
        if linked_agent is None:
            return [agent_session_id]
        locked_root = await self.lock_session_agent_by_id(
            session,
            linked_agent.root_session_agent_id,
        )
        if locked_root is None:
            return [agent_session_id]
        descendants = await self.list_descendant_session_agents(
            session,
            session_agent_id=linked_agent.id,
            include_self=True,
        )
        return [agent.agent_session_id for agent in descendants]

    async def get_team_primary_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentSession | None:
        """Fetch active team primary AgentSession of Agent."""
        result = await session.execute(
            sa.select(RDBAgentSession).where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
                RDBAgentSession.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def ensure_team_primary_for_agent(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> AgentSessionEnsureTeamPrimaryResult:
        """Ensure active team primary AgentSession for Agent."""
        lifecycle_status = await session.scalar(
            sa.select(RDBAgent.lifecycle_status).where(RDBAgent.id == agent_id)
        )
        if lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            raise ValueError("Agent is not active for team-primary recovery")
        existing_primary = await self.get_team_primary_by_agent_id(session, agent_id)
        if existing_primary is not None:
            return AgentSessionEnsureTeamPrimaryResult(
                session=existing_primary,
                created=False,
            )
        return await self._create_team_primary_if_absent(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            start_reason=AgentSessionStartReason.INITIAL,
        )

    async def _create_team_primary_if_absent(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        start_reason: AgentSessionStartReason,
    ) -> AgentSessionEnsureTeamPrimaryResult:
        """Create team primary AgentSession race-safely or return existing row."""
        for _ in range(SESSION_HANDLE_INSERT_ATTEMPTS):
            result = await session.execute(
                pg_insert(RDBAgentSession)
                .values(
                    id=uuid7().hex,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    handle=generate_session_handle(),
                    session_kind=AgentSessionKind.ROOT,
                    status=AgentSessionStatus.ACTIVE,
                    title=None,
                    primary_kind=AgentSessionPrimaryKind.TEAM_PRIMARY,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    start_reason=start_reason,
                )
                .on_conflict_do_nothing()
                .returning(RDBAgentSession)
            )
            rdb = result.scalar_one_or_none()
            if rdb is not None:
                await self._create_root_session_agent_tree(
                    session,
                    agent_session_id=rdb.id,
                    root_session_handle=rdb.handle,
                    workspace_id=rdb.workspace_id,
                    agent_id=rdb.agent_id,
                )
                await session.flush()
                return AgentSessionEnsureTeamPrimaryResult(
                    session=self._build(rdb),
                    created=True,
                )

            primary = await self.get_team_primary_by_agent_id(session, agent_id)
            if primary is not None:
                return AgentSessionEnsureTeamPrimaryResult(
                    session=primary,
                    created=False,
                )

        raise RuntimeError("AgentSession handle generation exhausted retry attempts")

    async def update_title(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        title: str | None,
        title_source: AgentSessionTitleSource | None,
    ) -> AgentSession | None:
        """Update AgentSession title and title source."""
        values: dict[str, object | None] = {
            "title": title,
            "title_source": title_source,
        }
        if title_source != AgentSessionTitleSource.AUTO_GENERATED:
            values["title_generated_at"] = None
            values["title_generation_event_id"] = None
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(**values)
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def set_initial_auto_title_if_unset(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        title: str,
        event_id: str | None,
    ) -> AgentSession | None:
        """Set first-message title only while no title source exists."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.title_source.is_(None),
            )
            .values(
                title=title,
                title_source=AgentSessionTitleSource.AUTO_INITIAL,
                title_generated_at=sa.func.now(),
                title_generation_event_id=event_id,
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def replace_initial_auto_title(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        title: str,
        event_id: str,
    ) -> AgentSession | None:
        """Replace initial automatic title for the same initial prompt event."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.title_source == AgentSessionTitleSource.AUTO_INITIAL,
                RDBAgentSession.title_generation_event_id == event_id,
            )
            .values(
                title=title,
                title_source=AgentSessionTitleSource.AUTO_GENERATED,
                title_generated_at=sa.func.now(),
                title_generation_event_id=event_id,
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def lock_root_tree_sessions(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
    ) -> list[AgentSession]:
        """Lock all AgentSessions in one root SessionAgent tree."""
        root_agent = await session.scalar(
            sa.select(RDBSessionAgent)
            .where(
                RDBSessionAgent.agent_session_id == root_session_id,
                RDBSessionAgent.kind == SessionAgentKind.ROOT,
            )
            .with_for_update()
        )
        if root_agent is None:
            return []
        session_ids = sa.select(RDBSessionAgent.agent_session_id).where(
            RDBSessionAgent.root_session_agent_id == root_agent.id
        )
        rows = (
            await session.execute(
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id.in_(session_ids))
                .order_by(RDBAgentSession.id)
                .with_for_update()
            )
        ).scalars()
        return [self._build(row) for row in rows]

    async def archive_tree(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
        archived_at: datetime.datetime,
        purge_after: datetime.datetime | None,
        policy_revision: int,
        retention_days: int | None,
        end_reason: AgentSessionEndReason | None = None,
    ) -> None:
        """Archive a complete root tree and snapshot policy on its root."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id.in_(session_ids))
            .values(
                status=AgentSessionStatus.ARCHIVED,
                ended_at=archived_at,
                end_reason=end_reason,
                run_state=AgentSessionRunState.IDLE,
            )
        )
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == root_session_id)
            .values(
                archived_at=archived_at,
                purge_after=purge_after,
                archive_policy_revision=policy_revision,
                archive_retention_days_snapshot=retention_days,
            )
        )
        await session.flush()

    async def restore_tree(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
    ) -> None:
        """Restore a complete archived tree and clear root archive metadata."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id.in_(session_ids))
            .values(status=AgentSessionStatus.ACTIVE)
        )
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == root_session_id)
            .values(
                archived_at=None,
                purge_after=None,
                archive_policy_revision=None,
                archive_retention_days_snapshot=None,
                ended_at=None,
                end_reason=None,
            )
        )
        await session.execute(
            sa.update(RDBSessionAgentContext)
            .where(
                RDBSessionAgentContext.id.in_(
                    sa.select(RDBSessionAgent.context_id).where(
                        RDBSessionAgent.agent_session_id == root_session_id
                    )
                )
            )
            .values(
                working_folder_cleanup_status=(
                    SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
                ),
                working_folder_cleanup_summary=None,
                working_folder_cleanup_completed_at=None,
            )
        )
        await session.flush()

    async def archive(
        self,
        session: AsyncSession,
        agent_session_id: str,
        *,
        ended_at: datetime.datetime,
        end_reason: AgentSessionEndReason | None = None,
    ) -> None:
        """Transition one AgentSession to archived state for legacy callers."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == agent_session_id)
            .values(
                status=AgentSessionStatus.ARCHIVED,
                ended_at=ended_at,
                end_reason=end_reason,
            )
        )
        await session.flush()

    async def claim_lifecycle_start(
        self,
        session: AsyncSession,
        agent_session_id: str,
        *,
        now: datetime.datetime,
    ) -> bool:
        """Claim AgentSession lifecycle start marker once initially."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBAgentSession)
                .where(
                    RDBAgentSession.id == agent_session_id,
                    RDBAgentSession.lifecycle_started_at.is_(None),
                )
                .values(lifecycle_started_at=now)
            ),
        )
        await session.flush()
        return result.rowcount == 1

    async def get_lifecycle_started_at(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> datetime.datetime | None:
        """Fetch AgentSession lifecycle start marker time."""
        result = await session.execute(
            sa.select(RDBAgentSession.lifecycle_started_at).where(
                RDBAgentSession.id == agent_session_id
            )
        )
        return result.scalar_one_or_none()

    async def lock_model_input_head_if_current(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        expected_event_id: str | None,
    ) -> bool:
        """Lock the Session and verify the planned model-input head."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            raise ValueError("AgentSession not found")
        return rdb.model_input_head_event_id == expected_event_id

    async def move_model_input_head(
        self,
        session: AsyncSession,
        session_id: str,
        event_id: str,
    ) -> AgentSession:
        """Move Model input head to specified event."""
        event_row = await session.execute(
            sa.select(RDBEvent.id, RDBEvent.model_order).where(
                RDBEvent.session_id == session_id,
                RDBEvent.id == event_id,
            )
        )
        event = event_row.one_or_none()
        if event is None:
            raise ValueError("Model input head event not found in session")

        rdb = await session.get(RDBAgentSession, session_id)
        if rdb is None:
            raise ValueError("AgentSession not found")
        rdb.model_input_head_event_id = event_id
        rdb.model_input_head_model_order = int(event.model_order)
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def list_model_file_gc_lagging(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[ModelFileGCLaggingSession]:
        """List sessions whose ModelFile GC cursor is behind the input head."""
        rows = (
            await session.execute(
                sa.select(
                    RDBAgentSession.id,
                    RDBAgentSession.model_input_head_event_id,
                    RDBAgentSession.model_input_head_model_order,
                    RDBAgentSession.model_file_gc_cursor_model_order,
                )
                .where(
                    RDBAgentSession.model_input_head_event_id.is_not(None),
                    RDBAgentSession.model_input_head_model_order.is_not(None),
                    RDBAgentSession.model_file_gc_cursor_model_order
                    < RDBAgentSession.model_input_head_model_order,
                )
                .order_by(RDBAgentSession.model_file_gc_cursor_model_order)
                .limit(limit)
            )
        ).all()
        return [
            ModelFileGCLaggingSession(
                session_id=row.id,
                head_event_id=row.model_input_head_event_id,
                head_model_order=int(row.model_input_head_model_order),
                cursor_model_order=int(row.model_file_gc_cursor_model_order),
            )
            for row in rows
        ]

    async def advance_model_file_gc_cursor(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        cursor_event_id: str | None,
        cursor_model_order: int,
        updated_at: datetime.datetime,
    ) -> None:
        """Advance the ModelFile GC cursor for a session."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.model_file_gc_cursor_model_order <= cursor_model_order,
            )
            .values(
                model_file_gc_cursor_event_id=cursor_event_id,
                model_file_gc_cursor_model_order=cursor_model_order,
                model_file_gc_updated_at=updated_at,
            )
        )
        await session.flush()

    async def set_inference_state(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        inference_state: SessionInferenceState,
    ) -> AgentSession:
        """Persist the resolved inference configuration for the next turn."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                current_model_target_label=inference_state.model_target_label,
                current_model_selection=inference_state.model_selection.model_dump(
                    mode="json"
                ),
                current_model_settings=inference_state.model_settings.model_dump(
                    mode="json"
                ),
                current_reasoning_effort=inference_state.reasoning_effort,
                current_effective_context_window_tokens=(
                    inference_state.effective_context_window_tokens
                ),
                current_effective_auto_compaction_threshold_tokens=(
                    inference_state.effective_auto_compaction_threshold_tokens
                ),
                current_inference_resolved_at=inference_state.resolved_at,
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            raise ValueError("AgentSession not found")
        await session.flush()
        return self._build(rdb)

    async def mark_running(self, session: AsyncSession, session_id: str) -> None:
        """Transition AgentSession run state to RUNNING."""
        updated_id = await session.scalar(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .values(
                run_state=AgentSessionRunState.RUNNING,
                run_heartbeat_at=sa.func.now(),
            )
            .returning(RDBAgentSession.id)
        )
        if updated_id is None:
            raise ValueError("Active AgentSession not found")
        await session.flush()

    async def mark_running_for_input_wakeup(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        """Transition AgentSession to RUNNING recovery target on buffered input."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.run_state != AgentSessionRunState.RUNNING,
            )
            .values(
                run_state=AgentSessionRunState.RUNNING,
                run_heartbeat_at=sa.func.now(),
            )
        )
        await session.flush()

    async def consume_pending_idle_continuation(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        continue_running: bool,
    ) -> bool:
        """Atomically consume one matching idle continuation boundary."""
        values: dict[str, object] = {
            "pending_idle_continuation_run_id": None,
            "run_state": (
                AgentSessionRunState.RUNNING
                if continue_running
                else AgentSessionRunState.IDLE
            ),
        }
        if continue_running:
            values["run_heartbeat_at"] = sa.func.now()
        else:
            values.update(
                stop_requested_at=None,
                stop_requester_user_id=None,
                stop_request_id=None,
            )
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.pending_idle_continuation_run_id == run_id,
            )
            .values(**values)
            .returning(RDBAgentSession.id)
        )
        await session.flush()
        return result.scalar_one_or_none() is not None

    async def enqueue_pending_command(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        command_id: str,
        command_name: str,
        payload: dict[str, object],
        requester_user_id: str | None,
    ) -> AgentSession | None:
        """Store single pending command in idle AgentSession and mark running."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                RDBAgentSession.pending_command_id.is_(None),
            )
            .values(
                pending_command_id=command_id,
                pending_command_name=command_name,
                pending_command_payload=payload,
                pending_command_requester_user_id=requester_user_id,
                pending_command_created_at=sa.func.now(),
                run_state=AgentSessionRunState.RUNNING,
                run_heartbeat_at=sa.func.now(),
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def get_pending_command_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> PendingSessionCommand | None:
        """Fetch pending command for AgentSession."""
        result = await session.execute(
            sa.select(RDBAgentSession).where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.pending_command_id.is_not(None),
            )
        )
        rdb = result.scalar_one_or_none()
        if (
            rdb is None
            or rdb.pending_command_id is None
            or rdb.pending_command_name is None
            or rdb.pending_command_payload is None
            or rdb.pending_command_created_at is None
        ):
            return None
        return PendingSessionCommand(
            id=rdb.pending_command_id,
            name=rdb.pending_command_name,
            payload=dict(rdb.pending_command_payload),
            requester_user_id=rdb.pending_command_requester_user_id,
            created_at=rdb.pending_command_created_at,
        )

    async def clear_pending_command(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        command_id: str,
    ) -> None:
        """Remove processed pending command."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.pending_command_id == command_id,
            )
            .values(
                pending_command_id=None,
                pending_command_name=None,
                pending_command_payload=None,
                pending_command_requester_user_id=None,
                pending_command_created_at=None,
            )
        )
        await session.flush()

    async def request_stop(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        stop_request_id: str,
        stop_requester_user_id: str | None,
    ) -> AgentSession | None:
        """Record stop intent on running AgentSession."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
            )
            .values(
                stop_requested_at=sa.func.now(),
                stop_requester_user_id=stop_requester_user_id,
                stop_request_id=stop_request_id,
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def has_stop_request(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> bool:
        """Check whether AgentSession has stop intent."""
        result = await session.execute(
            sa.select(RDBAgentSession.id).where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.stop_requested_at.is_not(None),
            )
        )
        return result.scalar_one_or_none() is not None

    async def clear_stop_request(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        """Remove processed stop intent."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                stop_requested_at=None,
                stop_requester_user_id=None,
                stop_request_id=None,
            )
        )
        await session.flush()

    async def mark_idle(self, session: AsyncSession, session_id: str) -> None:
        """Transition AgentSession run state to IDLE."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                run_state=AgentSessionRunState.IDLE,
                stop_requested_at=None,
                stop_requester_user_id=None,
                stop_request_id=None,
            )
        )
        await session.flush()

    async def heartbeat_running(self, session: AsyncSession, session_id: str) -> None:
        """Update heartbeat time of RUNNING AgentSession."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
            )
            .values(run_heartbeat_at=sa.func.now())
        )
        await session.flush()

    async def find_stuck_running(
        self,
        session: AsyncSession,
        *,
        stale_threshold: datetime.timedelta,
        limit: int,
    ) -> list[AgentSession]:
        """Fetch old RUNNING AgentSession list."""
        cutoff = sa.func.now() - stale_threshold
        result = await session.execute(
            sa.select(RDBAgentSession)
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
                RDBAgentSession.run_heartbeat_at < cutoff,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
            .order_by(RDBAgentSession.run_heartbeat_at)
            .limit(limit)
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def _create_root_session_agent_tree(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
        root_session_handle: str,
        workspace_id: str,
        agent_id: str,
    ) -> None:
        """Create the root SessionAgent and context for a root AgentSession."""
        context_id = uuid7().hex
        root_session_agent_id = uuid7().hex
        runtime = await session.scalar(
            sa.select(RDBAgentRuntime).where(RDBAgentRuntime.agent_id == agent_id)
        )
        if runtime is None or runtime.workspace_path is None:
            raise RuntimeError("Agent Runtime workspace path is unavailable")
        context = RDBSessionAgentContext(
            agent_id=agent_id,
            workspace_id=workspace_id,
            agent_runtime_id=runtime.id,
            working_folder_path=build_session_working_folder_path(
                root_session_handle,
                workspace_root=runtime.workspace_path,
            ),
            working_folder_binding_state=SessionWorkingFolderBindingState.BOUND,
            working_folder_cleanup_status=(
                SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
            ),
            working_folder_cleanup_summary=None,
            working_folder_cleanup_completed_at=None,
        )
        context.id = context_id
        session.add(context)
        await session.flush()
        root_agent = RDBSessionAgent(
            context_id=context_id,
            root_session_agent_id=root_session_agent_id,
            agent_session_id=agent_session_id,
            kind=SessionAgentKind.ROOT,
            name=_ROOT_SESSION_AGENT_NAME,
            path=_ROOT_SESSION_AGENT_PATH,
            agent_type=_DEFAULT_SESSION_AGENT_TYPE,
            parent_session_agent_id=None,
        )
        root_agent.id = root_session_agent_id
        session.add(root_agent)
        context.root_session_agent_id = root_session_agent_id

    async def _create_linked_subagent_session(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        title: str | None,
    ) -> RDBAgentSession:
        """Create the hidden AgentSession backing a child SessionAgent."""
        for _ in range(SESSION_HANDLE_INSERT_ATTEMPTS):
            result = await session.execute(
                pg_insert(RDBAgentSession)
                .values(
                    id=uuid7().hex,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    handle=generate_session_handle(),
                    session_kind=AgentSessionKind.SUBAGENT,
                    status=AgentSessionStatus.ACTIVE,
                    title=title,
                    primary_kind=None,
                    product_mode=None,
                    associated_user_id=None,
                    start_reason=AgentSessionStartReason.INITIAL,
                )
                .on_conflict_do_nothing(index_elements=[RDBAgentSession.handle])
                .returning(RDBAgentSession)
            )
            rdb = result.scalar_one_or_none()
            if rdb is not None:
                await session.flush()
                return rdb

        raise RuntimeError("AgentSession handle generation exhausted retry attempts")

    @staticmethod
    def _validate_create(create: AgentSessionCreate) -> None:
        """Reject invalid root/subagent product-mode and ownership combinations."""
        if create.session_kind is AgentSessionKind.SUBAGENT:
            if (
                create.product_mode is not None
                or create.associated_user_id is not None
                or create.primary_kind is not None
            ):
                raise ValueError(
                    "Subagent sessions cannot set product mode, associated user, "
                    "or primary kind"
                )
            return
        if create.session_kind is not AgentSessionKind.ROOT:
            raise ValueError("Unsupported AgentSession kind")
        if create.product_mode is AgentSessionProductMode.TEAM:
            if create.associated_user_id is not None:
                raise ValueError("Team sessions cannot set an associated user")
            return
        if create.product_mode is AgentSessionProductMode.USER:
            if create.associated_user_id is None:
                raise ValueError("User sessions require an associated user")
            if create.primary_kind is not None:
                raise ValueError("User sessions cannot set a primary kind")
            return
        raise ValueError("Root sessions require an explicit product mode")

    def _build_session_agent(self, rdb: RDBSessionAgent) -> SessionAgent:
        """Convert RDB SessionAgent row to domain model."""
        return SessionAgent(
            id=rdb.id,
            context_id=rdb.context_id,
            root_session_agent_id=rdb.root_session_agent_id,
            agent_session_id=rdb.agent_session_id,
            kind=rdb.kind,
            name=rdb.name,
            path=rdb.path,
            agent_type=rdb.agent_type,
            parent_session_agent_id=rdb.parent_session_agent_id,
            last_task_message=rdb.last_task_message,
            last_message_at=rdb.last_message_at,
            parent_observed_run_index=rdb.parent_observed_run_index,
            parent_observed_event_id=rdb.parent_observed_event_id,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_working_folder_context(
        self,
        rdb: RDBSessionAgentContext,
    ) -> SessionWorkingFolderContext:
        """Convert one SessionAgentContext working-folder projection."""
        return SessionWorkingFolderContext(
            id=rdb.id,
            agent_id=rdb.agent_id,
            agent_runtime_id=rdb.agent_runtime_id,
            working_folder_path=rdb.working_folder_path,
            binding_state=rdb.working_folder_binding_state,
            invalidated_by_removal_id=(rdb.working_folder_invalidated_by_removal_id),
            invalidated_at=rdb.working_folder_invalidated_at,
            cleanup_status=rdb.working_folder_cleanup_status,
        )

    def _build(self, rdb: RDBAgentSession) -> AgentSession:
        """Convert RDB model to domain model."""
        inference_state: SessionInferenceState | None = None
        if rdb.current_model_target_label is not None:
            if (
                rdb.current_model_selection is None
                or rdb.current_model_settings is None
                or rdb.current_effective_context_window_tokens is None
                or rdb.current_effective_auto_compaction_threshold_tokens is None
                or rdb.current_inference_resolved_at is None
            ):
                raise ValueError("AgentSession has incomplete inference state")
            inference_state = SessionInferenceState(
                model_target_label=rdb.current_model_target_label,
                model_selection=AgentModelSelection.model_validate(
                    rdb.current_model_selection
                ),
                model_settings=SelectableModelSettings.model_validate(
                    rdb.current_model_settings
                ),
                reasoning_effort=rdb.current_reasoning_effort,
                effective_context_window_tokens=(
                    rdb.current_effective_context_window_tokens
                ),
                effective_auto_compaction_threshold_tokens=(
                    rdb.current_effective_auto_compaction_threshold_tokens
                ),
                resolved_at=rdb.current_inference_resolved_at,
            )
        return AgentSession(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            agent_id=rdb.agent_id,
            handle=rdb.handle,
            inference_state=inference_state,
            session_kind=rdb.session_kind,
            status=rdb.status,
            primary_kind=rdb.primary_kind,
            product_mode=rdb.product_mode,
            associated_user_id=rdb.associated_user_id,
            start_reason=rdb.start_reason,
            title=rdb.title,
            title_source=rdb.title_source,
            title_generated_at=rdb.title_generated_at,
            title_generation_event_id=rdb.title_generation_event_id,
            last_user_input_at=rdb.last_user_input_at,
            last_activity_at=rdb.last_activity_at,
            pinned=rdb.pinned,
            end_reason=rdb.end_reason,
            model_input_head_event_id=rdb.model_input_head_event_id,
            model_input_head_model_order=rdb.model_input_head_model_order,
            model_file_gc_cursor_event_id=rdb.model_file_gc_cursor_event_id,
            model_file_gc_cursor_model_order=rdb.model_file_gc_cursor_model_order,
            started_at=rdb.started_at,
            lifecycle_started_at=rdb.lifecycle_started_at,
            run_state=rdb.run_state,
            run_heartbeat_at=rdb.run_heartbeat_at,
            pending_idle_continuation_run_id=(rdb.pending_idle_continuation_run_id),
            owner_generation=rdb.owner_generation,
            pending_command_id=rdb.pending_command_id,
            pending_command_name=rdb.pending_command_name,
            pending_command_payload=rdb.pending_command_payload,
            pending_command_requester_user_id=rdb.pending_command_requester_user_id,
            pending_command_created_at=rdb.pending_command_created_at,
            stop_requested_at=rdb.stop_requested_at,
            stop_requester_user_id=rdb.stop_requester_user_id,
            stop_request_id=rdb.stop_request_id,
            archived_at=rdb.archived_at,
            purge_after=rdb.purge_after,
            archive_policy_revision=rdb.archive_policy_revision,
            archive_retention_days_snapshot=rdb.archive_retention_days_snapshot,
            ended_at=rdb.ended_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
