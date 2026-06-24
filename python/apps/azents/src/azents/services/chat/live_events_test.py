"""Live event store tests."""

import datetime
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from azents.core.enums import EventKind
from azents.engine.events.types import (
    ActiveToolCall,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    NativeArtifact,
    ReasoningPayload,
)

from .live_events import InMemoryLiveEventStore, LiveEventStore, RedisLiveEventStore


def _native_artifact() -> NativeArtifact:
    """Create native artifact for tests."""
    return NativeArtifact(
        compat_key="test:test:test:test:1",
        adapter="test",
        native_format="test",
        provider="test",
        model="test",
        schema_version="1",
        item={},
    )


@pytest_asyncio.fixture
async def redis(redis_url: str) -> AsyncGenerator[Redis, None]:
    """Redis client for tests."""
    client = Redis.from_url(redis_url)
    await client.flushall()
    try:
        yield client
    finally:
        await client.aclose()


async def _assert_live_store_contract(store: LiveEventStore) -> None:
    session_id = "session-1"
    now = datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC)

    assistant = await store.append_assistant_delta(
        session_id,
        delta="hello",
        content_index=0,
        now=now,
    )
    await store.append_assistant_delta(
        session_id,
        delta=" world",
        content_index=0,
        now=now + datetime.timedelta(seconds=1),
    )
    await store.append_reasoning_delta(session_id, delta="think", now=now)
    await store.append_reasoning_delta(session_id, delta="ing", now=now)
    await store.append_client_tool_call_delta(
        session_id,
        call_id="call-1",
        name="bash",
        arguments_delta='{"cmd"',
        index=0,
        now=now,
    )
    await store.append_client_tool_call_delta(
        session_id,
        call_id="call-1",
        name=None,
        arguments_delta=':"ls"}',
        index=0,
        now=now,
    )

    events = await store.list_by_session_id(session_id)
    assert {event.kind for event in events} == {
        EventKind.ASSISTANT_MESSAGE,
        EventKind.CLIENT_TOOL_CALL,
        EventKind.REASONING,
    }

    assistant_payload = next(
        event.payload for event in events if event.kind == EventKind.ASSISTANT_MESSAGE
    )
    assert isinstance(assistant_payload, AssistantMessagePayload)
    assert assistant_payload.content == "hello world"

    reasoning_payload = next(
        event.payload for event in events if event.kind == EventKind.REASONING
    )
    assert isinstance(reasoning_payload, ReasoningPayload)
    assert reasoning_payload.text == "thinking"

    tool_payload = next(
        event.payload for event in events if event.kind == EventKind.CLIENT_TOOL_CALL
    )
    assert isinstance(tool_payload, ClientToolCallPayload)
    assert tool_payload.name == "bash"
    assert tool_payload.arguments == '{"cmd":"ls"}'

    await store.remove_live_counterpart(assistant)
    assert all(
        event.kind != EventKind.ASSISTANT_MESSAGE
        for event in await store.list_by_session_id(session_id)
    )


@pytest.mark.asyncio
async def test_in_memory_live_event_store_contract() -> None:
    """In-memory live event store contract."""
    await _assert_live_store_contract(InMemoryLiveEventStore())


@pytest.mark.asyncio
async def test_redis_live_event_store_contract(redis: Redis) -> None:
    """Redis live event store contract."""
    await _assert_live_store_contract(RedisLiveEventStore(redis))


@pytest.mark.asyncio
async def test_replace_active_tool_calls_removes_stale_tool_projection() -> None:
    """Active tool call projection is replaced as a set."""
    store = InMemoryLiveEventStore()
    now = datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC)

    await store.replace_active_tool_calls(
        "session-1",
        [
            ActiveToolCall(
                call_id="call-1",
                name="bash",
                arguments='{"cmd":"sleep"}',
                started_at=now,
            )
        ],
    )
    await store.replace_active_tool_calls("session-1", [])

    assert await store.list_by_session_id("session-1") == []


@pytest.mark.asyncio
async def test_tool_call_live_projection_stays_until_result() -> None:
    """Durable tool call alone does not remove running live projection."""
    store = InMemoryLiveEventStore()
    now = datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC)
    await store.replace_active_tool_calls(
        "session-1",
        [
            ActiveToolCall(
                call_id="call-1",
                name="bash",
                arguments='{"cmd":"sleep"}',
                started_at=now,
            )
        ],
    )

    await store.remove_live_counterpart(
        Event(
            id="1".rjust(32, "0"),
            session_id="session-1",
            kind=EventKind.CLIENT_TOOL_CALL,
            payload=ClientToolCallPayload(
                call_id="call-1",
                name="bash",
                arguments='{"cmd":"sleep"}',
                native_artifact=_native_artifact(),
            ),
            created_at=now,
        )
    )
    assert len(await store.list_by_session_id("session-1")) == 1

    await store.remove_live_counterpart(
        Event(
            id="2".rjust(32, "0"),
            session_id="session-1",
            kind=EventKind.CLIENT_TOOL_RESULT,
            payload=ClientToolResultPayload(
                call_id="call-1",
                name="bash",
                status="completed",
                output="done",
                attachments=[],
            ),
            created_at=now,
        )
    )
    assert await store.list_by_session_id("session-1") == []
