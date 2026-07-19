"""Durable subagent terminal result mailbox delivery."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunStatus,
    SessionAgentKind,
)
from azents.engine.events.types import AgentRunState
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.services.agent_mailbox import AgentMailboxService

logger = logging.getLogger(__name__)

DeliveryRepairSource = Literal[
    "terminal_boundary",
    "parent_wait",
    "source_session_reuse",
]


@dataclasses.dataclass(frozen=True)
class TerminalResultDeliverySummary:
    """Best-effort terminal result delivery attempt summary."""

    attempted: int
    enqueued: int
    already_finalized: int
    failed: int


@dataclasses.dataclass(frozen=True)
class SubagentTerminalResultService:
    """Deliver eligible terminal subagent Runs to their direct parent mailbox."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_mailbox_service: Annotated[AgentMailboxService, Depends(AgentMailboxService)]

    async def deliver_pending_for_source_session(
        self,
        source_session_id: str,
        *,
        repair_source: DeliveryRepairSource,
    ) -> TerminalResultDeliverySummary:
        """Attempt every eligible terminal Run for one source session."""
        try:
            async with self.session_manager() as session:
                repository = self.agent_run_repository
                list_candidate_ids = (
                    repository.list_parent_result_delivery_candidate_ids_by_session_id
                )
                candidate_ids = await list_candidate_ids(
                    session,
                    session_id=source_session_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to list pending subagent terminal results",
                extra={
                    "source_session_id": source_session_id,
                    "repair_source": repair_source,
                },
            )
            return TerminalResultDeliverySummary(0, 0, 0, 1)
        enqueued = 0
        finalized = 0
        failed = 0
        for run_id in candidate_ids:
            try:
                delivered = await self._deliver_one(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                failed += 1
                logger.exception(
                    "Failed to deliver subagent terminal result",
                    extra={
                        "run_id": run_id,
                        "source_session_id": source_session_id,
                        "repair_source": repair_source,
                    },
                )
                continue
            if delivered:
                enqueued += 1
                logger.info(
                    "Enqueued subagent terminal result",
                    extra={
                        "run_id": run_id,
                        "source_session_id": source_session_id,
                        "repair_source": repair_source,
                    },
                )
            else:
                finalized += 1
        return TerminalResultDeliverySummary(
            attempted=len(candidate_ids),
            enqueued=enqueued,
            already_finalized=finalized,
            failed=failed,
        )

    async def deliver_pending_for_parent_children(
        self,
        parent_session_id: str,
        *,
        repair_source: DeliveryRepairSource,
    ) -> TerminalResultDeliverySummary:
        """Repair eligible results from the current agent's direct children."""
        async with self.session_manager() as session:
            parent = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    parent_session_id,
                )
            )
            if parent is None:
                return TerminalResultDeliverySummary(0, 0, 0, 0)
            descendants = (
                await self.agent_session_repository.list_descendant_session_agents(
                    session,
                    session_agent_id=parent.id,
                    include_self=False,
                )
            )
            child_session_ids = [
                descendant.agent_session_id
                for descendant in descendants
                if descendant.parent_session_agent_id == parent.id
            ]
        summaries = [
            await self.deliver_pending_for_source_session(
                child_session_id,
                repair_source=repair_source,
            )
            for child_session_id in child_session_ids
        ]
        return TerminalResultDeliverySummary(
            attempted=sum(summary.attempted for summary in summaries),
            enqueued=sum(summary.enqueued for summary in summaries),
            already_finalized=sum(summary.already_finalized for summary in summaries),
            failed=sum(summary.failed for summary in summaries),
        )

    async def _deliver_one(self, run_id: str) -> bool:
        """Deliver one terminal Run in a single locked transaction."""
        async with self.session_manager() as session:
            run = await self.agent_run_repository.lock_by_id(session, run_id)
            if run is None:
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
            source = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    run.session_id,
                )
            )
            if source is None or source.kind != SessionAgentKind.SUBAGENT:
                return False
            if source.parent_session_agent_id is None:
                raise ValueError("Subagent has no direct parent")
            target = await self.agent_session_repository.get_session_agent_by_id(
                session,
                source.parent_session_agent_id,
            )
            if target is None:
                raise ValueError("Direct parent SessionAgent not found")
            input_buffer = await self.agent_mailbox_service.enqueue_terminal_result(
                session,
                source=source,
                target=target,
                run=run,
                content=_terminal_result_content(run),
            )
            finalized = await self.agent_run_repository.mark_parent_result_enqueued(
                session,
                run_id=run.id,
                input_buffer_id=input_buffer.id,
                enqueued_at=datetime.datetime.now(datetime.UTC),
            )
            return (
                finalized.parent_result_delivery_state
                == AgentRunParentResultDeliveryState.ENQUEUED
            )


def _terminal_result_content(run: AgentRunState) -> str:
    """Return the user-safe terminal projection or a fixed status fallback."""
    message = _sanitized_terminal_result_message(run)
    if message is not None:
        return message
    match run.status:
        case AgentRunStatus.COMPLETED:
            return "The agent run completed without a result message."
        case AgentRunStatus.FAILED:
            return "The agent run failed."
        case AgentRunStatus.STOPPED:
            return "The agent run was stopped."
        case AgentRunStatus.INTERRUPTED:
            return "The agent run was interrupted."
        case AgentRunStatus.CANCELLED:
            return "The agent run was cancelled before completing."
        case _:
            raise ValueError("Terminal result content requires a terminal Run")


def _sanitized_terminal_result_message(run: AgentRunState) -> str | None:
    """Return safe terminal text after removing provider failure details."""
    if run.terminal_result_message is None:
        return None
    message = run.terminal_result_message.strip()
    if not message:
        return None
    if run.status is AgentRunStatus.FAILED and message.startswith(
        "Model provider error:"
    ):
        return None
    return message
