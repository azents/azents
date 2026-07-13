"""Live event store tests."""

import datetime
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from azents.core.enums import EventKind, InputBufferKind
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.action_messages import ActionMessagePayload, SkillAction
from azents.engine.events.types import (
    ActiveToolCall,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ReasoningPayload,
    UserMessagePayload,
)
from azents.repos.input_buffer.data import InputBuffer

from .live_events import (
    InMemoryLiveEventStore,
    LiveEventStore,
    RedisLiveEventStore,
    active_tool_call_to_live_event,
    input_buffer_to_live_event,
)


def test_user_input_buffer_live_event_preserves_nullable_requested_profile() -> None:
    """Pending User input exposes explicit nullable reasoning intent."""
    event = input_buffer_to_live_event(
        InputBuffer(
            id="0023456789abcdef0123456789abcdef",
            session_id="1123456789abcdef0123456789abcdef",
            kind=InputBufferKind.USER_MESSAGE,
            requested_model_target_label="quality",
            requested_reasoning_effort=None,
            actor_user_id="user-1",
            content="Use the quality model",
            idempotency_key=None,
            metadata={"source": "chat"},
            action=None,
            attachments=[],
            file_parts=[],
            created_at=datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC),
        )
    )

    assert isinstance(event.payload, UserMessagePayload)
    assert event.payload.requested_inference_profile is not None
    assert event.payload.requested_inference_profile.model_target_label == "quality"
    assert event.payload.requested_inference_profile.reasoning_effort is None


def test_action_input_buffer_live_event_preserves_requested_profile() -> None:
    """Pending action projection exposes its requested inference profile."""
    event = input_buffer_to_live_event(
        InputBuffer(
            id="0123456789abcdef0123456789abcdef",
            session_id="1123456789abcdef0123456789abcdef",
            kind=InputBufferKind.ACTION_MESSAGE,
            requested_model_target_label="reasoning",
            requested_reasoning_effort=ModelReasoningEffort.HIGH,
            actor_user_id="user-1",
            content="Review this PR",
            idempotency_key=None,
            metadata={"source": "chat"},
            action=SkillAction(skill_path="/skills/review/SKILL.md").model_dump(
                mode="json"
            ),
            attachments=[],
            file_parts=[],
            created_at=datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC),
        )
    )

    assert isinstance(event.payload, ActionMessagePayload)
    assert event.payload.requested_inference_profile is not None
    assert event.payload.requested_inference_profile.model_target_label == "reasoning"
    assert event.payload.requested_inference_profile.reasoning_effort == (
        ModelReasoningEffort.HIGH
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
    await store.append_assistant_delta(
        session_id,
        delta="secondary",
        content_index=1,
        now=now + datetime.timedelta(seconds=1),
    )
    await store.append_reasoning_delta(session_id, delta="think", now=now)
    await store.append_reasoning_delta(session_id, delta="ing", now=now)
    events = await store.list_by_session_id(session_id)
    assert {event.kind for event in events} == {
        EventKind.ASSISTANT_MESSAGE,
        EventKind.REASONING,
    }

    assistant_payloads = [
        event.payload
        for event in events
        if isinstance(event.payload, AssistantMessagePayload)
    ]
    assistant_contents = [payload.content for payload in assistant_payloads]
    assert len(assistant_contents) == 2
    assert "hello world" in assistant_contents
    assert "secondary" in assistant_contents

    reasoning_payload = next(
        event.payload for event in events if event.kind == EventKind.REASONING
    )
    assert isinstance(reasoning_payload, ReasoningPayload)
    assert reasoning_payload.text == "thinking"

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


def test_active_tool_call_projection_has_stable_live_shape() -> None:
    """PostgreSQL active calls use the same stable event shape as tool deltas."""
    now = datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC)
    event = active_tool_call_to_live_event(
        "session-1",
        ActiveToolCall(
            call_id="call-1",
            name="bash",
            arguments='{"cmd":"sleep"}',
            started_at=now,
            owner_generation=1,
        ),
    )

    assert event.kind == EventKind.CLIENT_TOOL_CALL
    assert isinstance(event.payload, ClientToolCallPayload)
    assert event.payload.call_id == "call-1"
    assert event.payload.arguments == '{"cmd":"sleep"}'
    assert event.created_at == now
