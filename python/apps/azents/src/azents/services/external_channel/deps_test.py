"""External Channel dependency composition tests."""

import pytest

from azents.core.config import (
    Config,
    ExternalChannelConversationConfig,
    ExternalChannelConversationLockConfig,
    ExternalChannelIngressQuiesceConfig,
    RedisConfig,
)
from azents.core.enums import ExternalChannelConversationLockBackend
from azents.services.external_channel import deps
from azents.services.external_channel.conversation_lock import (
    InMemoryExternalChannelConversationLock,
    RedisExternalChannelConversationLock,
)
from azents.utils.appctx import AppContext


class _Redis:
    """Minimal process-owned Redis client double."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        """Record client closure."""
        self.closed = True


def _config(backend: ExternalChannelConversationLockBackend) -> Config:
    """Return the minimum constructed Config required by the provider."""
    return Config.model_construct(
        redis=RedisConfig(url="redis://test"),
        external_channel_conversation=ExternalChannelConversationConfig(
            lock=ExternalChannelConversationLockConfig(
                backend=backend,
                lease_ttl_seconds=30.0,
                renewal_interval_seconds=10.0,
            ),
            quiesce=ExternalChannelIngressQuiesceConfig(
                slack_http=False,
                slack_socket=False,
                discord_gateway=False,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_memory_lock_selection_does_not_create_a_redis_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memory selection is explicit and independent from the Session broker."""
    config = _config(ExternalChannelConversationLockBackend.MEMORY)
    appctx = AppContext(config)
    monkeypatch.setattr(
        deps,
        "create_redis_client",
        lambda _url: pytest.fail("Memory lock must not create Redis."),
    )

    async with appctx:
        first = await deps.get_external_channel_conversation_lock(appctx, config)
        second = await deps.get_external_channel_conversation_lock(appctx, config)

    assert isinstance(first, InMemoryExternalChannelConversationLock)
    assert second is first


@pytest.mark.asyncio
async def test_redis_lock_selection_reuses_and_closes_its_own_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis selection owns one client without changing broker composition."""
    config = _config(ExternalChannelConversationLockBackend.REDIS)
    appctx = AppContext(config)
    redis = _Redis()
    monkeypatch.setattr(
        deps,
        "create_redis_client",
        lambda _url: redis,
    )

    async with appctx:
        first = await deps.get_external_channel_conversation_lock(appctx, config)
        second = await deps.get_external_channel_conversation_lock(appctx, config)
        assert redis.closed is False

    assert isinstance(first, RedisExternalChannelConversationLock)
    assert second is first
    assert redis.closed is True
