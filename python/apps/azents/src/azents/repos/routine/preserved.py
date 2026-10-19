"""SQL admission for work already preserved by the canonical archive transaction."""

import sqlalchemy as sa

from azents.core.enums import AgentRunStatus, AgentSessionStatus, MailboxItemKind
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.repos.routine.state import ROUTINE_STATE_NAMESPACE


def preserved_routine_work_exists() -> sa.ColumnElement[bool]:
    """Correlate exact started context and ordinary active/idle continuation work."""
    continuation = sa.exists(
        sa.select(1)
        .select_from(RDBMailboxItem)
        .where(
            RDBMailboxItem.session_id == RDBAgentSession.id,
            RDBMailboxItem.kind == MailboxItemKind.ROUTINE_CONTINUATION,
        )
    ).correlate(RDBAgentSession)
    idle = sa.exists(
        sa.select(1)
        .select_from(RDBConversation)
        .where(
            RDBConversation.session_id == RDBAgentSession.id,
            RDBConversation.pending_idle_continuation_run_id == RDBAgentRun.id,
        )
    ).correlate(RDBAgentSession, RDBAgentRun)
    return sa.exists(
        sa.select(1)
        .select_from(RDBToolkitState)
        .join(
            RDBAgentRun,
            RDBAgentRun.id == RDBToolkitState.state_json["current_run_id"].astext,
        )
        .where(
            RDBToolkitState.session_id == RDBAgentSession.id,
            RDBToolkitState.agent_id == RDBAgentSession.agent_id,
            RDBToolkitState.toolkit_namespace == ROUTINE_STATE_NAMESPACE,
            RDBToolkitState.state_name.startswith("execution:"),
            RDBToolkitState.state_json["phase"].astext.in_(("started", "completed")),
            RDBToolkitState.state_json["context"]["scope"]["session_id"].astext
            == RDBAgentSession.id,
            RDBToolkitState.state_json["context"]["scope"]["agent_id"].astext
            == RDBAgentSession.agent_id,
            RDBToolkitState.state_json["context"]["scope"]["workspace_id"].astext
            == RDBAgentSession.workspace_id,
            RDBAgentRun.session_id == RDBAgentSession.id,
            RDBAgentRun.scheduled_task_cycle_id.is_(None),
            sa.or_(
                RDBAgentRun.status.in_(
                    (AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
                ),
                sa.and_(
                    RDBAgentRun.status == AgentRunStatus.COMPLETED,
                    sa.or_(idle, continuation),
                ),
            ),
        )
    ).correlate(RDBAgentSession)


def archived_routine_execution_allowed() -> sa.ColumnElement[bool]:
    """This is an exception for retained execution, never new archived admission."""
    return sa.and_(
        RDBAgentSession.status == AgentSessionStatus.ARCHIVED,
        preserved_routine_work_exists(),
    )
