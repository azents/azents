"""Wait observations preserve durable-active and wake-only descendant semantics."""

from unittest.mock import AsyncMock

from azents.core.enums import AgentSessionRunState
from azents.repos.agent_session.data import AgentSession
from azents.repos.agent_wait_read import AgentWaitReadRepository
from azents.repos.agent_wait_read_data import (
    AgentWaitDescendantSnapshot,
    AgentWaitDescendantState,
)
from azents.services.agent_wait import AgentWaitService, WaitObservation
from azents.services.mailbox import MailboxService


async def test_observe_combines_detached_active_and_wake_only_descendants() -> None:
    repository = AsyncMock(spec=AgentWaitReadRepository)
    repository.descendants.return_value = AgentWaitDescendantSnapshot(
        descendants=(
            AgentWaitDescendantState(
                session_id="active",
                path="/root/active",
                session=AgentSession.model_construct(
                    run_state=AgentSessionRunState.RUNNING
                ),
                run=None,
            ),
            AgentWaitDescendantState(
                session_id="wake", path="/root/wake", session=None, run=None
            ),
            AgentWaitDescendantState(
                session_id="idle", path="/root/idle", session=None, run=None
            ),
        )
    )
    mailbox = AsyncMock(spec=MailboxService)
    mailbox.has_pending_session_mailbox_items.return_value = True
    mailbox.has_pending_wake_session_mailbox_items.side_effect = [True, False]
    service = AgentWaitService(repository=repository, mailbox_item_service=mailbox)

    result = await service.observe("root-session")

    assert result == WaitObservation(True, 3, ("/root/active", "/root/wake"))
    repository.descendants.assert_awaited_once_with("root-session")
    assert [
        call.args[0]
        for call in mailbox.has_pending_wake_session_mailbox_items.await_args_list
    ] == ["wake", "idle"]


async def test_missing_session_keeps_the_initial_mailbox_observation() -> None:
    repository = AsyncMock(spec=AgentWaitReadRepository)
    repository.descendants.return_value = AgentWaitDescendantSnapshot(descendants=())
    mailbox = AsyncMock(spec=MailboxService)
    mailbox.has_pending_session_mailbox_items.return_value = False
    service = AgentWaitService(repository=repository, mailbox_item_service=mailbox)

    assert await service.observe("missing") == WaitObservation(False, 0, ())
    mailbox.has_pending_wake_session_mailbox_items.assert_not_awaited()
