"""AgentSession repository."""

import datetime
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection, SelectableModelSettings
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionEndReason,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    SessionAgentKind,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.session_handle import generate_session_handle
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
    AgentSessionUnreadTerminalRunProjection,
    PendingSessionCommand,
    SessionAgent,
)

SESSION_HANDLE_INSERT_ATTEMPTS = 10
_ROOT_SESSION_AGENT_NAME = "root"
_ROOT_SESSION_AGENT_PATH = "/root"
_DEFAULT_SESSION_AGENT_TYPE = "default"
_CHILD_SESSION_AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


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
        """Fetch workspace AgentSession list in latest-first order."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
            )
            .order_by(RDBAgentSession.updated_at.desc())
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_active_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> list[AgentSession]:
        """Fetch active Agent sessions with team primary first.

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
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .order_by(
                primary_order,
                RDBAgentSession.last_user_input_at.desc(),
                RDBAgentSession.updated_at.desc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

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
    ) -> list[AgentSessionUnreadTerminalRunProjection]:
        """Fetch active root Sessions and their shared unread Run boundaries."""
        primary_order = sa.case(
            (RDBAgentSession.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY, 0),
            else_=1,
        )
        result = await session.execute(
            sa.select(RDBAgentSession, RDBAgentSessionUnreadRun.run_id)
            .outerjoin(
                RDBAgentSessionUnreadRun,
                RDBAgentSessionUnreadRun.session_id == RDBAgentSession.id,
            )
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .order_by(
                primary_order,
                RDBAgentSession.last_user_input_at.desc(),
                RDBAgentSession.updated_at.desc(),
            )
        )
        return [
            AgentSessionUnreadTerminalRunProjection(
                session=self._build(agent_session),
                unread_terminal_run_id=unread_terminal_run_id,
            )
            for agent_session, unread_terminal_run_id in result.tuples()
        ]

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
        )

    async def list_archived_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> list[AgentSession]:
        """Fetch archived root sessions in latest-archive-first order."""
        rows = (
            await session.execute(
                sa.select(RDBAgentSession)
                .where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
                )
                .order_by(
                    RDBAgentSession.archived_at.desc(),
                    RDBAgentSession.updated_at.desc(),
                )
            )
        ).scalars()
        return [self._build(row) for row in rows]

    async def get_latest_active_non_primary(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> AgentSession | None:
        """Fetch newest active non-primary AgentSession by creation time."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
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
        """Fetch AgentSession by ID with a row lock."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == agent_session_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def claim_owner_generation(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> int:
        """Claim ownership only while the authoritative root remains active."""
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
        root_status = await session.scalar(
            sa.select(RDBAgentSession.status)
            .where(RDBAgentSession.id == root_agent.agent_session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if root_status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Root AgentSession is not active")
        generation = await session.scalar(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == agent_session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .values(owner_generation=RDBAgentSession.owner_generation + 1)
            .returning(RDBAgentSession.owner_generation)
        )
        if generation is None:
            raise ValueError("AgentSession not found")
        await session.flush()
        return generation

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
    ) -> AgentSession:
        """Ensure active team primary AgentSession for Agent."""
        lifecycle_status = await session.scalar(
            sa.select(RDBAgent.lifecycle_status).where(RDBAgent.id == agent_id)
        )
        if lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            raise ValueError("Agent is not active for team-primary recovery")
        existing_primary = await self.get_team_primary_by_agent_id(session, agent_id)
        if existing_primary is not None:
            return existing_primary
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
    ) -> AgentSession:
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
                    workspace_id=rdb.workspace_id,
                    agent_id=rdb.agent_id,
                )
                await session.flush()
                return self._build(rdb)

            primary = await self.get_team_primary_by_agent_id(session, agent_id)
            if primary is not None:
                return primary

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
                stop_requested_by=None,
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
        user_id: str | None,
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
                pending_command_user_id=user_id,
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
            user_id=rdb.pending_command_user_id,
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
                pending_command_user_id=None,
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
        user_id: str | None,
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
                stop_requested_by=user_id,
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
                stop_requested_by=None,
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
                stop_requested_by=None,
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
        workspace_id: str,
        agent_id: str,
    ) -> None:
        """Create the root SessionAgent and context for a root AgentSession."""
        context_id = uuid7().hex
        root_session_agent_id = uuid7().hex
        runtime_id = await self._get_agent_runtime_id(session, agent_id=agent_id)
        context = RDBSessionAgentContext(
            agent_id=agent_id,
            workspace_id=workspace_id,
            agent_runtime_id=runtime_id,
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

    async def _get_agent_runtime_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> str | None:
        """Return current runtime ID for an Agent when already provisioned."""
        result = await session.execute(
            sa.select(RDBAgentRuntime.id).where(RDBAgentRuntime.agent_id == agent_id)
        )
        return result.scalar_one_or_none()

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
            start_reason=rdb.start_reason,
            title=rdb.title,
            title_source=rdb.title_source,
            title_generated_at=rdb.title_generated_at,
            title_generation_event_id=rdb.title_generation_event_id,
            last_user_input_at=rdb.last_user_input_at,
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
            pending_command_user_id=rdb.pending_command_user_id,
            pending_command_created_at=rdb.pending_command_created_at,
            stop_requested_at=rdb.stop_requested_at,
            stop_requested_by=rdb.stop_requested_by,
            stop_request_id=rdb.stop_request_id,
            archived_at=rdb.archived_at,
            purge_after=rdb.purge_after,
            archive_policy_revision=rdb.archive_policy_revision,
            archive_retention_days_snapshot=rdb.archive_retention_days_snapshot,
            ended_at=rdb.ended_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
