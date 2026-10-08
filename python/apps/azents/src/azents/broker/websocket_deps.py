"""WebSocket broadcast composition independent of Session broker bootstrap."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends

from azents.broker.broadcast import (
    BaseWebSocketBroadcast,
    InMemoryWebSocketBroadcast,
    WebSocketBroadcast,
)
from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.core.redis import create_redis_client
from azents.services.chat.live_events import (
    InMemoryLiveEventStore,
    get_live_event_store,
)
from azents.utils.appctx import AppContext


async def get_websocket_broadcast(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> BaseWebSocketBroadcast:
    """Compose one deliberately selected broadcast per application context.

    Memory mode shares the local live store with API and Worker consumers in
    this context; it cannot fan out between separate processes or replicas.
    """

    async def create() -> AsyncIterator[BaseWebSocketBroadcast]:
        if (
            appctx.config.session_broker_backend == "memory"
            or appctx.config.broadcast_backend == "memory"
        ):
            store = await get_live_event_store(appctx)
            assert isinstance(store, InMemoryLiveEventStore)
            broadcast = InMemoryWebSocketBroadcast(store)
            try:
                yield broadcast
            finally:
                await broadcast.aclose()
            return
        redis = create_redis_client(appctx.config.redis.url)
        try:
            yield WebSocketBroadcast(redis)
        finally:
            await redis.aclose()

    return await appctx.get_variable(f"{__name__}.get_websocket_broadcast", create)
