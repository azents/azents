"""Transaction-aware terminal Run finalization and parent delivery."""

import dataclasses
import datetime
from enum import StrEnum
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunStatus,
    AgentSessionStatus,
    SessionAgentKind,
)
from azents.engine.events.types import AgentRunState
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.services.agent_mailbox import AgentMailboxService


class TerminalDeliveryDisposition(StrEnum):
    """Outcome of one terminal Run's direct-parent delivery attempt."""

    ENQUEUED = "enqueued"
    SUPPRESSED = "suppressed"
    ALREADY_FINALIZED = "already_finalized"
    INELIGIBLE = "ineligible"


@dataclasses.dataclass(frozen=True)
class TerminalFinalizationOutcome:
    """Structured terminal Run finalization outcome."""

    run_id: str
    disposition: TerminalDeliveryDisposition
    mailbox_item_id: str | None = None


@dataclasses.dataclass(frozen=True)
class TerminalRunFinalizationCoordinator:
    """Finalize terminal Runs and direct-parent mailbox delivery atomically."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_mailbox_service: Annotated[AgentMailboxService, Depends(AgentMailboxService)]

    async def finalize_run(
        self,
        run_id: str,
    ) -> TerminalFinalizationOutcome:
        """Finalize one already-terminal Run in a managed transaction."""
        async with self.session_manager() as session:
            return await self.finalize_run_in_session(session, run_id=run_id)

    async def finalize_run_in_session(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> TerminalFinalizationOutcome:
        """Finalize one terminal Run in the caller's transaction."""
        candidate = await self.agent_run_repository.get_by_id(session, run_id)
        if candidate is None:
            return TerminalFinalizationOutcome(
                run_id=run_id,
                disposition=TerminalDeliveryDisposition.INELIGIBLE,
            )
        user_stop_requested = await self.agent_session_repository.has_stop_request(
            session,
            candidate.session_id,
        )
        source = await self.agent_session_repository.get_session_agent_by_session_id(
            session,
            candidate.session_id,
        )
        if source is None:
            return TerminalFinalizationOutcome(
                run_id=run_id,
                disposition=TerminalDeliveryDisposition.INELIGIBLE,
            )
        locked_root = await self.agent_session_repository.lock_session_agent_by_id(
            session,
            source.root_session_agent_id,
        )
        if locked_root is None:
            return TerminalFinalizationOutcome(
                run_id=run_id,
                disposition=TerminalDeliveryDisposition.INELIGIBLE,
            )
        run = await self.agent_run_repository.lock_by_id(session, run_id)
        if run is None or run.session_id != source.agent_session_id:
            return TerminalFinalizationOutcome(
                run_id=run_id,
                disposition=TerminalDeliveryDisposition.INELIGIBLE,
            )
        if user_stop_requested and run.status is AgentRunStatus.INTERRUPTED:
            stopped = await self.agent_run_repository.mark_stopped_for_user_stop(
                session,
                run_id,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            if stopped is None:
                return TerminalFinalizationOutcome(
                    run_id=run_id,
                    disposition=TerminalDeliveryDisposition.INELIGIBLE,
                )
            run = stopped
        if run.parent_result_delivery_state is not None:
            return TerminalFinalizationOutcome(
                run_id=run_id,
                disposition=TerminalDeliveryDisposition.ALREADY_FINALIZED,
                mailbox_item_id=run.parent_result_mailbox_item_id,
            )
        if run.status not in _TERMINAL_RUN_STATUSES:
            return TerminalFinalizationOutcome(
                run_id=run_id,
                disposition=TerminalDeliveryDisposition.INELIGIBLE,
            )
        if source.kind is not SessionAgentKind.SUBAGENT:
            return await self._suppress(session, run_id=run_id)
        if source.parent_session_agent_id is None:
            return await self._suppress(session, run_id=run_id)
        parent = await self.agent_session_repository.lock_session_agent_by_id(
            session,
            source.parent_session_agent_id,
        )
        if parent is None:
            return await self._suppress(session, run_id=run_id)
        parent_session = await self.agent_session_repository.lock_by_id(
            session,
            parent.agent_session_id,
        )
        if (
            parent_session is None
            or parent_session.status is not AgentSessionStatus.ACTIVE
        ):
            return await self._suppress(session, run_id=run_id)
        mailbox_item = await self.agent_mailbox_service.enqueue_terminal_result(
            session,
            source=source,
            target=parent,
            run=run,
            content=_terminal_result_content(run),
        )
        finalized = await self.agent_run_repository.mark_parent_result_enqueued(
            session,
            run_id=run.id,
            mailbox_item_id=mailbox_item.id,
            enqueued_at=datetime.datetime.now(datetime.UTC),
        )
        if (
            finalized.parent_result_delivery_state
            is not AgentRunParentResultDeliveryState.ENQUEUED
        ):
            raise RuntimeError("Terminal parent result delivery did not finalize")
        return TerminalFinalizationOutcome(
            run_id=run.id,
            disposition=TerminalDeliveryDisposition.ENQUEUED,
            mailbox_item_id=mailbox_item.id,
        )

    async def finalize_runs_in_session(
        self,
        session: AsyncSession,
        run_ids: list[str],
    ) -> list[TerminalFinalizationOutcome]:
        """Finalize multiple terminal Runs in one caller transaction."""
        return [
            await self.finalize_run_in_session(session, run_id=run_id)
            for run_id in run_ids
        ]

    async def _suppress(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> TerminalFinalizationOutcome:
        finalized = await self.agent_run_repository.mark_parent_result_suppressed(
            session,
            run_id=run_id,
            finalized_at=datetime.datetime.now(datetime.UTC),
        )
        return TerminalFinalizationOutcome(
            run_id=run_id,
            disposition=TerminalDeliveryDisposition.SUPPRESSED,
            mailbox_item_id=finalized.parent_result_mailbox_item_id,
        )


_TERMINAL_RUN_STATUSES = {
    AgentRunStatus.COMPLETED,
    AgentRunStatus.FAILED,
    AgentRunStatus.STOPPED,
    AgentRunStatus.INTERRUPTED,
    AgentRunStatus.CANCELLED,
}


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
