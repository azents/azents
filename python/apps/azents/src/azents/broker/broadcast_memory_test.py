"""Standalone memory broadcast, live fencing, and composition contracts."""

import asyncio
from collections.abc import AsyncIterator
from typing import Literal

import pytest

from azents.api.public.chat.v1 import get_ws_broadcast
from azents.broker.broadcast import (
    InMemoryWebSocketBroadcast,
    WebSocketBroadcast,
    WebSocketBroadcastPublishError,
)
from azents.broker.websocket_deps import get_websocket_broadcast
from azents.core.config import Config, Settings
from azents.services.chat.live_events import (
    InMemoryLiveEventStore,
    get_live_event_store,
)
from azents.utils.appctx import AppContext
from azents.worker.deps import (
    get_broadcast,
)
from azents.worker.deps import (
    get_live_event_store as get_worker_live_event_store,
)


def _config(backend: Literal["redis", "memory"]) -> Config:
    """Supply synthetic settings without connecting to external services."""
    return Config.from_settings(
        Settings(
            _env_file=None,
            rdb_host="unused",
            rdb_user="unused",
            rdb_db_name="unused",
            auth_jwt_secret_key="synthetic-jwt-key",
            credential_encryption_key="synthetic-credential-key",
            broadcast_backend=backend,
        )
    )


async def _next_event(events: AsyncIterator[dict[str, object]]) -> dict[str, object]:
    """Bound a failed delivery hang without using timing as a success oracle."""
    return await asyncio.wait_for(anext(events), 1)


@pytest.mark.asyncio
async def test_memory_fanout_serializes_each_subscriber_and_isolates_sessions() -> None:
    broadcast = InMemoryWebSocketBroadcast(InMemoryLiveEventStore())
    async with (
        broadcast.subscribe("a") as first,
        broadcast.subscribe("a") as second,
        broadcast.subscribe("b") as other,
    ):
        event: dict[str, object] = {"opaque": {"text": "한글"}, "unknown": [1, 2]}
        await broadcast.publish("a", event)
        event["unknown"] = [3]
        first_event = await _next_event(first)
        first_event["opaque"] = None
        assert await _next_event(second) == {
            "opaque": {"text": "한글"},
            "unknown": [1, 2],
        }
        await broadcast.publish("b", {"only": "b"})
        assert await _next_event(other) == {"only": "b"}
        await broadcast.publish("a", {"only": "a"})
        assert await _next_event(first) == {"only": "a"}
        assert await _next_event(second) == {"only": "a"}
    await broadcast.aclose()


@pytest.mark.asyncio
async def test_memory_live_publication_uses_actual_store_generation() -> None:
    store = InMemoryLiveEventStore()
    broadcast = InMemoryWebSocketBroadcast(store)
    event: dict[str, object] = {"type": "opaque_live_update"}
    async with broadcast.subscribe("session") as events:
        assert not await broadcast.publish_live_projection(
            "session", event, owner_generation=1
        )
        assert await store.advance_owner("session", 1)
        assert await broadcast.publish_live_projection(
            "session", event, owner_generation=1
        )
        assert await _next_event(events) == event
        await store.for_owner("session", 1).clear_session("session")
        assert await broadcast.publish_live_projection(
            "session", {"after_owner_clear": True}, owner_generation=1
        )
        assert await _next_event(events) == {"after_owner_clear": True}
        assert await store.advance_owner("session", 2)
        assert not await store.advance_owner("session", 1)
        await store.for_owner("session", 1).clear_session("session")
        assert not await broadcast.publish_live_projection(
            "session", {"stale": True}, owner_generation=1
        )
        assert await broadcast.publish_live_projection(
            "session", {"current": True}, owner_generation=2
        )
        assert await _next_event(events) == {"current": True}
        await store.clear_session("session")
        assert not await broadcast.publish_live_projection(
            "session", event, owner_generation=2
        )
    await broadcast.aclose()


@pytest.mark.asyncio
async def test_memory_cleanup_on_cancellation_and_close() -> None:
    broadcast = InMemoryWebSocketBroadcast(InMemoryLiveEventStore())
    entered = asyncio.Event()

    async def consume() -> None:
        async with broadcast.subscribe("session") as events:
            entered.set()
            await _next_event(events)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not broadcast._subscribers
    async with broadcast.subscribe("session") as events:
        await broadcast.publish("session", {"fresh": True})
        assert await _next_event(events) == {"fresh": True}
        await broadcast.aclose()
        with pytest.raises(StopAsyncIteration):
            await _next_event(events)
    with pytest.raises(WebSocketBroadcastPublishError):
        await broadcast.publish("session", {})
    with pytest.raises(WebSocketBroadcastPublishError):
        async with broadcast.subscribe("session"):
            pytest.fail("Closed broadcast admitted a subscriber")
    assert not broadcast._subscribers


@pytest.mark.asyncio
async def test_memory_serialization_failure_is_not_a_success() -> None:
    broadcast = InMemoryWebSocketBroadcast(InMemoryLiveEventStore())
    with pytest.raises(TypeError):
        await broadcast.publish("session", {"unsupported": object()})
    async with broadcast.subscribe("session") as events:
        await broadcast.publish("session", {"valid": True})
        assert await _next_event(events) == {"valid": True}
    await broadcast.aclose()


@pytest.mark.asyncio
async def test_actual_memory_factories_share_broadcast_and_live_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_redis(url: str) -> None:
        del url
        pytest.fail("Explicit memory composition must not create a Redis client")

    monkeypatch.setattr(
        "azents.broker.websocket_deps.create_redis_client", reject_redis
    )
    monkeypatch.setattr(
        "azents.services.chat.live_events.create_redis_client", reject_redis
    )
    async with AppContext(_config("memory")) as appctx:
        broadcast = await get_websocket_broadcast(appctx)
        assert isinstance(broadcast, InMemoryWebSocketBroadcast)
        assert await get_broadcast(appctx) is broadcast
        assert await get_ws_broadcast(appctx) is broadcast
        store = await get_live_event_store(appctx)
        assert isinstance(store, InMemoryLiveEventStore)
        assert await get_worker_live_event_store(appctx) is store
        assert broadcast.live_store is store
        async with broadcast.subscribe("session") as events:
            assert await store.advance_owner("session", 3)
            assert await broadcast.publish_live_projection(
                "session", {"composed": True}, owner_generation=3
            )
            assert await _next_event(events) == {"composed": True}
    with pytest.raises(WebSocketBroadcastPublishError):
        await broadcast.publish("session", {})


@pytest.mark.asyncio
async def test_separate_memory_contexts_are_not_cross_replica_fanout() -> None:
    async with (
        AppContext(_config("memory")) as first,
        AppContext(_config("memory")) as second,
    ):
        first_broadcast = await get_websocket_broadcast(first)
        second_broadcast = await get_websocket_broadcast(second)
        assert first_broadcast is not second_broadcast
        async with second_broadcast.subscribe("session") as events:
            await first_broadcast.publish("session", {"foreign": True})
            await second_broadcast.publish("session", {"local": True})
            assert await _next_event(events) == {"local": True}


@pytest.mark.asyncio
async def test_default_redis_composition_does_not_transparently_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config("redis")
    assert Settings.model_fields["broadcast_backend"].default == "redis"
    async with AppContext(config) as appctx:
        assert isinstance(await get_websocket_broadcast(appctx), WebSocketBroadcast)

    def failing_redis(url: str) -> None:
        del url
        raise OSError("Synthetic client creation failure")

    monkeypatch.setattr(
        "azents.broker.websocket_deps.create_redis_client", failing_redis
    )
    async with AppContext(config) as appctx:
        with pytest.raises(OSError):
            await get_websocket_broadcast(appctx)
