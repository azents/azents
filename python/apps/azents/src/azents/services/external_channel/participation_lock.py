"""Namespaced parent-channel participation coordination."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from azents.core.enums import ExternalChannelConversationScopeKind
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationLock,
    ExternalChannelConversationLockLease,
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationLock,
    ExternalChannelParticipationScope,
)

_PARTICIPATION_NAMESPACE = "participation"


@dataclass(frozen=True)
class NamespacedExternalChannelParticipationLock(ExternalChannelParticipationLock):
    """Reuse the configured lock backend with a distinct key namespace."""

    conversation_lock: ExternalChannelConversationLock

    def acquire(
        self,
        *,
        scope: ExternalChannelParticipationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        """Acquire a parent-channel lock distinct from conversation identity."""
        namespaced_scope = ExternalChannelConversationScope(
            connection_id=scope.connection_id,
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id=(
                f"{_PARTICIPATION_NAMESPACE}:{scope.provider_parent_channel_id}"
            ),
            provider_thread_key=None,
        )
        return self.conversation_lock.acquire(
            scope=namespaced_scope,
            deadline=deadline,
        )
