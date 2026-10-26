"""Real-database coverage for shared folder setup admission."""

import asyncio
from uuid import uuid4

import pytest
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import MailboxEnqueue
from azents.repos.mailbox_database import MailboxDatabaseRepository
from azents.repos.session_working_folder_setup import (
    enqueue_missing_session_working_folder,
)


async def _root(manager: SessionManager[WriteSession]) -> str:
    """Create an eligible root without any initial setup action."""
    async with manager() as session:
        slug = f"folder-{uuid4().hex[:12]}"
        workspace_id = await _create_workspace(session, slug)
        agent_id = await _create_agent(session, workspace_id, slug)
        root = await AgentSessionRepository().create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                title=None,
            ),
        )
        return root.id


def _visibility() -> MailboxDatabaseRepository:
    return MailboxDatabaseRepository(
        mailbox_item_repository=MailboxRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        action_execution_repository=ActionExecutionRepository(),
    )


async def _prepare(
    session: WriteSession,
    manager: SessionManager[WriteSession],
    session_id: str,
    visibility: MailboxDatabaseRepository,
) -> None:
    await enqueue_missing_session_working_folder(
        session,
        session_id=session_id,
        agent_session_repository=AgentSessionRepository(),
        mailbox_database_repository=visibility,
        mailbox_admission_repository=MailboxAdmissionRepository(
            session_manager=manager,
            mailbox_item_repository=MailboxRepository(),
            agent_session_repository=AgentSessionRepository(),
        ),
    )


async def test_missing_setup_precedes_grouped_messages_and_is_idempotent(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """The persisted queue puts one setup before a channel-style history group."""
    session_id = await _root(rdb_session_manager)
    async with rdb_session_manager() as session:
        await _prepare(session, rdb_session_manager, session_id, _visibility())
        group = uuid7().hex
        admission = MailboxAdmissionRepository(
            session_manager=rdb_session_manager,
            mailbox_item_repository=MailboxRepository(),
            agent_session_repository=AgentSessionRepository(),
        )
        await admission.enqueue_many_in_session(
            session,
            [
                MailboxEnqueue(
                    session_id=session_id,
                    kind=MailboxItemKind.USER_MESSAGE,
                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=group,
                    order_sequence=index,
                    content=f"history {index}",
                    idempotency_key=f"history:{index}",
                    metadata={"source": "test"},
                    attachments=[],
                    file_parts=[],
                    action=None,
                    payload=None,
                )
                for index in range(2)
            ],
        )
    async with rdb_session_manager() as session:
        await _prepare(session, rdb_session_manager, session_id, _visibility())
        items = await MailboxRepository().list_by_session_id(session, session_id)
    assert len(items) == 3
    assert items[0].action == {"type": "create_session_working_folder"}
    assert items[0].scheduling_mode is MailboxSchedulingMode.QUEUE_ONLY
    assert items[0].order_group < group
    assert [item.content for item in items[1:]] == ["history 0", "history 1"]


async def test_folder_setup_rolls_back_with_failed_input(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A later admission failure cannot leave a standalone setup row."""
    session_id = await _root(rdb_session_manager)
    with pytest.raises(ValueError, match="late input failure"):
        async with rdb_session_manager() as session:
            await _prepare(session, rdb_session_manager, session_id, _visibility())
            raise ValueError("late input failure")
    async with rdb_session_manager() as session:
        assert await MailboxRepository().list_by_session_id(session, session_id) == []


async def test_concurrent_missing_setup_admission_uses_one_database_row(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Two transactions that both observe missing setup share the atomic upsert."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    session_id = await _root(manager)
    barrier = asyncio.Barrier(2)

    class SynchronizedVisibility(MailboxDatabaseRepository):
        async def has_seen_action_type(
            self, session: ReadSession, *, session_id: str, action_type: str
        ) -> bool:
            seen = await super().has_seen_action_type(
                session, session_id=session_id, action_type=action_type
            )
            assert not seen
            await barrier.wait()
            return seen

    visibility = SynchronizedVisibility(
        mailbox_item_repository=MailboxRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        action_execution_repository=ActionExecutionRepository(),
    )

    async def prepare() -> None:
        async with manager() as session:
            await _prepare(session, manager, session_id, visibility)

    await asyncio.wait_for(asyncio.gather(prepare(), prepare()), timeout=10)
    async with manager() as session:
        items = await MailboxRepository().list_by_session_id(session, session_id)
    assert len(items) == 1
    assert items[0].action == {"type": "create_session_working_folder"}
