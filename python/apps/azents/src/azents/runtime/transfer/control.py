"""Runtime Control-owned Transfer State settings composition."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal, Protocol, assert_never

from redis.asyncio import Redis

from azents.runtime.transfer.data import RuntimeTransferConfig
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.runtime.transfer.redis import RedisRuntimeTransferStateStore
from azents.runtime.transfer.store import RuntimeTransferStateStore

type RuntimeControlTransferBackend = Literal["memory", "redis"]


class RuntimeControlTransferSettings(Protocol):
    """Reversible Runtime Control settings that select Transfer State."""

    runtime_control_transfer_backend: RuntimeControlTransferBackend
    runtime_control_transfer_redis_namespace: str
    runtime_control_transfer_per_runtime_attempts: int
    runtime_control_transfer_per_runtime_bytes: int
    runtime_control_transfer_deployment_attempts: int
    runtime_control_transfer_deployment_bytes: int
    runtime_control_transfer_admission_lease_seconds: float
    runtime_control_transfer_consumer_lease_seconds: float
    runtime_control_transfer_stream_lease_seconds: float
    runtime_control_transfer_terminal_ttl_seconds: float
    runtime_control_transfer_list_page_size: int


def runtime_control_transfer_config(
    settings: RuntimeControlTransferSettings,
) -> RuntimeTransferConfig:
    """Build explicit Transfer State limits from Runtime Control settings."""
    return RuntimeTransferConfig(
        per_runtime_attempts=settings.runtime_control_transfer_per_runtime_attempts,
        per_runtime_bytes=settings.runtime_control_transfer_per_runtime_bytes,
        deployment_attempts=settings.runtime_control_transfer_deployment_attempts,
        deployment_bytes=settings.runtime_control_transfer_deployment_bytes,
        admission_lease=timedelta(
            seconds=settings.runtime_control_transfer_admission_lease_seconds
        ),
        consumer_lease=timedelta(
            seconds=settings.runtime_control_transfer_consumer_lease_seconds
        ),
        stream_lease=timedelta(
            seconds=settings.runtime_control_transfer_stream_lease_seconds
        ),
        terminal_ttl=timedelta(
            seconds=settings.runtime_control_transfer_terminal_ttl_seconds
        ),
        list_page_size=settings.runtime_control_transfer_list_page_size,
    )


def create_runtime_control_transfer_state_store(
    *,
    settings: RuntimeControlTransferSettings,
    redis: Redis,
    clock: Callable[[], datetime],
) -> RuntimeTransferStateStore:
    """Create the Runtime Control-owned Transfer State backend."""
    config = runtime_control_transfer_config(settings)
    backend = settings.runtime_control_transfer_backend
    if backend == "memory":
        return InMemoryRuntimeTransferStateStore(config=config, clock=clock)
    if backend == "redis":
        return RedisRuntimeTransferStateStore(
            redis=redis,
            config=config,
            clock=clock,
            namespace=settings.runtime_control_transfer_redis_namespace,
        )
    assert_never(backend)
