"""Tests for External Channel mailbox wake dispatch."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.repos.mailbox.data import MailboxItem
from azents.services.external_channel.conversation import (
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.mailbox_wake import (
    ExternalChannelMailboxWakeDispatcher,
)
from azents.services.mailbox import MailboxService


class _Session:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def commit(self) -> None:
        self.calls.append("commit")


class _MailboxService:
    def __init__(self, calls: list[str], item: MailboxItem | None) -> None:
        self.calls = calls
        self.item = item

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        buffer_id: str,
    ) -> MailboxItem | None:
        del session, buffer_id
        self.calls.append("load_mailbox")
        return self.item


class _Broker:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.messages: list[SessionWakeUp] = []

    async def send_message(self, message: SessionWakeUp) -> None:
        self.calls.append("send_wake")
        self.messages.append(message)


def _mailbox_item() -> MailboxItem:
    return MailboxItem.model_construct(
        id="mailbox-1",
        session_id="session-1",
    )


async def test_dispatch_sends_routing_only_wake_after_mailbox_commit() -> None:
    """Accepted input remains durable before its routing-only wake is sent."""
    calls: list[str] = []
    session = _Session(calls)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    broker = _Broker(calls)
    dispatcher = ExternalChannelMailboxWakeDispatcher(
        session_manager=session_manager,
        mailbox_service=cast(
            MailboxService,
            _MailboxService(calls, _mailbox_item()),
        ),
        broker=cast(SessionBroker, broker),
    )

    result = await dispatcher.dispatch(
        mailbox_item_id="mailbox-1",
        session_id="session-1",
        now=datetime.datetime.now(datetime.UTC),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert result == "dispatched"
    assert calls == ["load_mailbox", "commit", "send_wake"]
    assert broker.messages == [SessionWakeUp(session_id="session-1")]


async def test_missing_mailbox_item_does_not_send_duplicate_wake() -> None:
    """A promoted item makes wake recovery an idempotent no-op."""
    calls: list[str] = []
    session = _Session(calls)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    broker = _Broker(calls)
    dispatcher = ExternalChannelMailboxWakeDispatcher(
        session_manager=session_manager,
        mailbox_service=cast(MailboxService, _MailboxService(calls, None)),
        broker=cast(SessionBroker, broker),
    )

    result = await dispatcher.dispatch(
        mailbox_item_id="mailbox-1",
        session_id="session-1",
        now=datetime.datetime.now(datetime.UTC),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert result == "already_dispatched"
    assert calls == ["load_mailbox", "commit"]
    assert broker.messages == []
