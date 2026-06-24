"""Agent Runtime dependency providers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx, get_config
from azents.core.redis import create_redis_client
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.redis import (
    RedisRuntimeCoordinationStore,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.utils.appctx import AppContext


async def get_runtime_coordination_store(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    config: Annotated[Config, Depends(get_config)],
) -> RuntimeCoordinationStore:
    """Return the process-wide Runtime Coordination Store."""

    async def create() -> AsyncIterator[RuntimeCoordinationStore]:
        redis = create_redis_client(config.redis.url)
        try:
            yield RedisRuntimeCoordinationStore(redis)
        finally:
            await redis.aclose()

    return await appctx.get_variable(
        f"{__name__}.get_runtime_coordination_store",
        create,
    )


def get_runtime_control_protocol(
    store: Annotated[RuntimeCoordinationStore, Depends(get_runtime_coordination_store)],
) -> RuntimeControlProtocolService:
    """Return the Runtime control protocol service."""
    return RuntimeControlProtocolService(store)


def get_runtime_runner_operation_client(
    control_protocol: Annotated[
        RuntimeControlProtocolService,
        Depends(get_runtime_control_protocol),
    ],
    store: Annotated[RuntimeCoordinationStore, Depends(get_runtime_coordination_store)],
) -> RuntimeRunnerOperationClient:
    """Return the Runtime Runner operation client."""
    return RuntimeRunnerOperationClient(
        control_protocol=control_protocol,
        coordination_store=store,
    )
