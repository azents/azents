"""Completed database-only Mailbox runtime reads."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentRunStatus,
    AgentSessionStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.mailbox_data import MailboxItem
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository


@dataclasses.dataclass(frozen=True)
class MailboxPreparationRead:
    """One detached Session identity and its current FIFO head."""

    agent_session: AgentSession | None
    buffer: MailboxItem | None


@dataclasses.dataclass(frozen=True)
class MailboxRuntimeOperations:
    """Own runtime Mailbox read transaction lifetimes."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    mailbox_item_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]

    async def _first_promotable_in_session(
        self, session: ReadSession, session_id: str
    ) -> MailboxItem | None:
        pending = await self.mailbox_item_repository.list_for_flush(
            session, session_id, limit=1
        )
        return pending[0] if pending else None

    async def first_promotable(self, session_id: str) -> MailboxItem | None:
        async with self.session_manager() as session:
            return await self._first_promotable_in_session(session, session_id)

    async def has_pending_wake_items(self, session_id: str) -> bool:
        async with self.session_manager() as session:
            pending = await self.mailbox_item_repository.list_for_flush(
                session, session_id
            )
            return any(
                buffer.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
                for buffer in pending
            )

    async def has_pending_agent_messages(self, session_id: str) -> bool:
        async with self.session_manager() as session:
            return await self.mailbox_item_repository.has_by_session_id_and_kind(
                session, session_id=session_id, kind=MailboxItemKind.AGENT_MESSAGE
            )

    async def read_preparation(self, session_id: str) -> MailboxPreparationRead:
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            buffer = await self._first_promotable_in_session(session, session_id)
            return MailboxPreparationRead(agent_session=agent_session, buffer=buffer)

    async def attachment_authority(
        self,
        *,
        session_id: str,
        active_run_id: str,
        agent_id: str,
        workspace_id: str,
        owner_generation: int,
    ) -> SessionResourceAuthority | None:
        async with self.session_manager() as session:
            current = await self.agent_session_repository.get_by_id(session, session_id)
            get_root = (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )
            root = await get_root(session, session_id)
            run = await self.agent_run_repository.get_by_id(session, active_run_id)
            if (
                current is None
                or root is None
                or run is None
                or run.session_id != session_id
                or run.status not in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
                or current.workspace_id != workspace_id
                or current.agent_id != agent_id
                or current.status is not AgentSessionStatus.ACTIVE
                or current.owner_generation != owner_generation
            ):
                return None
            return SessionResourceAuthority(
                workspace_id=current.workspace_id,
                agent_id=current.agent_id,
                session_id=session_id,
                root_session_id=root.agent_session_id,
                run_id=run.id,
                run_index=run.run_index,
                owner_generation=owner_generation,
            )
