"""Broker dependency injection."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.core.redis import create_redis_client
from azents.utils.appctx import AppContext

from .redis import RedisBroker
from .types import SessionBroker


async def get_broker(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> SessionBroker:
    """API-side SessionBroker dependency cached through AppContext.

    The Redis URL comes from config, and the broker is created without worker_id.
    Use worker.deps.get_worker_broker for the worker-only broker.
    """

    async def create_broker() -> AsyncIterator[RedisBroker]:
        redis = create_redis_client(appctx.config.redis.url)
        broker = RedisBroker(redis)
        try:
            yield broker
        finally:
            await redis.aclose()

    return await appctx.get_variable(f"{__name__}.get_broker", create_broker)
