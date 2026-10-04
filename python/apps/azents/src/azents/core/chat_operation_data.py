"""Detached internal Chat database snapshots and lifecycle commands."""

import dataclasses
import datetime

from azents.core.action_execution_data import ActionExecutionProjection
from azents.core.agent_session_data import AgentSession, SessionWorkingFolderContext
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.goal import GoalStateSnapshot
from azents.core.mailbox_data import MailboxItem
from azents.core.session_lifecycle import SessionLifecycleTransitionContext
from azents.engine.events.types import AgentRunState
from azents.engine.tools.todo import TodoStateSnapshot


@dataclasses.dataclass(frozen=True)
class ChatArchiveDatabaseResult:
    """Committed root archive and captured external cleanup work."""

    root_session_id: str
    subtree_session_ids: tuple[str, ...]
    working_folder_context: SessionWorkingFolderContext
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclasses.dataclass(frozen=True)
class ChatLiveDatabaseSnapshot:
    """Authorized durable state captured before volatile transport reads."""

    agent_session: AgentSession
    mailbox_items: tuple[MailboxItem, ...]
    run: AgentRunState | None
    goal: GoalStateSnapshot
    todo: TodoStateSnapshot
    action_executions: tuple[ActionExecutionProjection, ...]


@dataclasses.dataclass(frozen=True)
class ChatArchiveMutation:
    """Exact locked root transition without executable callbacks."""

    context: SessionLifecycleTransitionContext
    archived_at: datetime.datetime
    purge_after: datetime.datetime | None
    policy_revision: int
    retention_days: int | None
