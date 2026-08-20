"""Shared wait condition and mailbox activity service."""

import dataclasses
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.events.types import AgentRunState
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.services.mailbox import MailboxService


class MailboxActivityObserverProtocol(Protocol):
    """Run-scoped activity observer required by the wait service."""

    def current_revision(self) -> int: ...

    async def wait_after(self, revision: int, timeout_seconds: float) -> bool: ...


@dataclasses.dataclass(frozen=True)
class WaitObservation:
    """Durable wait state snapshot."""

    mailbox_updated: bool
    descendant_count: int
    active_paths: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class AgentWaitService:
    """Evaluate descendant eligibility and durable mailbox activity."""

    session_manager: SessionManager[AsyncSession]
    agent_session_repository: AgentSessionRepository
    agent_run_repository: AgentRunRepository
    mailbox_item_service: MailboxService

    async def observe(self, session_id: str) -> WaitObservation:
        """Read all-kind mailbox state and descendant activity."""
        mailbox_updated = (
            await self.mailbox_item_service.has_pending_session_mailbox_items(
                session_id
            )
        )
        async with self.session_manager() as session:
            current = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
            if current is None:
                return WaitObservation(mailbox_updated, 0, ())
            descendants = (
                await self.agent_session_repository.list_descendant_session_agents(
                    session,
                    session_agent_id=current.id,
                    include_self=False,
                )
            )
            session_ids = [agent.agent_session_id for agent in descendants]
            sessions = await self.agent_session_repository.list_by_ids(
                session,
                agent_session_ids=session_ids,
            )
            latest_runs = await self.agent_run_repository.list_latest_by_session_ids(
                session,
                session_ids=session_ids,
            )
        active_paths: list[str] = []
        for descendant in descendants:
            if _session_agent_active(
                sessions.get(descendant.agent_session_id),
                latest_runs.get(descendant.agent_session_id),
            ) or await self.mailbox_item_service.has_pending_wake_session_mailbox_items(
                descendant.agent_session_id
            ):
                active_paths.append(descendant.path)
        return WaitObservation(mailbox_updated, len(descendants), tuple(active_paths))


def _session_agent_active(
    session: AgentSession | None,
    run: AgentRunState | None,
) -> bool:
    """Return whether a descendant has active durable work."""
    return bool(session is not None and session.run_state.value == "running") or bool(
        run is not None and run.status.value in {"pending", "running"}
    )
