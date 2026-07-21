"""Live event store tests."""

import datetime
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from azents.core.enums import (
    AgentRunStatus,
    EventKind,
    InputBufferKind,
    InputBufferSchedulingMode,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.action_messages import ActionMessagePayload, SkillAction
from azents.engine.events.types import (
    ActiveToolCall,
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ProviderToolCallPayload,
    ReasoningPayload,
    ToolkitSourceSnapshot,
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
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
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


def test_agent_result_input_buffer_live_event_restores_terminal_metadata() -> None:
    """Pending terminal result exposes the complete agent message payload."""
    event = input_buffer_to_live_event(
        InputBuffer(
            id="0223456789abcdef0123456789abcdef",
            session_id="1123456789abcdef0123456789abcdef",
            kind=InputBufferKind.AGENT_MESSAGE,
            scheduling_mode=InputBufferSchedulingMode.QUEUE_ONLY,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            actor_user_id=None,
            content="Review completed.",
            idempotency_key="agent_result:" + "2" * 32,
            metadata={
                "source": "agent_mailbox",
                "message_kind": "agent_result",
                "source_session_agent_id": "source-agent",
                "source_path": "/root/reviewer",
                "target_session_agent_id": "target-agent",
                "target_path": "/root",
                "source_run_id": "2" * 32,
                "source_run_index": "4",
                "run_status": "completed",
                "source_terminal_result_event_id": "3" * 32,
            },
            action=None,
            attachments=[],
            file_parts=[],
            created_at=datetime.datetime(2026, 7, 19, tzinfo=datetime.UTC),
        )
    )

    assert isinstance(event.payload, AgentMessagePayload)
    assert event.payload.message_kind == "agent_result"
    assert event.payload.source_run_id == "2" * 32
    assert event.payload.source_run_index == 4
    assert event.payload.run_status is AgentRunStatus.COMPLETED
    assert event.payload.source_terminal_result_event_id == "3" * 32


def test_action_input_buffer_live_event_preserves_requested_profile() -> None:
    """Pending action projection exposes its requested inference profile."""
    event = input_buffer_to_live_event(
        InputBuffer(
            id="0123456789abcdef0123456789abcdef",
            session_id="1123456789abcdef0123456789abcdef",
            kind=InputBufferKind.ACTION_MESSAGE,
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
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
    first_reasoning = await store.append_reasoning_delta(
        session_id,
        delta="first",
        item_id="rs_1",
        output_index=2,
        summary_index=0,
        now=now,
    )
    await store.append_reasoning_delta(
        session_id,
        delta=" summary",
        item_id="rs_1",
        output_index=2,
        summary_index=0,
        now=now,
    )
    await store.append_reasoning_delta(
        session_id,
        delta="second",
        item_id="rs_1",
        output_index=2,
        summary_index=1,
        now=now,
    )
    await store.append_reasoning_delta(
        session_id,
        delta="third",
        item_id="rs_2",
        output_index=3,
        summary_index=0,
        now=now + datetime.timedelta(seconds=1),
    )
    provider_running = await store.upsert_provider_tool_activity(
        session_id,
        call_id="search-1",
        name="web_search",
        status="running",
        arguments=None,
        now=now,
    )
    provider_completed = await store.upsert_provider_tool_activity(
        session_id,
        call_id="search-1",
        name="web_search",
        status="completed",
        arguments='{"query":"azents"}',
        now=now + datetime.timedelta(seconds=1),
    )
    assert provider_completed.id == provider_running.id
    assert provider_completed.created_at == now
    assert isinstance(provider_completed.payload, ProviderToolCallPayload)
    assert provider_completed.payload.status == "completed"
    events = await store.list_by_session_id(session_id)
    assert {event.kind for event in events} == {
        EventKind.ASSISTANT_MESSAGE,
        EventKind.PROVIDER_TOOL_CALL,
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

    reasoning_events = [event for event in events if event.kind == EventKind.REASONING]
    assert len(reasoning_events) == 2
    assert {
        event.payload.text
        for event in reasoning_events
        if isinstance(event.payload, ReasoningPayload)
    } == {"first summary\nsecond", "third"}

    durable_first_reasoning = first_reasoning.model_copy(
        update={"id": "e" * 32, "adapter": "openai"}
    )
    await store.remove_live_counterpart(durable_first_reasoning)
    remaining_reasoning = [
        event
        for event in await store.list_by_session_id(session_id)
        if event.kind == EventKind.REASONING
    ]
    assert len(remaining_reasoning) == 1
    assert isinstance(remaining_reasoning[0].payload, ReasoningPayload)
    assert remaining_reasoning[0].payload.text == "third"

    await store.remove_live_counterpart(assistant)
    assert all(
        event.kind != EventKind.ASSISTANT_MESSAGE
        for event in await store.list_by_session_id(session_id)
    )

    durable_provider_call = provider_completed.model_copy(
        update={"id": "d" * 32, "adapter": "openai"}
    )
    await store.remove_live_counterpart(durable_provider_call)
    assert all(
        event.kind != EventKind.PROVIDER_TOOL_CALL
        for event in await store.list_by_session_id(session_id)
    )


@pytest.mark.asyncio
async def test_reasoning_identity_promotes_from_output_index_to_item_id() -> None:
    """Move an existing output-position projection to its stable item identity."""
    store = InMemoryLiveEventStore()
    now = datetime.datetime(2026, 7, 17, tzinfo=datetime.UTC)

    output_only = await store.append_reasoning_delta(
        "session-1",
        delta="first",
        item_id=None,
        output_index=2,
        summary_index=0,
        now=now,
    )
    promoted = await store.append_reasoning_delta(
        "session-1",
        delta=" continued",
        item_id="rs_1",
        output_index=2,
        summary_index=0,
        now=now + datetime.timedelta(seconds=1),
    )

    events = await store.list_by_session_id("session-1")
    assert len(events) == 1
    assert events[0].id == promoted.id
    assert events[0].id != output_only.id
    assert events[0].created_at == now
    assert isinstance(events[0].payload, ReasoningPayload)
    assert events[0].payload.text == "first continued"


@pytest.mark.asyncio
async def test_durable_reasoning_hands_off_output_index_only_live_items() -> None:
    """Use durable output-position metadata for order-independent handoff."""
    store = InMemoryLiveEventStore()
    now = datetime.datetime(2026, 7, 17, tzinfo=datetime.UTC)
    first = await store.append_reasoning_delta(
        "session-1",
        delta="first",
        item_id=None,
        output_index=2,
        summary_index=0,
        now=now,
    )
    second = await store.append_reasoning_delta(
        "session-1",
        delta="second",
        item_id=None,
        output_index=3,
        summary_index=0,
        now=now + datetime.timedelta(seconds=1),
    )
    assert isinstance(first.payload, ReasoningPayload)
    assert isinstance(second.payload, ReasoningPayload)
    second_artifact = second.payload.native_artifact.model_copy(
        update={
            "item": {
                "type": "reasoning",
                "id": "rs_2",
                "output_index": 3,
            }
        }
    )
    durable_second = second.model_copy(
        update={
            "id": "a" * 32,
            "adapter": "openai",
            "payload": second.payload.model_copy(
                update={"native_artifact": second_artifact}
            ),
        }
    )

    await store.remove_live_counterpart(durable_second)

    remaining = await store.list_by_session_id("session-1")
    assert [event.id for event in remaining] == [first.id]


@pytest.mark.asyncio
async def test_legacy_durable_reasoning_removes_all_live_reasoning_items() -> None:
    """Keep legacy identity-free durable cleanup behavior."""
    store = InMemoryLiveEventStore()
    now = datetime.datetime(2026, 7, 17, tzinfo=datetime.UTC)
    live = await store.append_reasoning_delta(
        "session-1",
        delta="first",
        item_id="rs_1",
        output_index=2,
        summary_index=0,
        now=now,
    )
    await store.append_reasoning_delta(
        "session-1",
        delta="second",
        item_id="rs_2",
        output_index=3,
        summary_index=0,
        now=now + datetime.timedelta(seconds=1),
    )
    assert isinstance(live.payload, ReasoningPayload)
    legacy_artifact = live.payload.native_artifact.model_copy(
        update={"item": {"type": "reasoning"}}
    )
    legacy = live.model_copy(
        update={
            "id": "b" * 32,
            "adapter": "openai",
            "payload": live.payload.model_copy(
                update={"native_artifact": legacy_artifact}
            ),
        }
    )

    await store.remove_live_counterpart(legacy)

    assert await store.list_by_session_id("session-1") == []


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
            toolkit_source=ToolkitSourceSnapshot(
                toolkit_config_id="toolkit-config-1",
                toolkit_type="github",
                toolkit_name="GitHub",
                toolkit_slug="github",
            ),
            started_at=now,
            owner_generation=1,
            wire_dialect="json_function",
        ),
    )

    assert event.kind == EventKind.CLIENT_TOOL_CALL
    assert isinstance(event.payload, ClientToolCallPayload)
    assert event.payload.call_id == "call-1"
    assert event.payload.arguments == '{"cmd":"sleep"}'
    assert event.payload.toolkit_source is not None
    assert event.payload.toolkit_source.toolkit_config_id == "toolkit-config-1"
    assert event.created_at == now
