"""Database-only Session folder setup admission shared by input producers."""

import datetime

from azents.core.enums import (
    MailboxItemKind,
    MailboxSchedulingMode,
    SessionWorkingFolderBindingState,
)
from azents.engine.events.action_messages import CreateSessionWorkingFolderAction
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import MailboxEnqueue
from azents.repos.mailbox_database import MailboxDatabaseRepository


async def enqueue_missing_session_working_folder(
    session: WriteSession,
    *,
    session_id: str,
    agent_session_repository: AgentSessionRepository,
    mailbox_database_repository: MailboxDatabaseRepository,
    mailbox_admission_repository: MailboxAdmissionRepository,
) -> None:
    """Queue missing folder setup before a producer allocates its input order."""
    action = CreateSessionWorkingFolderAction()
    if await mailbox_database_repository.has_seen_action_type(
        session,
        session_id=session_id,
        action_type=action.type,
    ):
        return
    context = await agent_session_repository.get_working_folder_context_by_session_id(
        session,
        session_id=session_id,
    )
    if context is None:
        raise RuntimeError("Active root Session is missing working-folder context")
    if context.binding_state not in {
        SessionWorkingFolderBindingState.PENDING,
        SessionWorkingFolderBindingState.BOUND,
    }:
        return
    await mailbox_admission_repository.enqueue_in_session(
        session,
        MailboxEnqueue(
            session_id=session_id,
            kind=MailboxItemKind.ACTION_MESSAGE,
            scheduling_mode=MailboxSchedulingMode.QUEUE_ONLY,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            requested_enabled_execution_options=[],
            sender_user_id=None,
            order_group=None,
            order_sequence=0,
            content="",
            idempotency_key=f"session-working-folder:adoption:{context.id}",
            metadata={
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "source": "system",
            },
            action=action.model_dump(mode="json"),
            attachments=[],
            file_parts=[],
            payload=None,
        ),
    )
