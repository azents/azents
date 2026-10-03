"""Shared wait condition and mailbox activity service."""

import dataclasses
from typing import Annotated, Protocol

from fastapi import Depends

from azents.engine.events.types import AgentRunState
from azents.repos.agent_session.data import AgentSession
from azents.repos.agent_wait_read import AgentWaitReadRepository
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
    """Evaluate detached descendant state and completed mailbox activity reads."""

    repository: Annotated[AgentWaitReadRepository, Depends(AgentWaitReadRepository)]
    mailbox_item_service: Annotated[MailboxService, Depends(MailboxService)]

    async def observe(self, session_id: str) -> WaitObservation:
        """Observe mailbox effects only outside the descendant database snapshot."""
        mailbox_updated = (
            await self.mailbox_item_service.has_pending_session_mailbox_items(
                session_id
            )
        )
        snapshot = await self.repository.descendants(session_id)
        active_paths: list[str] = []
        for descendant in snapshot.descendants:
            if _session_agent_active(
                descendant.session,
                descendant.run,
            ) or await self.mailbox_item_service.has_pending_wake_session_mailbox_items(
                descendant.session_id
            ):
                active_paths.append(descendant.path)
        return WaitObservation(
            mailbox_updated, len(snapshot.descendants), tuple(active_paths)
        )


def _session_agent_active(
    session: AgentSession | None,
    run: AgentRunState | None,
) -> bool:
    """Return whether a descendant has active durable work."""
    return bool(session is not None and session.run_state.value == "running") or bool(
        run is not None and run.status.value in {"pending", "running"}
    )
