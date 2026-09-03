"""Runtime Control Transfer State composition tests."""

import inspect
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from redis.asyncio import Redis

from azents.runtime.control_server import RuntimeControlSettings
from azents.runtime.coordination.redis import RedisRuntimeCoordinationStore
from azents.runtime.deps import get_runtime_coordination_store
from azents.runtime.transfer.control import (
    create_runtime_control_transfer_state_store,
    runtime_control_transfer_config,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.runtime.transfer.redis import RedisRuntimeTransferStateStore


def _settings() -> RuntimeControlSettings:
    """Return explicit local Runtime Control settings."""
    return RuntimeControlSettings(
        runtime_control_allow_insecure=True,
        runtime_runner_image="runner:test",
        runtime_runner_control_endpoint="runtime-control:8030",
        runtime_runner_transfer_endpoint="runtime-transfer:8031",
        credential_encryption_key=Fernet.generate_key().decode(),
    )


def _clock() -> datetime:
    """Return deterministic timezone-aware time."""
    return datetime(2026, 7, 25, tzinfo=timezone.utc)


def _redis() -> Redis:
    """Return an unconnected Redis client for composition-only assertions."""
    return Redis.from_url("redis://localhost")


def test_default_runtime_control_transfer_state_is_redis() -> None:
    """Runtime Control defaults to Redis Transfer State composition."""
    redis = _redis()
    store = create_runtime_control_transfer_state_store(
        settings=_settings(),
        redis=redis,
        clock=_clock,
    )

    assert isinstance(store, RedisRuntimeTransferStateStore)
    assert store.redis is redis
    assert store.keys.namespace == "azents:runtime:transfer"


def test_memory_transfer_state_is_explicit_and_process_local() -> None:
    """Explicit memory selection constructs separate process-local stores."""
    settings = _settings().model_copy(
        update={
            "runtime_control_transfer_backend": "memory",
            "runtime_control_transfer_per_runtime_attempts": 2,
            "runtime_control_transfer_per_runtime_bytes": 3,
            "runtime_control_transfer_deployment_attempts": 4,
            "runtime_control_transfer_deployment_bytes": 5,
            "runtime_control_transfer_admission_lease_seconds": 6.0,
            "runtime_control_transfer_consumer_lease_seconds": 7.0,
            "runtime_control_transfer_terminal_ttl_seconds": 8.0,
            "runtime_control_transfer_list_page_size": 9,
        }
    )
    redis = _redis()
    first = create_runtime_control_transfer_state_store(
        settings=settings,
        redis=redis,
        clock=_clock,
    )
    second = create_runtime_control_transfer_state_store(
        settings=settings,
        redis=redis,
        clock=_clock,
    )

    assert isinstance(first, InMemoryRuntimeTransferStateStore)
    assert isinstance(second, InMemoryRuntimeTransferStateStore)
    assert first is not second
    assert first.config == runtime_control_transfer_config(settings)


def test_redis_transfer_namespace_and_config_propagate() -> None:
    """Redis composition preserves explicit namespace and reversible limits."""
    settings = _settings().model_copy(
        update={
            "runtime_control_transfer_redis_namespace": (
                "azents:runtime:transfer:control-test"
            ),
            "runtime_control_transfer_per_runtime_attempts": 3,
            "runtime_control_transfer_per_runtime_bytes": 30,
            "runtime_control_transfer_deployment_attempts": 4,
            "runtime_control_transfer_deployment_bytes": 40,
            "runtime_control_transfer_admission_lease_seconds": 10.0,
            "runtime_control_transfer_consumer_lease_seconds": 20.0,
            "runtime_control_transfer_terminal_ttl_seconds": 30.0,
            "runtime_control_transfer_list_page_size": 5,
        }
    )
    redis = _redis()
    store = create_runtime_control_transfer_state_store(
        settings=settings,
        redis=redis,
        clock=_clock,
    )

    assert isinstance(store, RedisRuntimeTransferStateStore)
    assert store.keys.namespace == "azents:runtime:transfer:control-test"
    assert store.config == runtime_control_transfer_config(settings)


def test_transfer_and_coordination_stores_share_client_without_composition_leak() -> (
    None
):
    """Transfer composition coexists with separately constructed coordination."""
    redis = _redis()
    transfer = create_runtime_control_transfer_state_store(
        settings=_settings(),
        redis=redis,
        clock=_clock,
    )
    coordination = RedisRuntimeCoordinationStore(redis)

    assert isinstance(transfer, RedisRuntimeTransferStateStore)
    assert transfer.redis is redis
    assert isinstance(coordination, RedisRuntimeCoordinationStore)


def test_api_runtime_coordination_dependency_remains_redis_only() -> None:
    """API and Worker runtime dependency composition does not provide Transfer State."""
    source = inspect.getsource(get_runtime_coordination_store)

    assert "RedisRuntimeCoordinationStore(redis)" in source
    assert "TransferStateStore" not in source
