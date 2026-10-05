"""Native PostgreSQL proof of Human input/worker Agent-before-Session ordering."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

import sqlalchemy as sa
from azcommon.result import Failure
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.agent_session_input_data import AgentSessionInputInactiveSession
from azents.core.enums import (
    AgentRuntimeCapability,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.engine.run.input import InputMessage
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.agent_session_input_operations import (
    AgentSessionInputOperationsRepository,
)
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox_database import MailboxDatabaseRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.services.agent_session_input_test import (
    _TEST_INFERENCE_PROFILE,
    _active_profile_repository,
    _ExchangeFileService,
    _mailbox_admission_repository,
    _root_agent_session_creation_service,
    _WorkspaceUserRepositoryDouble,
)
from azents.worker.session.idle_continuation_lock_test import (
    _cleanup_workspace_fixture,
    _wait_for_database_blocker,
)


class _ObservedAgentRepository(AgentRepository):
    """Expose the actual backend reaching Human admission's Agent lock."""

    def __init__(self) -> None:
        self.backend_pid: asyncio.Future[int] = (
            asyncio.get_running_loop().create_future()
        )

    async def lock_by_id(self, session: WriteSession, agent_id: str) -> Agent | None:
        pid = await session.write_session.scalar(sa.text("SELECT pg_backend_pid()"))
        assert isinstance(pid, int)
        self.backend_pid.set_result(pid)
        return await super().lock_by_id(session, agent_id)


async def test_human_admission_cannot_hold_session_while_waiting_for_worker_agent(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Worker can acquire Session while Human input waits on its Agent lock."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    sessions = AgentSessionRepository()
    async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_raw:
        setup = ReadWriteSession(setup_raw)
        workspace_id = await _create_workspace(setup, f"input-lock-{suffix}")
        agent_id = await _create_agent(
            setup,
            workspace_id,
            f"input-lock-{suffix}",
            runtime_capability=AgentRuntimeCapability.NONE,
        )
        root = await sessions.create(
            setup,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                title=None,
            ),
        )
        await setup_raw.commit()

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            async with raw.begin():
                yield ReadWriteSession(raw)

    agents = _ObservedAgentRepository()
    operations = AgentSessionInputOperationsRepository(
        agent_repository=agents,
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        agent_session_repository=sessions,
        root_session_repository=_root_agent_session_creation_service(),
        chat_write_request_repository=ChatWriteRequestRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        workspace_user_repository=_WorkspaceUserRepositoryDouble(),
        attachment_claim_repository=_ExchangeFileService(),
        mailbox_repository=MailboxRepository(),
        mailbox_database_repository=MailboxDatabaseRepository(
            mailbox_item_repository=MailboxRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            action_execution_repository=ActionExecutionRepository(),
        ),
        mailbox_admission_repository=_mailbox_admission_repository(manager),
        active_profile_repository=_active_profile_repository(manager),
        session_manager=manager,
    )
    human = None
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as worker_raw:
            worker = ReadWriteSession(worker_raw)
            await AgentRepository().lock_by_id(worker, agent_id)
            worker_pid = await worker_raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(worker_pid, int)
            human = asyncio.create_task(
                operations.create_buffered_agent_input(
                    agent_id=agent_id,
                    agent_session_id=root.id,
                    message=InputMessage(
                        text="input", headers=[], metadata={}, attachments=[]
                    ),
                    inference_profile=_TEST_INFERENCE_PROFILE,
                    user_id="unused-user",
                    request_payload={},
                )
            )
            human_pid = await asyncio.wait_for(agents.backend_pid, timeout=5)
            await asyncio.wait_for(
                _wait_for_database_blocker(
                    rdb_engine,
                    blocked_pid=human_pid,
                    blocker_pid=worker_pid,
                ),
                timeout=5,
            )
            # Match worker_executor_model commit's exact Agent -> Session prefix.
            locked = await asyncio.wait_for(
                sessions.lock_by_id(worker, root.id), timeout=5
            )
            assert locked is not None
            await worker_raw.execute(
                sa.update(RDBAgentSession)
                .where(
                    RDBAgentSession.id == root.id,
                )
                .values(status=AgentSessionStatus.ARCHIVED)
            )
            await worker_raw.commit()
        result = await asyncio.wait_for(human, timeout=5)
        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputInactiveSession)
    finally:
        if human is not None and not human.done():
            human.cancel()
            with suppress(asyncio.CancelledError):
                await human
        await _cleanup_workspace_fixture(rdb_engine, workspace_id)
