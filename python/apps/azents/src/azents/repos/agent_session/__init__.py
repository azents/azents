"""AgentSession repository."""

import datetime
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import aliased

from azents.core.agent_session_data import (
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
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentSessionEndReason,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    ModelCandidateClaimKind,
    SessionAgentKind,
    SessionWorkingFolderBindingState,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_availability import PrimaryModelReservation
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.model_operation import ModelOperationSnapshot
from azents.core.session_handle import generate_session_handle
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.agent_session_unread_run import RDBAgentSessionUnreadRun
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.model_candidate_health import RDBModelCandidateHealth
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.historical_memory_consolidation.lifecycle import (
    source_availability_in_session,
)
from azents.repos.lifecycle_target import ArchiveRetention, LifecycleTargetRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository

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
    cursor_event_id: str | None


@dataclass(frozen=True)
class LockedSessionWorkingFolderBinding:
    """Locked root context plus the path-owning root Session handle."""

    context: SessionWorkingFolderContext
    root_session_handle: str


@dataclass(frozen=True)
class _RuntimeFreeRootCreationAuthority:
    """Runtime-free Agent authority captured before root Session persistence."""

    runtime_capability_version: int


@dataclass(frozen=True)
class _ManagedRootCreationAuthority:
    """Managed Agent authority with its locked Runtime reference."""

    runtime_capability_version: int
    agent_runtime_id: str


type _RootCreationAuthority = (
    _RuntimeFreeRootCreationAuthority | _ManagedRootCreationAuthority
)


def _cursor_result(value: object) -> CursorResult[Any]:
    """Validate one SQLAlchemy mutation result with rowcount evidence."""
    if not isinstance(value, CursorResult):
        raise RuntimeError("SQLAlchemy mutation did not return CursorResult")
    return value


class AgentSessionRepository:
    """AgentSession CRUD repository."""

    async def create(
        self,
        session: WriteSession,
        create: AgentSessionCreate,
    ) -> AgentSession:
        """Create AgentSession."""
        self._validate_create(create)
        root_authority = (
            await self._root_creation_authority(session, agent_id=create.agent_id)
            if create.session_kind is AgentSessionKind.ROOT
            else None
        )
        if root_authority is None:
            lifecycle_status = await session.write_session.scalar(
                sa.select(RDBAgent.lifecycle_status).where(
                    RDBAgent.id == create.agent_id
                )
            )
            if lifecycle_status is not AgentLifecycleStatus.ACTIVE:
                raise ValueError("Agent is not active for Session creation")
        for _ in range(SESSION_HANDLE_INSERT_ATTEMPTS):
            rdb = await self._insert_conversation_session(
                session,
                workspace_id=create.workspace_id,
                agent_id=create.agent_id,
                session_kind=create.session_kind,
                title=create.title,
                primary_kind=create.primary_kind,
                product_mode=create.product_mode,
                associated_user_id=create.associated_user_id,
                start_reason=create.start_reason,
                lifecycle_root_session_id=None,
            )
            if rdb is None:
                continue
            if root_authority is not None:
                conversation = self._require_conversation(rdb)
                await self._create_root_session_agent_tree(
                    session,
                    agent_session_id=rdb.id,
                    root_session_handle=conversation.handle,
                    workspace_id=rdb.workspace_id,
                    agent_id=rdb.agent_id,
                    authority=root_authority,
                )
                await self._confirm_root_creation_authority(
                    session, agent_id=rdb.agent_id, authority=root_authority
                )
            await session.write_session.flush()
            return self._build(rdb)
        raise RuntimeError("AgentSession handle generation exhausted retry attempts")

    async def get_by_id(
        self,
        session: ReadSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Fetch AgentSession by ID."""
        rdb = await session.read_session.scalar(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(RDBAgentSession.id == agent_session_id)
            .execution_options(populate_existing=True)
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_by_ids(
        self,
        session: ReadSession,
        *,
        agent_session_ids: Sequence[str],
    ) -> dict[str, AgentSession]:
        """Fetch AgentSessions by ID."""
        ids = list(dict.fromkeys(agent_session_ids))
        if not ids:
            return {}
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(RDBAgentSession.id.in_(ids))
        )
        return {rdb.id: self._build(rdb) for rdb in result.scalars()}

    async def get_session_agent_by_session_id(
        self,
        session: ReadSession,
        agent_session_id: str,
    ) -> SessionAgent | None:
        """Fetch SessionAgent linked to an AgentSession."""
        rdb = await session.read_session.scalar(
            sa.select(RDBSessionAgent).where(
                RDBSessionAgent.agent_session_id == agent_session_id
            )
        )
        if rdb is None:
            return None
        return self._build_session_agent(rdb)

    async def get_working_folder_context_by_session_id(
        self,
        session: ReadSession,
        *,
        session_id: str,
    ) -> SessionWorkingFolderContext | None:
        """Load stored working-folder ownership for one SessionAgent."""
        result = await session.read_session.execute(
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

    async def lock_working_folder_binding_by_session_id(
        self,
        session: WriteSession,
        *,
        session_id: str,
    ) -> LockedSessionWorkingFolderBinding | None:
        """Lock one shared root context and load its root Session handle."""
        current_agent = aliased(RDBSessionAgent)
        root_agent = aliased(RDBSessionAgent)
        root_session = aliased(RDBAgentSession)
        root_conversation = aliased(RDBConversation)
        result = await session.write_session.execute(
            sa.select(RDBSessionAgentContext, root_conversation.handle)
            .join(
                current_agent,
                current_agent.context_id == RDBSessionAgentContext.id,
            )
            .join(
                root_agent,
                root_agent.id == RDBSessionAgentContext.root_session_agent_id,
            )
            .join(
                root_session,
                root_session.id == root_agent.agent_session_id,
            )
            .join(root_conversation, root_conversation.session_id == root_session.id)
            .where(current_agent.agent_session_id == session_id)
            .with_for_update(of=RDBSessionAgentContext)
        )
        row = result.one_or_none()
        if row is None:
            return None
        context, root_session_handle = row
        return LockedSessionWorkingFolderBinding(
            context=self._build_working_folder_context(context),
            root_session_handle=root_session_handle,
        )

    async def bind_pending_working_folder(
        self,
        session: WriteSession,
        *,
        context_id: str,
        expected_agent_id: str,
        expected_agent_runtime_id: str,
        working_folder_path: str,
    ) -> SessionWorkingFolderContext | None:
        """Bind one exact pending root context without reopening terminal states."""
        result = await session.write_session.execute(
            sa.update(RDBSessionAgentContext)
            .where(
                RDBSessionAgentContext.id == context_id,
                RDBSessionAgentContext.agent_id == expected_agent_id,
                RDBSessionAgentContext.agent_runtime_id == expected_agent_runtime_id,
                RDBSessionAgentContext.working_folder_binding_state
                == SessionWorkingFolderBindingState.PENDING,
                RDBSessionAgentContext.working_folder_path.is_(None),
                RDBSessionAgentContext.working_folder_invalidated_by_removal_id.is_(
                    None
                ),
                RDBSessionAgentContext.working_folder_invalidated_at.is_(None),
            )
            .values(
                working_folder_binding_state=SessionWorkingFolderBindingState.BOUND,
                working_folder_path=working_folder_path,
                updated_at=sa.func.now(),
            )
            .returning(RDBSessionAgentContext)
        )
        context = result.scalar_one_or_none()
        await session.write_session.flush()
        if context is None:
            return None
        return self._build_working_folder_context(context)

    async def mark_working_folder_cleanup_pending(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
    ) -> SessionWorkingFolderContext | None:
        """Mark one root Session working-folder cleanup pending under row lock."""
        result = await session.write_session.execute(
            sa.select(RDBSessionAgentContext)
            .join(
                RDBSessionAgent,
                RDBSessionAgent.context_id == RDBSessionAgentContext.id,
            )
            .where(RDBSessionAgent.agent_session_id == root_session_id)
            .with_for_update()
        )
        context = result.scalar_one_or_none()
        if context is None:
            return None
        if (
            context.working_folder_binding_state
            is not SessionWorkingFolderBindingState.BOUND
            or context.working_folder_cleanup_status
            is not SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
        ):
            return self._build_working_folder_context(context)
        context.working_folder_cleanup_status = (
            SessionWorkingFolderCleanupStatus.PENDING
        )
        context.working_folder_cleanup_summary = None
        context.working_folder_cleanup_completed_at = None
        await session.write_session.flush()
        return self._build_working_folder_context(context)

    async def complete_working_folder_cleanup(
        self,
        session: WriteSession,
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
        result = _cursor_result(
            await session.write_session.execute(
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
            )
        )
        await session.write_session.flush()
        return result.rowcount == 1

    async def get_root_session_agent_by_session_id(
        self,
        session: ReadSession,
        agent_session_id: str,
    ) -> SessionAgent | None:
        """Fetch root SessionAgent for the tree containing an AgentSession."""
        current = await self.get_session_agent_by_session_id(session, agent_session_id)
        if current is None:
            return None
        rdb = await session.read_session.get(
            RDBSessionAgent, current.root_session_agent_id
        )
        if rdb is None:
            return None
        return self._build_session_agent(rdb)

    async def get_session_agent_by_id(
        self,
        session: ReadSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Fetch SessionAgent by ID."""
        rdb = await session.read_session.get(RDBSessionAgent, session_agent_id)
        if rdb is None:
            return None
        return self._build_session_agent(rdb)

    async def lock_session_agent_by_id(
        self,
        session: WriteSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Fetch SessionAgent by ID with a row lock."""
        result = await session.write_session.execute(
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
        session: ReadSession,
        *,
        root_session_agent_id: str,
    ) -> list[SessionAgent]:
        """Fetch all SessionAgents in a root tree ordered by path."""
        result = await session.read_session.execute(
            sa.select(RDBSessionAgent)
            .where(RDBSessionAgent.root_session_agent_id == root_session_agent_id)
            .order_by(RDBSessionAgent.path.asc())
        )
        return [self._build_session_agent(rdb) for rdb in result.scalars()]

    async def list_descendant_session_agents(
        self,
        session: ReadSession,
        *,
        session_agent_id: str,
        include_self: bool,
    ) -> list[SessionAgent]:
        """Fetch descendants for a SessionAgent inside its root tree."""
        current = await session.read_session.get(RDBSessionAgent, session_agent_id)
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
        result = await session.read_session.execute(
            sa.select(RDBSessionAgent)
            .where(*conditions)
            .order_by(RDBSessionAgent.path.asc())
        )
        return [self._build_session_agent(rdb) for rdb in result.scalars()]

    async def get_session_agent_by_path(
        self,
        session: ReadSession,
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
        rdb = await session.read_session.scalar(
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
        session: ReadSession,
        *,
        current_session_agent_id: str,
        path: str,
    ) -> SessionAgent | None:
        """Resolve an absolute or current-agent-relative SessionAgent path."""
        current = await session.read_session.get(
            RDBSessionAgent, current_session_agent_id
        )
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
        session: WriteSession,
        *,
        parent_session_agent_id: str,
        name: str,
        agent_type: str,
        title: str | None,
        last_task_message: str | None,
    ) -> SessionAgent:
        """Create a child SessionAgent and linked hidden AgentSession."""
        validate_session_agent_child_name(name)
        root_session_agent_id = await session.write_session.scalar(
            sa.select(RDBSessionAgent.root_session_agent_id).where(
                RDBSessionAgent.id == parent_session_agent_id
            )
        )
        if root_session_agent_id is None:
            raise ValueError("Parent SessionAgent not found")
        root_agent = await session.write_session.scalar(
            sa.select(RDBSessionAgent)
            .where(
                RDBSessionAgent.id == root_session_agent_id,
                RDBSessionAgent.kind == SessionAgentKind.ROOT,
            )
            .with_for_update()
        )
        if root_agent is None:
            raise ValueError("Root SessionAgent not found")
        root_session = await session.write_session.get(
            RDBAgentSession,
            root_agent.agent_session_id,
            populate_existing=True,
        )
        if root_session is None or root_session.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Root AgentSession is not active")
        if root_session.stop_requested_at is not None:
            raise ValueError("Root AgentSession is stopping")
        parent_row = await session.write_session.execute(
            sa.select(RDBSessionAgent, RDBAgentSession)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBSessionAgent.agent_session_id,
            )
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(RDBSessionAgent.id == parent_session_agent_id)
            .with_for_update(of=(RDBSessionAgent, RDBAgentSession))
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

        existing = await session.write_session.scalar(
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
            lifecycle_root_session_id=root_agent.agent_session_id,
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
        session.write_session.add(rdb)
        await session.write_session.flush()
        await session.write_session.refresh(rdb)
        return self._build_session_agent(rdb)

    async def update_session_agent_last_task_message(
        self,
        session: WriteSession,
        *,
        session_agent_id: str,
        last_task_message: str | None,
    ) -> SessionAgent | None:
        """Update the latest task/message preview for a SessionAgent."""
        result = await session.write_session.execute(
            sa.update(RDBSessionAgent)
            .where(RDBSessionAgent.id == session_agent_id)
            .values(last_task_message=last_task_message)
            .returning(RDBSessionAgent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build_session_agent(rdb)

    async def mark_session_agent_message_activity(
        self,
        session: WriteSession,
        *,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Record the latest agent-to-agent message activity time."""
        result = await session.write_session.execute(
            sa.update(RDBSessionAgent)
            .where(RDBSessionAgent.id == session_agent_id)
            .values(last_message_at=sa.func.now())
            .returning(RDBSessionAgent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build_session_agent(rdb)

    async def update_session_agent_observation_cursor(
        self,
        session: WriteSession,
        *,
        session_agent_id: str,
        parent_observed_run_index: int | None,
        parent_observed_event_id: str | None,
    ) -> SessionAgent | None:
        """Update the terminal-result observation cursor for a SessionAgent."""
        result = await session.write_session.execute(
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
        await session.write_session.flush()
        return self._build_session_agent(rdb)

    async def advance_session_agent_observation_cursor(
        self,
        session: WriteSession,
        *,
        session_agent_id: str,
        parent_session_agent_id: str,
        parent_observed_run_index: int,
        parent_observed_event_id: str | None,
    ) -> SessionAgent | None:
        """Advance a direct child's cursor without allowing regression."""
        result = await session.write_session.execute(
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
        await session.write_session.flush()
        return self._build_session_agent(rdb)

    async def list_by_workspace(
        self,
        session: ReadSession,
        workspace_id: str,
    ) -> list[AgentSession]:
        """Fetch workspace Team AgentSession list in latest-first order."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.workspace_id == workspace_id,
                RDBConversation.session_kind == AgentSessionKind.ROOT,
                RDBConversation.product_mode == AgentSessionProductMode.TEAM,
            )
            .order_by(RDBAgentSession.updated_at.desc())
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_active_by_agent_id(
        self,
        session: ReadSession,
        agent_id: str,
    ) -> list[AgentSession]:
        """Fetch active Team Agent sessions with team primary first.

        Non-primary sessions are ordered by their most recent user-authored input,
        not by assistant/tool/system activity.
        """
        primary_order = sa.case(
            (RDBConversation.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY, 0),
            else_=1,
        )
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBConversation.session_kind == AgentSessionKind.ROOT,
                RDBConversation.product_mode == AgentSessionProductMode.TEAM,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .order_by(
                primary_order,
                RDBConversation.pinned.desc(),
                RDBConversation.last_user_input_at.desc(),
                RDBAgentSession.updated_at.desc(),
                RDBAgentSession.id.asc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_active_user_by_agent_and_user(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        associated_user_id: str,
    ) -> list[AgentSession]:
        """Fetch active User Sessions owned by one User for an Agent."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBConversation.session_kind == AgentSessionKind.ROOT,
                RDBConversation.product_mode == AgentSessionProductMode.USER,
                RDBConversation.associated_user_id == associated_user_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .order_by(
                RDBConversation.last_user_input_at.desc(),
                RDBAgentSession.updated_at.desc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_active_user_roots_by_workspace_and_user(
        self,
        session: ReadSession,
        *,
        workspace_id: str,
        associated_user_id: str,
    ) -> list[AgentSession]:
        """Fetch active User root Sessions for one Workspace member."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.workspace_id == workspace_id,
                RDBConversation.session_kind == AgentSessionKind.ROOT,
                RDBConversation.product_mode == AgentSessionProductMode.USER,
                RDBConversation.associated_user_id == associated_user_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .order_by(RDBAgentSession.created_at, RDBAgentSession.id)
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_user_roots_by_user(
        self,
        session: ReadSession,
        *,
        associated_user_id: str,
    ) -> list[AgentSession]:
        """Fetch all User root Sessions owned by one User."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBConversation.session_kind == AgentSessionKind.ROOT,
                RDBConversation.product_mode == AgentSessionProductMode.USER,
                RDBConversation.associated_user_id == associated_user_id,
            )
            .order_by(RDBAgentSession.created_at, RDBAgentSession.id)
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def has_any_for_associated_user(
        self,
        session: WriteSession,
        *,
        associated_user_id: str,
    ) -> bool:
        """Return whether any Session rows remain for an associated User."""
        return bool(
            await session.write_session.scalar(
                sa.select(
                    sa.exists().where(
                        RDBConversation.associated_user_id == associated_user_id
                    )
                )
            )
        )

    async def list_root_trees_by_agent_id(
        self,
        session: ReadSession,
        *,
        agent_id: str,
    ) -> list[AgentSession]:
        """List every root tree for Agent decommission reconciliation."""
        rows = (
            await session.read_session.execute(
                sa.select(RDBAgentSession)
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
                .where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBConversation.session_kind == AgentSessionKind.ROOT,
                )
                .order_by(RDBAgentSession.created_at, RDBAgentSession.id)
            )
        ).scalars()
        return [self._build(row) for row in rows]

    async def has_any_for_agent_id(
        self,
        session: ReadSession,
        *,
        agent_id: str,
    ) -> bool:
        """Return whether any Session row remains for an Agent."""
        return bool(
            await session.read_session.scalar(
                sa.select(sa.exists().where(RDBAgentSession.agent_id == agent_id))
            )
        )

    async def list_active_unread_by_agent_id(
        self,
        session: ReadSession,
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
        session: ReadSession,
        agent_id: str,
        *,
        auto_archive_ttl_days: int,
        pinned: bool | None,
        offset: int,
        limit: int | None,
    ) -> AgentSessionProjectionPage:
        """Fetch an active-root projection page with optional pin filtering."""
        primary_order = sa.case(
            (RDBConversation.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY, 0),
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
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(RDBAgentSession.agent_id == agent_id)
            .group_by(RDBSessionAgent.root_session_agent_id)
            .subquery()
        )
        filters = [
            RDBAgentSession.agent_id == agent_id,
            RDBConversation.session_kind == AgentSessionKind.ROOT,
            RDBConversation.product_mode == AgentSessionProductMode.TEAM,
            RDBAgentSession.status == AgentSessionStatus.ACTIVE,
        ]
        if pinned is not None:
            filters.append(RDBConversation.pinned.is_(pinned))
        total_count = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(*filters)
        )
        query = (
            sa.select(
                RDBAgentSession,
                RDBAgentSessionUnreadRun.run_id,
                tree_activity.c.latest_activity_at,
            )
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
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
                RDBConversation.pinned.desc(),
                RDBConversation.last_user_input_at.desc(),
                RDBAgentSession.updated_at.desc(),
                RDBAgentSession.id.asc(),
            )
            .offset(offset)
        )
        if limit is not None:
            query = query.limit(limit)
        result = await session.read_session.execute(query)
        return AgentSessionProjectionPage(
            items=[
                AgentSessionUnreadTerminalRunProjection(
                    session=self._build(agent_session),
                    unread_terminal_run_id=unread_terminal_run_id,
                    auto_archive_after=(
                        None
                        if self._require_conversation(agent_session).primary_kind
                        == AgentSessionPrimaryKind.TEAM_PRIMARY
                        or self._require_conversation(agent_session).pinned
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
        session: ReadSession,
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
        session: ReadSession,
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
        session: ReadSession,
        agent_session_id: str,
    ) -> AgentSessionUnreadTerminalRunProjection | None:
        """Fetch one Session with its shared unread Run boundary."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession, RDBAgentSessionUnreadRun.run_id)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
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
        session: ReadSession,
        agent_id: str,
    ) -> list[AgentSession]:
        """Fetch archived Team root sessions in latest-archive-first order."""
        rows = (
            await session.read_session.execute(
                sa.select(RDBAgentSession)
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
                .where(
                    RDBAgentSession.agent_id == agent_id,
                    RDBConversation.session_kind == AgentSessionKind.ROOT,
                    RDBConversation.product_mode == AgentSessionProductMode.TEAM,
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
        session: ReadSession,
        agent_id: str,
        *,
        offset: int,
        limit: int,
    ) -> AgentSessionPage:
        """Fetch one latest-archive-first root-session page."""
        filters = [
            RDBAgentSession.agent_id == agent_id,
            RDBConversation.session_kind == AgentSessionKind.ROOT,
            RDBConversation.product_mode == AgentSessionProductMode.TEAM,
            RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
        ]
        total_count = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(*filters)
        )
        rows = (
            await session.read_session.execute(
                sa.select(RDBAgentSession)
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
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
        session: ReadSession,
        *,
        limit: int,
    ) -> list[AgentSession]:
        """List oldest active non-primary Team roots not protected by a pin."""
        rows = (
            await session.read_session.execute(
                sa.select(RDBAgentSession)
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
                .where(
                    RDBConversation.session_kind == AgentSessionKind.ROOT,
                    RDBConversation.product_mode == AgentSessionProductMode.TEAM,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBConversation.primary_kind.is_(None),
                    RDBConversation.pinned.is_(False),
                )
                .order_by(RDBAgentSession.last_activity_at, RDBAgentSession.id)
                .limit(limit)
            )
        ).scalars()
        return [self._build(row) for row in rows]

    async def get_latest_active_non_primary(
        self,
        session: ReadSession,
        *,
        agent_id: str,
    ) -> AgentSession | None:
        """Fetch newest active non-primary Team AgentSession by creation time."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBConversation.session_kind == AgentSessionKind.ROOT,
                RDBConversation.product_mode == AgentSessionProductMode.TEAM,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBConversation.primary_kind.is_(None),
            )
            .order_by(RDBAgentSession.created_at.desc())
            .limit(1)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(await self._refresh_conversation(session, rdb))

    async def fence_active_mailbox_target(
        self,
        session: WriteSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Retain exact active target admission through its mailbox transaction."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == agent_session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                ],
                values={
                    "owner_generation": RDBAgentSession.owner_generation,
                    "updated_at": RDBAgentSession.updated_at,
                },
            )
            .returning(RDBAgentSession.id)
            .execution_options(populate_existing=True)
        )
        current = result.scalar_one_or_none()
        return (
            None
            if current is None
            else self._build(await self._refresh_conversation(session, current))
        )

    async def lock_by_id(
        self,
        session: WriteSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Fence the exact Session mutation without excluding unrelated Agent work."""
        result = await session.write_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(RDBAgentSession.id == agent_session_id)
            # SQLAlchemy renders key_share=True as PostgreSQL
            # ``FOR NO KEY UPDATE``. Admission updates only non-key columns
            # such as run_state while allowing FK KEY SHARE references.
            .with_for_update(key_share=True, of=RDBAgentSession)
            .execution_options(populate_existing=True)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(await self._refresh_conversation(session, rdb))

    async def set_pinned(
        self,
        session: WriteSession,
        *,
        session_id: str,
        pinned: bool,
    ) -> AgentSession | None:
        """Set automatic-archive protection for one active root Session."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBConversation.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                ],
                values={"pinned": pinned},
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def claim_owner_generation(
        self,
        session: WriteSession,
        agent_session_id: str,
    ) -> int:
        """Advance the exact Session owner row, serializing critical commits only."""
        source = await self.get_session_agent_by_session_id(session, agent_session_id)
        if source is None:
            raise ValueError("AgentSession tree not found")
        root = await self.get_session_agent_by_id(session, source.root_session_agent_id)
        if root is None:
            raise ValueError("Root SessionAgent not found")
        root_session = await self.get_by_id(session, root.agent_session_id)
        if root_session is None or root_session.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Root AgentSession is not active")
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == agent_session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                ],
                values={"owner_generation": RDBAgentSession.owner_generation + 1},
            ).returning(RDBAgentSession.owner_generation)
        )
        generation = result.scalar_one_or_none()
        if generation is None:
            raise ValueError("AgentSession not found")
        return generation

    async def fence_purge_owner_generations(
        self,
        session: WriteSession,
        *,
        session_ids: Sequence[str],
    ) -> int:
        """Invalidate stale worker ownership for a root-authoritative purge tree."""
        if not session_ids:
            return 0
        fenced_ids = (
            await session.write_session.scalars(
                self._conversation_update(
                    predicates=[RDBAgentSession.id.in_(session_ids)],
                    values={"owner_generation": RDBAgentSession.owner_generation + 1},
                ).returning(RDBAgentSession.id)
            )
        ).all()
        await session.write_session.flush()
        return len(fenced_ids)

    async def list_session_agent_subtree_session_ids(
        self,
        session: ReadSession,
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
        descendants = await self.list_descendant_session_agents(
            session,
            session_agent_id=linked_agent.id,
            include_self=True,
        )
        return [agent.agent_session_id for agent in descendants]

    async def get_team_primary_by_agent_id(
        self,
        session: ReadSession,
        agent_id: str,
    ) -> AgentSession | None:
        """Fetch active team primary AgentSession of Agent."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBConversation.session_kind == AgentSessionKind.ROOT,
                RDBConversation.product_mode == AgentSessionProductMode.TEAM,
                RDBConversation.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(await self._refresh_conversation(session, rdb))

    async def ensure_team_primary_for_agent(
        self,
        session: WriteSession,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> AgentSessionEnsureTeamPrimaryResult:
        """Ensure active team primary AgentSession for Agent."""
        lifecycle_status = await session.write_session.scalar(
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
        session: WriteSession,
        *,
        workspace_id: str,
        agent_id: str,
        start_reason: AgentSessionStartReason,
    ) -> AgentSessionEnsureTeamPrimaryResult:
        """Create team primary AgentSession race-safely or return existing row."""
        root_authority = await self._root_creation_authority(
            session,
            agent_id=agent_id,
        )
        for _ in range(SESSION_HANDLE_INSERT_ATTEMPTS):
            rdb = await self._insert_conversation_session(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_kind=AgentSessionKind.ROOT,
                title=None,
                primary_kind=AgentSessionPrimaryKind.TEAM_PRIMARY,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                start_reason=start_reason,
                lifecycle_root_session_id=None,
            )
            if rdb is not None:
                conversation = self._require_conversation(rdb)
                await self._create_root_session_agent_tree(
                    session,
                    agent_session_id=rdb.id,
                    root_session_handle=conversation.handle,
                    workspace_id=rdb.workspace_id,
                    agent_id=rdb.agent_id,
                    authority=root_authority,
                )
                await self._confirm_root_creation_authority(
                    session, agent_id=rdb.agent_id, authority=root_authority
                )
                await session.write_session.flush()
                return AgentSessionEnsureTeamPrimaryResult(
                    session=self._build(rdb), created=True
                )
            primary = await self.get_team_primary_by_agent_id(session, agent_id)
            if primary is not None:
                return AgentSessionEnsureTeamPrimaryResult(
                    session=primary, created=False
                )
        raise RuntimeError("AgentSession handle generation exhausted retry attempts")

    async def update_title(
        self,
        session: WriteSession,
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
            values["title_model_operation_state"] = None
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[RDBAgentSession.id == session_id], values={**values}
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def set_initial_auto_title_if_unset(
        self,
        session: WriteSession,
        *,
        session_id: str,
        title: str,
        event_id: str | None,
    ) -> AgentSession | None:
        """Set first-message title only while no title source exists."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBConversation.title_source.is_(None),
                ],
                values={
                    "title": title,
                    "title_source": AgentSessionTitleSource.AUTO_INITIAL,
                    "title_generated_at": sa.func.now(),
                    "title_generation_event_id": event_id,
                },
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def replace_initial_auto_title(
        self,
        session: WriteSession,
        *,
        session_id: str,
        title: str,
        event_id: str,
    ) -> AgentSession | None:
        """Replace initial automatic title for the same initial prompt event."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBConversation.title_source
                    == AgentSessionTitleSource.AUTO_INITIAL,
                    RDBConversation.title_generation_event_id == event_id,
                ],
                values={
                    "title": title,
                    "title_source": AgentSessionTitleSource.AUTO_GENERATED,
                    "title_generated_at": sa.func.now(),
                    "title_generation_event_id": event_id,
                    "title_model_operation_state": None,
                },
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def set_primary_model_reservation(
        self,
        session: WriteSession,
        *,
        session_id: str,
        reservation: PrimaryModelReservation | None,
        expected_reservation_generation: int | None,
    ) -> AgentSession | None:
        """Replace a Primary reservation under an optional generation fence."""
        predicates: list[sa.ColumnElement[bool]] = [
            RDBAgentSession.id == session_id,
            RDBConversation.session_kind == AgentSessionKind.ROOT,
            RDBAgentSession.status == AgentSessionStatus.ACTIVE,
        ]
        if expected_reservation_generation is not None:
            predicates.append(
                RDBConversation.primary_model_reservation[
                    "reservation_generation"
                ].astext.cast(sa.BigInteger)
                == expected_reservation_generation
            )
        values: dict[str, object] = {
            "primary_model_reservation": (
                reservation.model_dump(mode="json") if reservation is not None else None
            )
        }
        if reservation is not None:
            predicates.append(
                RDBConversation.primary_model_reservation_generation
                < reservation.reservation_generation
            )
            values["primary_model_reservation_generation"] = (
                reservation.reservation_generation
            )
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[*predicates], values={**values}
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def set_title_model_operation_state(
        self,
        session: WriteSession,
        *,
        session_id: str,
        generation_event_id: str,
        operation: ModelOperationSnapshot | None,
    ) -> AgentSession | None:
        """Set title operation state only for the current generation event."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBConversation.title_source
                    == AgentSessionTitleSource.AUTO_INITIAL,
                    RDBConversation.title_generation_event_id == generation_event_id,
                ],
                values={
                    "title_model_operation_state": operation.model_dump(mode="json")
                    if operation is not None
                    else None
                },
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def lock_root_tree_sessions(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
    ) -> list[AgentSession]:
        """Lock complete tree membership inside the owning lifecycle operation.

        Child creation shares the root gate. Confirmed database aborts are
        recovered by the complete operation owner, not a partial row-set retry.
        """
        root_agent = await session.write_session.scalar(
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
            await session.write_session.execute(
                sa.select(RDBAgentSession)
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
                .where(RDBAgentSession.id.in_(session_ids))
                .order_by(RDBAgentSession.id)
                .with_for_update(key_share=True, of=RDBAgentSession)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        return [self._build(row) for row in rows]

    async def archive_conversation_resources(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
    ) -> None:
        """Retire actual Conversation resources without writing common lifecycle."""
        await self._release_primary_model_reservations(session, session_ids=session_ids)
        await session.write_session.execute(
            sa.update(RDBConversation)
            .where(RDBConversation.session_id.in_(session_ids))
            .values(primary_model_reservation=None, title_model_operation_state=None)
        )
        root_profile = await session.write_session.scalar(
            sa.select(RDBConversation.session_id).where(
                RDBConversation.session_id == root_session_id
            )
        )
        if root_profile is not None:
            await source_availability_in_session(
                session, source_session_id=root_session_id, denied=True
            )
        await session.write_session.flush()

    async def archive_tree(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
        archived_at: datetime.datetime,
        purge_after: datetime.datetime | None,
        policy_revision: int,
        retention_days: int | None,
        end_reason: AgentSessionEndReason | None = None,
    ) -> None:
        """Archive Conversation resources through the common lifecycle writer."""
        await self.archive_conversation_resources(
            session, root_session_id=root_session_id, session_ids=session_ids
        )
        await LifecycleTargetRepository().archive_status(
            session,
            root_session_id=root_session_id,
            session_ids=session_ids,
            retention=ArchiveRetention(
                archived_at=archived_at,
                purge_after=purge_after,
                policy_revision=policy_revision,
                retention_days=retention_days,
            ),
            end_reason=end_reason,
        )

    async def restore_tree(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
    ) -> None:
        """Restore a complete archived tree and clear root archive metadata."""
        await session.write_session.execute(
            self._conversation_update(
                predicates=[RDBAgentSession.id.in_(session_ids)],
                values={"status": AgentSessionStatus.ACTIVE},
            )
        )
        await session.write_session.execute(
            self._conversation_update(
                predicates=[RDBAgentSession.id == root_session_id],
                values={
                    "archived_at": None,
                    "purge_after": None,
                    "archive_policy_revision": None,
                    "archive_retention_days_snapshot": None,
                    "ended_at": None,
                    "end_reason": None,
                },
            )
        )
        await session.write_session.execute(
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
        await source_availability_in_session(
            session, source_session_id=root_session_id, denied=False
        )
        await session.write_session.flush()

    async def archive(
        self,
        session: WriteSession,
        agent_session_id: str,
        *,
        ended_at: datetime.datetime,
        end_reason: AgentSessionEndReason | None = None,
    ) -> None:
        """Archive one Conversation in the caller's existing DB composition."""
        await self.archive_conversation_resources(
            session, root_session_id=agent_session_id, session_ids=[agent_session_id]
        )
        await session.write_session.execute(
            self._conversation_update(
                predicates=[RDBAgentSession.id == agent_session_id],
                values={
                    "status": AgentSessionStatus.ARCHIVED,
                    "ended_at": ended_at,
                    "end_reason": end_reason,
                },
            )
        )
        await session.write_session.flush()

    async def _release_primary_model_reservations(
        self,
        session: WriteSession,
        *,
        session_ids: Sequence[str],
    ) -> None:
        """Release exact candidate-health claims before archiving Sessions."""
        rows = (
            await session.write_session.execute(
                sa.select(
                    RDBAgentSession.id,
                    RDBAgentSession.workspace_id,
                    RDBConversation.primary_model_reservation,
                )
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
                .where(
                    RDBAgentSession.id.in_(session_ids),
                    RDBConversation.primary_model_reservation.is_not(None),
                )
                .with_for_update(of=RDBAgentSession)
            )
        ).all()
        for session_id, workspace_id, reservation_payload in rows:
            if reservation_payload is None:
                continue
            reservation = PrimaryModelReservation.model_validate(reservation_payload)
            await session.write_session.execute(
                sa.update(RDBModelCandidateHealth)
                .where(
                    RDBModelCandidateHealth.workspace_id == workspace_id,
                    RDBModelCandidateHealth.llm_provider_integration_id
                    == reservation.candidate.llm_provider_integration_id,
                    RDBModelCandidateHealth.model_identifier
                    == reservation.candidate.model_identifier,
                    RDBModelCandidateHealth.generation == reservation.health_generation,
                    RDBModelCandidateHealth.claim_kind
                    == ModelCandidateClaimKind.RESERVATION,
                    RDBModelCandidateHealth.claim_owner_id == session_id,
                    RDBModelCandidateHealth.claim_token == reservation.claim_token,
                )
                .values(
                    claim_kind=None,
                    claim_owner_id=None,
                    claim_token=None,
                    claim_until=None,
                    updated_at=sa.func.clock_timestamp(),
                )
            )

    async def claim_lifecycle_start(
        self,
        session: WriteSession,
        agent_session_id: str,
        *,
        now: datetime.datetime,
    ) -> bool:
        """Claim AgentSession lifecycle start marker once initially."""
        result = _cursor_result(
            await session.write_session.execute(
                self._conversation_update(
                    predicates=[
                        RDBAgentSession.id == agent_session_id,
                        RDBAgentSession.lifecycle_started_at.is_(None),
                    ],
                    values={"lifecycle_started_at": now},
                )
            )
        )
        await session.write_session.flush()
        return result.rowcount == 1

    async def get_lifecycle_started_at(
        self,
        session: ReadSession,
        agent_session_id: str,
    ) -> datetime.datetime | None:
        """Fetch AgentSession lifecycle start marker time."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession.lifecycle_started_at)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(RDBAgentSession.id == agent_session_id)
        )
        return result.scalar_one_or_none()

    async def lock_compaction_plan_if_current(
        self,
        session: WriteSession,
        *,
        session_id: str,
        expected_head_event_id: str | None,
        expected_tail_event_id: str,
    ) -> bool:
        """Lock the Session and verify the planned compaction boundaries."""
        result = await session.write_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(RDBAgentSession.id == session_id)
            .with_for_update(of=RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            raise ValueError("AgentSession not found")
        latest_event_id = await session.write_session.scalar(
            sa.select(RDBEvent.id)
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.reverted.is_(False),
            )
            .order_by(RDBEvent.id.desc())
            .limit(1)
        )
        return (
            rdb.model_input_head_event_id == expected_head_event_id
            and latest_event_id == expected_tail_event_id
        )

    async def move_model_input_head(
        self,
        session: WriteSession,
        session_id: str,
        event_id: str,
    ) -> AgentSession:
        """Move Model input head to specified event."""
        event_id_row = await session.write_session.scalar(
            sa.select(RDBEvent.id).where(
                RDBEvent.session_id == session_id,
                RDBEvent.id == event_id,
            )
        )
        if event_id_row is None:
            raise ValueError("Model input head event not found in session")

        rdb = await session.write_session.get(RDBAgentSession, session_id)
        if rdb is None:
            raise ValueError("AgentSession not found")
        rdb.model_input_head_event_id = event_id
        await session.write_session.flush()
        await session.write_session.refresh(rdb)
        return self._build(await self._refresh_conversation(session, rdb))

    async def list_model_file_gc_lagging(
        self,
        session: ReadSession,
        *,
        limit: int,
    ) -> list[ModelFileGCLaggingSession]:
        """List sessions whose ModelFile GC cursor is behind the input head."""
        rows = (
            await session.read_session.execute(
                sa.select(
                    RDBAgentSession.id,
                    RDBAgentSession.model_input_head_event_id,
                    RDBAgentSession.model_file_gc_cursor_event_id,
                )
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
                .where(
                    RDBAgentSession.model_input_head_event_id.is_not(None),
                    sa.or_(
                        RDBAgentSession.model_file_gc_cursor_event_id.is_(None),
                        RDBAgentSession.model_file_gc_cursor_event_id
                        < RDBAgentSession.model_input_head_event_id,
                    ),
                )
                .order_by(
                    RDBAgentSession.model_file_gc_cursor_event_id.asc().nullsfirst()
                )
                .limit(limit)
            )
        ).all()
        return [
            ModelFileGCLaggingSession(
                session_id=row.id,
                head_event_id=row.model_input_head_event_id,
                cursor_event_id=row.model_file_gc_cursor_event_id,
            )
            for row in rows
        ]

    async def advance_model_file_gc_cursor(
        self,
        session: WriteSession,
        *,
        session_id: str,
        cursor_event_id: str,
        updated_at: datetime.datetime,
    ) -> None:
        """Advance the ModelFile GC cursor for a session."""
        await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    sa.or_(
                        RDBAgentSession.model_file_gc_cursor_event_id.is_(None),
                        RDBAgentSession.model_file_gc_cursor_event_id
                        <= cursor_event_id,
                    ),
                ],
                values={
                    "model_file_gc_cursor_event_id": cursor_event_id,
                    "model_file_gc_updated_at": updated_at,
                },
            )
        )
        await session.write_session.flush()

    async def set_inference_state(
        self,
        session: WriteSession,
        *,
        session_id: str,
        inference_state: SessionInferenceState,
    ) -> AgentSession:
        """Persist the resolved inference configuration for the next turn."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[RDBAgentSession.id == session_id],
                values={
                    "current_model_target_label": inference_state.model_target_label,
                    "current_model_selection": (
                        inference_state.model_selection.model_dump(mode="json")
                    ),
                    "current_model_settings": inference_state.model_settings.model_dump(
                        mode="json"
                    ),
                    "current_reasoning_effort": inference_state.reasoning_effort,
                    "current_enabled_execution_options": [
                        option.value
                        for option in inference_state.enabled_execution_options
                    ],
                    "current_effective_context_window_tokens": (
                        inference_state.effective_context_window_tokens
                    ),
                    "current_effective_auto_compaction_threshold_tokens": (
                        inference_state.effective_auto_compaction_threshold_tokens
                    ),
                    "current_inference_resolved_at": inference_state.resolved_at,
                },
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            raise ValueError("AgentSession not found")
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def set_applied_inference_profile(
        self,
        session: WriteSession,
        *,
        session_id: str,
        model_target_label: str,
        reasoning_effort: ModelReasoningEffort | None,
        enabled_execution_options: list[ModelExecutionOptionId],
    ) -> AgentSession:
        """Replace the Session-owned applied model intent."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[RDBAgentSession.id == session_id],
                values={
                    "applied_model_target_label": model_target_label,
                    "applied_reasoning_effort": reasoning_effort,
                    "applied_enabled_execution_options": [
                        option.value for option in enabled_execution_options
                    ],
                    "applied_profile_generation": (
                        RDBAgentSession.applied_profile_generation + 1
                    ),
                },
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            raise ValueError("AgentSession not found")
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def replace_stale_applied_inference_profiles(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        valid_model_target_labels: Sequence[str],
        model_target_label: str,
        reasoning_effort: ModelReasoningEffort | None,
        enabled_execution_options: Sequence[ModelExecutionOptionId],
    ) -> int:
        """Replace active Session profiles whose labels left the Agent option list."""
        if not valid_model_target_labels:
            raise ValueError("Agent must have at least one valid model target label")

        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.applied_model_target_label.is_not(None),
                    ~RDBAgentSession.applied_model_target_label.in_(
                        valid_model_target_labels
                    ),
                ],
                values={
                    "applied_model_target_label": model_target_label,
                    "applied_reasoning_effort": reasoning_effort,
                    "applied_enabled_execution_options": [
                        option.value for option in enabled_execution_options
                    ],
                    "applied_profile_generation": (
                        RDBAgentSession.applied_profile_generation + 1
                    ),
                    "updated_at": sa.func.now(),
                },
            ).returning(RDBAgentSession.id)
        )
        replaced_session_ids = result.scalars().all()
        await session.write_session.flush()
        return len(replaced_session_ids)

    async def mark_running(self, session: WriteSession, session_id: str) -> None:
        """Transition AgentSession run state to RUNNING."""
        updated_id = await session.write_session.scalar(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                ],
                values={
                    "run_state": AgentSessionRunState.RUNNING,
                    "run_heartbeat_at": sa.func.now(),
                },
            ).returning(RDBAgentSession.id)
        )
        if updated_id is None:
            raise ValueError("Active AgentSession not found")
        await session.write_session.flush()

    async def mark_running_for_input_wakeup(
        self,
        session: WriteSession,
        session_id: str,
    ) -> None:
        """Transition AgentSession to RUNNING recovery target on buffered input."""
        updated_id = await session.write_session.scalar(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.run_state != AgentSessionRunState.RUNNING,
                ],
                values={
                    "run_state": AgentSessionRunState.RUNNING,
                    "run_heartbeat_at": sa.func.now(),
                },
            ).returning(RDBAgentSession.id)
        )
        if updated_id is not None:
            await session.write_session.flush()
            return
        current = (
            await session.write_session.execute(
                sa.select(
                    RDBAgentSession.status,
                    RDBAgentSession.run_state,
                )
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
                .where(RDBAgentSession.id == session_id)
            )
        ).one_or_none()
        if current != (
            AgentSessionStatus.ACTIVE,
            AgentSessionRunState.RUNNING,
        ):
            raise ValueError("Active AgentSession not found")
        await session.write_session.flush()

    async def admit_input_wakeup(
        self,
        session: WriteSession,
        session_id: str,
    ) -> AgentSession | None:
        """Atomically validate an input-eligible Session and request its wake."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.stop_requested_at.is_(None),
                ],
                values={
                    "run_state": AgentSessionRunState.RUNNING,
                    "run_heartbeat_at": sa.case(
                        (
                            RDBAgentSession.run_state != AgentSessionRunState.RUNNING,
                            sa.func.now(),
                        ),
                        else_=RDBAgentSession.run_heartbeat_at,
                    ),
                },
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def consume_pending_idle_continuation(
        self,
        session: WriteSession,
        *,
        session_id: str,
        run_id: str,
        continue_running: bool,
        allow_archived_scheduled_continuation: bool,
    ) -> bool:
        """Atomically consume one matching idle continuation boundary."""
        allowed_statuses = [AgentSessionStatus.ACTIVE]
        if allow_archived_scheduled_continuation:
            allowed_statuses.append(AgentSessionStatus.ARCHIVED)
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
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status.in_(allowed_statuses),
                    RDBConversation.pending_idle_continuation_run_id == run_id,
                ],
                values={**values},
            ).returning(RDBAgentSession.id)
        )
        await session.write_session.flush()
        return result.scalar_one_or_none() is not None

    async def enqueue_pending_command(
        self,
        session: WriteSession,
        *,
        session_id: str,
        command_id: str,
        command_name: str,
        payload: dict[str, object],
        requester_user_id: str | None,
    ) -> AgentSession | None:
        """Store single pending command in idle AgentSession and mark running."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                    RDBConversation.pending_command_id.is_(None),
                ],
                values={
                    "pending_command_id": command_id,
                    "pending_command_name": command_name,
                    "pending_command_payload": payload,
                    "pending_command_requester_user_id": requester_user_id,
                    "pending_command_created_at": sa.func.now(),
                    "run_state": AgentSessionRunState.RUNNING,
                    "run_heartbeat_at": sa.func.now(),
                },
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def get_pending_command_by_session_id(
        self,
        session: ReadSession,
        session_id: str,
    ) -> PendingSessionCommand | None:
        """Fetch pending command for AgentSession."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.id == session_id,
                RDBConversation.pending_command_id.is_not(None),
            )
        )
        rdb = result.scalar_one_or_none()
        if (
            rdb is None
            or rdb.conversation is None
            or rdb.conversation.pending_command_id is None
            or rdb.conversation.pending_command_name is None
            or rdb.conversation.pending_command_payload is None
            or rdb.conversation.pending_command_created_at is None
        ):
            return None
        return PendingSessionCommand(
            id=rdb.conversation.pending_command_id,
            name=rdb.conversation.pending_command_name,
            payload=dict(rdb.conversation.pending_command_payload),
            requester_user_id=rdb.conversation.pending_command_requester_user_id,
            created_at=rdb.conversation.pending_command_created_at,
        )

    async def clear_pending_command(
        self,
        session: WriteSession,
        *,
        session_id: str,
        command_id: str,
    ) -> None:
        """Remove processed pending command."""
        await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBConversation.pending_command_id == command_id,
                ],
                values={
                    "pending_command_id": None,
                    "pending_command_name": None,
                    "pending_command_payload": None,
                    "pending_command_requester_user_id": None,
                    "pending_command_created_at": None,
                },
            )
        )
        await session.write_session.flush()

    async def request_stop(
        self,
        session: WriteSession,
        *,
        session_id: str,
        stop_request_id: str,
        stop_requester_user_id: str | None,
    ) -> AgentSession | None:
        """Record stop intent on running AgentSession."""
        result = await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
                ],
                values={
                    "stop_requested_at": sa.func.now(),
                    "stop_requester_user_id": stop_requester_user_id,
                    "stop_request_id": stop_request_id,
                },
            ).returning(RDBAgentSession.id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.write_session.flush()
        return self._build(await self._refresh_conversation(session, rdb))

    async def has_stop_request(
        self,
        session: ReadSession,
        session_id: str,
    ) -> bool:
        """Check whether AgentSession has stop intent."""
        result = await session.read_session.execute(
            sa.select(RDBAgentSession.id)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.stop_requested_at.is_not(None),
            )
        )
        return result.scalar_one_or_none() is not None

    async def clear_stop_request(
        self,
        session: WriteSession,
        session_id: str,
    ) -> None:
        """Remove processed stop intent."""
        await session.write_session.execute(
            self._conversation_update(
                predicates=[RDBAgentSession.id == session_id],
                values={
                    "stop_requested_at": None,
                    "stop_requester_user_id": None,
                    "stop_request_id": None,
                },
            )
        )
        await session.write_session.flush()

    async def mark_idle(self, session: WriteSession, session_id: str) -> None:
        """Transition AgentSession run state to IDLE."""
        await session.write_session.execute(
            self._conversation_update(
                predicates=[RDBAgentSession.id == session_id],
                values={
                    "run_state": AgentSessionRunState.IDLE,
                    "stop_requested_at": None,
                    "stop_requester_user_id": None,
                    "stop_request_id": None,
                },
            )
        )
        await session.write_session.flush()

    async def heartbeat_running(self, session: WriteSession, session_id: str) -> None:
        """Update heartbeat time of RUNNING AgentSession."""
        await session.write_session.execute(
            self._conversation_update(
                predicates=[
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
                ],
                values={"run_heartbeat_at": sa.func.now()},
            )
        )
        await session.write_session.flush()

    async def find_stuck_running(
        self,
        session: ReadSession,
        *,
        stale_threshold: datetime.timedelta,
        limit: int,
    ) -> list[AgentSession]:
        """Fetch old RUNNING AgentSession list."""
        cutoff = sa.func.now() - stale_threshold
        result = await session.read_session.execute(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
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
        session: WriteSession,
        *,
        agent_session_id: str,
        root_session_handle: str,
        workspace_id: str,
        agent_id: str,
        authority: _RootCreationAuthority,
    ) -> None:
        """Create the root SessionAgent and context for a root AgentSession."""
        context_id = uuid7().hex
        root_session_agent_id = uuid7().hex
        if isinstance(authority, _RuntimeFreeRootCreationAuthority):
            agent_runtime_id = None
            working_folder_binding_state = SessionWorkingFolderBindingState.NONE
        else:
            agent_runtime_id = authority.agent_runtime_id
            working_folder_binding_state = SessionWorkingFolderBindingState.PENDING
        context = RDBSessionAgentContext(
            agent_id=agent_id,
            workspace_id=workspace_id,
            agent_runtime_id=agent_runtime_id,
            working_folder_path=None,
            working_folder_binding_state=working_folder_binding_state,
            working_folder_cleanup_status=(
                SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
            ),
            working_folder_cleanup_summary=None,
            working_folder_cleanup_completed_at=None,
        )
        context.id = context_id
        session.write_session.add(context)
        await session.write_session.flush()
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
        session.write_session.add(root_agent)
        context.root_session_agent_id = root_session_agent_id

    async def _root_creation_authority(
        self,
        session: WriteSession,
        *,
        agent_id: str,
    ) -> _RootCreationAuthority:
        """Prepare root authority and lock its managed Runtime before FK writes."""
        row = (
            await session.write_session.execute(
                sa.select(
                    RDBAgent.lifecycle_status,
                    RDBAgent.runtime_capability,
                    RDBAgent.runtime_capability_version,
                ).where(RDBAgent.id == agent_id)
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("Agent is unavailable")
        lifecycle_status, runtime_capability, runtime_capability_version = row
        if lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            raise ValueError("Agent is not active for Session creation")
        if runtime_capability is AgentRuntimeCapability.NONE:
            return _RuntimeFreeRootCreationAuthority(
                runtime_capability_version=runtime_capability_version,
            )
        if runtime_capability is not AgentRuntimeCapability.MANAGED:
            raise RuntimeError("Agent Runtime is being removed")
        runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
        locked_runtime_id = await session.write_session.scalar(
            sa.select(RDBAgentRuntime.id)
            .where(RDBAgentRuntime.id == runtime.id)
            .with_for_update(read=True, key_share=True)
        )
        if locked_runtime_id is None:
            raise RuntimeError("Agent Runtime is unavailable for Session creation")
        return _ManagedRootCreationAuthority(
            runtime_capability_version=runtime_capability_version,
            agent_runtime_id=locked_runtime_id,
        )

    async def _confirm_root_creation_authority(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        authority: _RootCreationAuthority,
    ) -> None:
        """Fence root creation with one final conditional Agent update."""
        expected_runtime_capability = (
            AgentRuntimeCapability.NONE
            if isinstance(authority, _RuntimeFreeRootCreationAuthority)
            else AgentRuntimeCapability.MANAGED
        )
        confirmed_id = await session.write_session.scalar(
            sa.update(RDBAgent)
            .where(
                RDBAgent.id == agent_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                RDBAgent.runtime_capability == expected_runtime_capability,
                RDBAgent.runtime_capability_version
                == authority.runtime_capability_version,
            )
            .values(
                runtime_capability_version=RDBAgent.runtime_capability_version,
            )
            .returning(RDBAgent.id)
        )
        if confirmed_id is None:
            raise RuntimeError(
                "Agent Runtime authority changed during Session creation"
            )

    async def _create_linked_subagent_session(
        self,
        session: WriteSession,
        *,
        workspace_id: str,
        agent_id: str,
        title: str | None,
        lifecycle_root_session_id: str,
    ) -> RDBAgentSession:
        """Create the hidden AgentSession backing a child SessionAgent."""
        for _ in range(SESSION_HANDLE_INSERT_ATTEMPTS):
            rdb = await self._insert_conversation_session(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_kind=AgentSessionKind.SUBAGENT,
                title=title,
                primary_kind=None,
                product_mode=None,
                associated_user_id=None,
                start_reason=AgentSessionStartReason.INITIAL,
                lifecycle_root_session_id=lifecycle_root_session_id,
            )
            if rdb is not None:
                await session.write_session.flush()
                return rdb
        raise RuntimeError("AgentSession handle generation exhausted retry attempts")

    @staticmethod
    def _require_conversation(current: RDBAgentSession) -> RDBConversation:
        """Require the joined public profile, without inventing identity fields."""
        profile = current.conversation
        if profile is None:
            raise ValueError("Session has no public Conversation profile")
        return profile

    async def _insert_conversation_session(
        self,
        session: WriteSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_kind: AgentSessionKind,
        title: str | None,
        primary_kind: AgentSessionPrimaryKind | None,
        product_mode: AgentSessionProductMode | None,
        associated_user_id: str | None,
        start_reason: AgentSessionStartReason,
        lifecycle_root_session_id: str | None,
    ) -> RDBAgentSession | None:
        """Rollback the whole paired creation trial on either uniqueness race."""
        async with session.write_session.begin_nested() as trial:
            current = await session.write_session.scalar(
                pg_insert(RDBAgentSession)
                .values(
                    id=uuid7().hex,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    lifecycle_root_session_id=lifecycle_root_session_id,
                    status=AgentSessionStatus.ACTIVE,
                    start_reason=start_reason,
                )
                .returning(RDBAgentSession)
            )
            if current is None:
                raise RuntimeError("Common Session insertion did not return a row")
            profile = await session.write_session.scalar(
                pg_insert(RDBConversation)
                .values(
                    session_id=current.id,
                    agent_id=agent_id,
                    session_status=current.status,
                    handle=generate_session_handle(),
                    session_kind=session_kind,
                    title=title,
                    primary_kind=primary_kind,
                    product_mode=product_mode,
                    associated_user_id=associated_user_id,
                )
                .on_conflict_do_nothing()
                .returning(RDBConversation)
            )
            if profile is None:
                await trial.rollback()
                return None
            current.conversation = profile
            return current

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

    @staticmethod
    def _conversation_update(
        *, predicates: Sequence[sa.ColumnElement[bool]], values: Mapping[str, object]
    ) -> sa.Update:
        """Mutate one joined public identity without dual storage writers."""
        common_table = RDBAgentSession.__table__
        conversation_table = RDBConversation.__table__
        if not isinstance(common_table, sa.Table) or not isinstance(
            conversation_table, sa.Table
        ):
            raise TypeError("Session and Conversation storage must be concrete tables")
        conversation_fields = frozenset(
            [
                "associated_user_id",
                "handle",
                "last_user_input_at",
                "pending_command_created_at",
                "pending_command_id",
                "pending_command_name",
                "pending_command_payload",
                "pending_command_requester_user_id",
                "pending_idle_continuation_run_id",
                "pinned",
                "primary_kind",
                "primary_model_reservation",
                "primary_model_reservation_generation",
                "product_mode",
                "session_kind",
                "title",
                "title_generated_at",
                "title_generation_event_id",
                "title_model_operation_state",
                "title_source",
            ]
        )
        profile_values = {
            key: value for key, value in values.items() if key in conversation_fields
        }
        common_values = {
            key: value
            for key, value in values.items()
            if key not in conversation_fields
        }
        if profile_values:
            locked = (
                sa.select(RDBAgentSession.id)
                .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
                .where(*predicates)
                # Serialize owner mutations while allowing live FK references.
                .with_for_update(of=RDBAgentSession, key_share=True)
                .cte("locked_conversation_session")
            )
            changed = (
                sa.update(conversation_table)
                .where(
                    RDBConversation.session_id.in_(sa.select(locked.c.id)),
                    RDBConversation.session_id == RDBAgentSession.id,
                    *predicates,
                )
                .values(**profile_values)
                .returning(conversation_table.c.session_id)
                .cte("changed_conversation")
            )
            return (
                sa.update(common_table)
                .where(RDBAgentSession.id.in_(sa.select(changed.c.session_id)))
                .values(**(common_values or {"updated_at": sa.func.now()}))
            )
        return (
            sa.update(RDBAgentSession)
            .where(RDBConversation.session_id == RDBAgentSession.id, *predicates)
            .values(**common_values)
            .execution_options(synchronize_session="fetch")
        )

    @staticmethod
    async def _refresh_conversation(
        session: ReadSession, current: RDBAgentSession | str
    ) -> RDBAgentSession:
        """Reload the authoritative joined values after a multi-table mutation."""
        session_id = current if isinstance(current, str) else current.id
        updated = await session.read_session.scalar(
            sa.select(RDBAgentSession)
            .join(RDBConversation, RDBConversation.session_id == RDBAgentSession.id)
            .where(RDBAgentSession.id == session_id)
            .execution_options(populate_existing=True)
        )
        if updated is None:
            raise ValueError("Public Conversation is unavailable")
        return updated

    def _build(self, rdb: RDBAgentSession) -> AgentSession:
        """Project a required Conversation profile over the shared Session."""
        conversation = rdb.conversation
        if conversation is None:
            raise ValueError("Session has no public Conversation profile")
        common = SessionExecutionRecordRepository.build(rdb)
        return AgentSession(
            **common.model_dump(
                exclude={"lifecycle_root_session_id", "model_file_gc_updated_at"}
            ),
            associated_user_id=conversation.associated_user_id,
            handle=conversation.handle,
            last_user_input_at=conversation.last_user_input_at,
            pending_command_created_at=conversation.pending_command_created_at,
            pending_command_id=conversation.pending_command_id,
            pending_command_name=conversation.pending_command_name,
            pending_command_payload=conversation.pending_command_payload,
            pending_command_requester_user_id=conversation.pending_command_requester_user_id,
            pending_idle_continuation_run_id=conversation.pending_idle_continuation_run_id,
            pinned=conversation.pinned,
            primary_kind=conversation.primary_kind,
            primary_model_reservation=(
                PrimaryModelReservation.model_validate(
                    conversation.primary_model_reservation
                )
                if conversation.primary_model_reservation is not None
                else None
            ),
            primary_model_reservation_generation=conversation.primary_model_reservation_generation,
            product_mode=conversation.product_mode,
            session_kind=conversation.session_kind,
            title=conversation.title,
            title_generated_at=conversation.title_generated_at,
            title_generation_event_id=conversation.title_generation_event_id,
            title_model_operation_state=(
                ModelOperationSnapshot.model_validate(
                    conversation.title_model_operation_state
                )
                if conversation.title_model_operation_state is not None
                else None
            ),
            title_source=conversation.title_source,
        )
