"""External Channel service dependency providers."""

from collections.abc import AsyncIterator
from typing import Annotated, assert_never

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx, get_config
from azents.core.enums import ExternalChannelConversationLockBackend
from azents.core.redis import create_redis_client
from azents.services.external_channel.conversation import (
    ExternalChannelConversationLock,
)
from azents.services.external_channel.conversation_lock import (
    InMemoryExternalChannelConversationLock,
    RedisExternalChannelConversationLock,
)
from azents.utils.appctx import AppContext


async def get_external_channel_conversation_lock(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    config: Annotated[Config, Depends(get_config)],
) -> ExternalChannelConversationLock:
    """Return the explicitly configured process-owned conversation lock."""
    lock_config = config.external_channel_conversation.lock

    async def create() -> AsyncIterator[ExternalChannelConversationLock]:
        match lock_config.backend:
            case ExternalChannelConversationLockBackend.MEMORY:
                yield InMemoryExternalChannelConversationLock()
            case ExternalChannelConversationLockBackend.REDIS:
                redis = create_redis_client(config.redis.url)
                try:
                    yield RedisExternalChannelConversationLock(
                        redis,
                        lease_ttl_seconds=lock_config.lease_ttl_seconds,
                        renewal_interval_seconds=lock_config.renewal_interval_seconds,
                    )
                finally:
                    await redis.aclose()
            case _ as unreachable:
                assert_never(unreachable)

    return await appctx.get_variable(
        f"{__name__}.get_external_channel_conversation_lock",
        create,
    )
