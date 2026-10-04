"""Completed database operations for best-effort subagent result repair."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunStatus,
    SessionAgentKind,
)
from azents.core.terminal_result import terminal_result_content
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository


@dataclasses.dataclass(frozen=True)
class SubagentTerminalResultRepository:
    """Own candidate snapshots and each atomic repair delivery transaction."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_mailbox_repository: Annotated[
        AgentMailboxRepository, Depends(AgentMailboxRepository)
    ]

    async def list_candidate_run_ids(self, source_session_id: str) -> list[str]:
        """Read repair candidates in a completed transaction."""
        async with self.session_manager() as session:
            repository = self.agent_run_repository
            list_candidate_ids = (
                repository.list_parent_result_delivery_candidate_ids_by_session_id
            )
            return await list_candidate_ids(
                session,
                session_id=source_session_id,
            )

    async def list_direct_child_session_ids(self, parent_session_id: str) -> list[str]:
        """Read only the parent's direct children in a completed transaction."""
        async with self.session_manager() as session:
            parent = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    parent_session_id,
                )
            )
            if parent is None:
                return []
            descendants = (
                await self.agent_session_repository.list_descendant_session_agents(
                    session,
                    session_agent_id=parent.id,
                    include_self=False,
                )
            )
            return [
                descendant.agent_session_id
                for descendant in descendants
                if descendant.parent_session_agent_id == parent.id
            ]

    async def deliver_one(self, run_id: str) -> bool:
        """Complete one repair delivery with its original failure semantics."""
        async with self.session_manager() as session:
            candidate = await self.agent_run_repository.get_by_id(session, run_id)
            if candidate is None:
                return False
            source = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    candidate.session_id,
                )
            )
            if source is None or source.kind != SessionAgentKind.SUBAGENT:
                return False
            locked_root = await self.agent_session_repository.lock_session_agent_by_id(
                session,
                source.root_session_agent_id,
            )
            if locked_root is None:
                return False
            run = await self.agent_run_repository.lock_by_id(session, run_id)
            if run is None or run.session_id != source.agent_session_id:
                return False
            if run.parent_result_delivery_state is not None:
                return False
            if run.status not in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.FAILED,
                AgentRunStatus.STOPPED,
                AgentRunStatus.INTERRUPTED,
                AgentRunStatus.CANCELLED,
            }:
                return False
            if source.parent_session_agent_id is None:
                raise ValueError("Subagent has no direct parent")
            target = await self.agent_session_repository.get_session_agent_by_id(
                session,
                source.parent_session_agent_id,
            )
            if target is None:
                raise ValueError("Direct parent SessionAgent not found")
            mailbox_item = await self.agent_mailbox_repository.enqueue_terminal_result(
                session,
                source=source,
                target=target,
                run=run,
                content=terminal_result_content(
                    status=run.status,
                    message=run.terminal_result_message,
                ),
            )
            finalized = await self.agent_run_repository.mark_parent_result_enqueued(
                session,
                run_id=run.id,
                mailbox_item_id=mailbox_item.id,
                enqueued_at=datetime.datetime.now(datetime.UTC),
            )
            return (
                finalized.parent_result_delivery_state
                == AgentRunParentResultDeliveryState.ENQUEUED
            )
