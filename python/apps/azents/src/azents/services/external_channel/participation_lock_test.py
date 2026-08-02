"""Participation lock namespace tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import cast

from azents.core.enums import ExternalChannelConversationScopeKind
from azents.services.external_channel.conversation import (
    ExternalChannelConversationLockLease,
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationScope,
)
from azents.services.external_channel.participation_lock import (
    NamespacedExternalChannelParticipationLock,
)


@dataclass
class _ConversationLock:
    scope: ExternalChannelConversationScope | None = None

    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        del deadline
        self.scope = scope

        @asynccontextmanager
        async def owned() -> AsyncIterator[ExternalChannelConversationLockLease]:
            yield cast(ExternalChannelConversationLockLease, object())

        return owned()


async def test_participation_lock_uses_distinct_parent_namespace() -> None:
    """Participation coordination cannot collide with conversation identities."""
    backend = _ConversationLock()
    lock = NamespacedExternalChannelParticipationLock(backend)

    async with lock.acquire(
        scope=ExternalChannelParticipationScope(
            connection_id="connection-1",
            provider_parent_channel_id="parent-channel-1",
        ),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
            + datetime.timedelta(seconds=30)
        ),
    ):
        pass

    assert backend.scope == ExternalChannelConversationScope(
        connection_id="connection-1",
        kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
        provider_channel_id="participation:parent-channel-1",
        provider_thread_key=None,
    )
