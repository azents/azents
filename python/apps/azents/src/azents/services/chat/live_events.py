"""Event chat live event projection store."""

import datetime
import hashlib
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any, Protocol, cast

from fastapi import Depends
from pydantic import TypeAdapter

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.core.enums import EventKind, InputBufferKind
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
)
from azents.core.redis import create_redis_client
from azents.engine.events.action_messages import ActionMessagePayload, ChatAction
from azents.engine.events.types import (
    ActiveToolCall,
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    InputTextPart,
    NativeArtifact,
    OutputTextPart,
    ReasoningPayload,
    UserContentPart,
    UserMessagePayload,
)
from azents.repos.input_buffer.data import InputBuffer
from azents.utils.appctx import AppContext

_LIVE_EVENT_TTL_SECONDS = 300
_live_event_adapter = TypeAdapter(Event)
_chat_action_adapter = TypeAdapter(ChatAction)
_agent_message_adapter = TypeAdapter(AgentMessagePayload)


def _live_event_key(session_id: str) -> str:
    return f"azents:chat:{session_id}:live_events"


def _stable_live_id(session_id: str, *parts: object) -> str:
    raw = ":".join([session_id, *(str(part) for part in parts)])
    return hashlib.md5(raw.encode("utf-8"), usedforsecurity=False).hexdigest()


def _live_native_artifact(
    *,
    projection: str,
    source: str,
    item: dict[str, object],
) -> NativeArtifact:
    return NativeArtifact(
        compat_key="azents-live:live_projection:azents:live:1",
        adapter="azents-live",
        native_format="live_projection",
        provider="azents",
        model="live",
        schema_version="1",
        item={
            "live_projection": projection,
            "source": source,
            **item,
        },
    )


def _text_content(value: str | Sequence[object]) -> str:
    if isinstance(value, str):
        return value
    texts: list[str] = []
    for part in value:
        if isinstance(part, OutputTextPart):
            texts.append(part.text)
    return "".join(texts)


def _assistant_live_event(
    *,
    session_id: str,
    event_id: str,
    content: str,
    content_index: int,
    created_at: datetime.datetime,
) -> Event:
    return Event(
        id=event_id,
        session_id=session_id,
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=AssistantMessagePayload(
            content=content,
            attachments=[],
            native_artifact=_live_native_artifact(
                projection="assistant_message",
                source="content_delta",
                item={"content_index": content_index},
            ),
        ),
        model_order=0,
        external_id=event_id,
        adapter="azents-live",
        provider="azents",
        model="live",
        native_format="live_projection",
        schema_version="1",
        created_at=created_at,
    )


def _reasoning_live_event(
    *,
    session_id: str,
    event_id: str,
    text: str,
    created_at: datetime.datetime,
) -> Event:
    return Event(
        id=event_id,
        session_id=session_id,
        kind=EventKind.REASONING,
        payload=ReasoningPayload(
            text=text,
            summary=None,
            native_artifact=_live_native_artifact(
                projection="reasoning",
                source="reasoning_delta",
                item={},
            ),
        ),
        model_order=0,
        external_id=event_id,
        adapter="azents-live",
        provider="azents",
        model="live",
        native_format="live_projection",
        schema_version="1",
        created_at=created_at,
    )


def _tool_call_live_event(
    *,
    session_id: str,
    event_id: str,
    call_id: str,
    name: str,
    arguments: str,
    source: str,
    background: bool,
    created_at: datetime.datetime,
) -> Event:
    return Event(
        id=event_id,
        session_id=session_id,
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id=call_id,
            name=name,
            arguments=arguments,
            native_artifact=_live_native_artifact(
                projection="client_tool_call",
                source=source,
                item={"background": background},
            ),
        ),
        model_order=0,
        external_id=call_id,
        adapter="azents-live",
        provider="azents",
        model="live",
        native_format="live_projection",
        schema_version="1",
        created_at=created_at,
    )


def _is_live_projection(event: Event, projection: str) -> bool:
    payload = event.payload
    artifact = getattr(payload, "native_artifact", None)
    if artifact is None:
        return False
    return (
        artifact.adapter == "azents-live"
        and artifact.item.get("live_projection") == projection
    )


def _input_buffer_requested_profile(
    input_buffer: InputBuffer,
) -> RequestedInferenceProfile | None:
    """Build the requested profile exposed by a pending input buffer."""
    if input_buffer.requested_model_target_label is None:
        return None
    return RequestedInferenceProfile(
        model_target_label=input_buffer.requested_model_target_label,
        reasoning_effort=input_buffer.requested_reasoning_effort,
    )


def input_buffer_to_live_event(input_buffer: InputBuffer) -> Event:
    """Convert InputBuffer to non-durable live event projection."""
    if input_buffer.kind == InputBufferKind.ACTION_MESSAGE:
        if input_buffer.action is None:
            raise ValueError("Action message input buffer requires action payload")
        payload = ActionMessagePayload(
            action=_chat_action_adapter.validate_python(input_buffer.action),
            message=input_buffer.content,
            requested_inference_profile=_input_buffer_requested_profile(input_buffer),
        )
    elif input_buffer.kind == InputBufferKind.AGENT_MESSAGE:
        payload = _agent_message_adapter.validate_python(
            {
                "message_kind": input_buffer.metadata["message_kind"],
                "source_session_agent_id": input_buffer.metadata[
                    "source_session_agent_id"
                ],
                "source_path": input_buffer.metadata["source_path"],
                "target_session_agent_id": input_buffer.metadata[
                    "target_session_agent_id"
                ],
                "target_path": input_buffer.metadata["target_path"],
                "content": input_buffer.content,
            }
        )
    else:
        content: str | list[UserContentPart]
        if input_buffer.file_parts:
            content = [
                InputTextPart(text=input_buffer.content),
                *input_buffer.file_parts,
            ]
        else:
            content = input_buffer.content
        metadata = dict(input_buffer.metadata)
        metadata["input_buffer_id"] = input_buffer.id
        metadata["live_projection"] = "input_buffer"
        requested_profile = _input_buffer_requested_profile(input_buffer)
        payload = UserMessagePayload(
            content=content,
            attachments=[],
            metadata=metadata,
            applied_inference_profile=(
                AppliedInferenceProfile(
                    model_target_label=requested_profile.model_target_label,
                    reasoning_effort=requested_profile.reasoning_effort,
                )
                if requested_profile is not None
                else None
            ),
        )
    return Event(
        id=input_buffer.id,
        session_id=input_buffer.session_id,
        kind=_event_kind_for_input_buffer(input_buffer.kind),
        payload=payload,
        model_order=0,
        external_id=input_buffer.id,
        adapter=None,
        provider=None,
        model=None,
        native_format=None,
        schema_version="1",
        created_at=input_buffer.created_at,
    )


def _event_kind_for_input_buffer(kind: InputBufferKind) -> EventKind:
    """Return live event kind corresponding to InputBuffer kind."""
    match kind:
        case InputBufferKind.USER_MESSAGE:
            return EventKind.USER_MESSAGE
        case InputBufferKind.GOAL_CONTINUATION:
            return EventKind.GOAL_CONTINUATION
        case InputBufferKind.ACTION_MESSAGE:
            return EventKind.ACTION_MESSAGE
        case InputBufferKind.AGENT_MESSAGE:
            return EventKind.AGENT_MESSAGE


class LiveEventStore(Protocol):
    """Non-durable event live event projection store contract."""

    async def list_by_session_id(self, session_id: str) -> list[Event]:
        """Fetch event live event projection list of session."""
        ...

    async def upsert(self, event: Event) -> None:
        """Upsert Event live event projection."""
        ...

    async def remove(self, session_id: str, event_id: str) -> None:
        """Remove one Event live event projection."""
        ...

    async def clear_session(self, session_id: str) -> None:
        """Remove all event live event projections of session."""
        ...

    async def append_assistant_delta(
        self,
        session_id: str,
        *,
        delta: str,
        content_index: int,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Merge streaming assistant delta into live assistant_message projection."""
        ...

    async def append_reasoning_delta(
        self,
        session_id: str,
        *,
        delta: str,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Merge streaming reasoning delta into live reasoning projection."""
        ...

    async def append_client_tool_call_delta(
        self,
        session_id: str,
        *,
        call_id: str | None,
        name: str | None,
        arguments_delta: str,
        index: int,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Merge streaming function-call delta into live tool projection."""
        ...

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: list[ActiveToolCall],
    ) -> None:
        """Replace current active tool call list with live tool projection."""
        ...

    async def remove_live_counterpart(self, event: Event) -> None:
        """Remove corresponding live projection after durable event append."""
        ...


class BaseLiveEventStore:
    """Storage-independent event live event projection operations."""

    async def list_by_session_id(self, session_id: str) -> list[Event]:
        """Fetch event live event projection list of session."""
        raise NotImplementedError

    async def upsert(self, event: Event) -> None:
        """Upsert Event live event projection."""
        raise NotImplementedError

    async def remove(self, session_id: str, event_id: str) -> None:
        """Remove one Event live event projection."""
        raise NotImplementedError

    async def clear_session(self, session_id: str) -> None:
        """Remove all event live event projections of session."""
        raise NotImplementedError

    async def _get(self, session_id: str, event_id: str) -> Event | None:
        raise NotImplementedError

    async def append_assistant_delta(
        self,
        session_id: str,
        *,
        delta: str,
        content_index: int,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Merge streaming assistant delta into live assistant_message projection."""
        event_id = _stable_live_id(session_id, "assistant", content_index)
        current = await self._get(session_id, event_id)
        current_text = (
            _text_content(current.payload.content)
            if current is not None
            and isinstance(current.payload, AssistantMessagePayload)
            else ""
        )
        event = _assistant_live_event(
            session_id=session_id,
            event_id=event_id,
            content=f"{current_text}{delta}",
            content_index=content_index,
            created_at=current.created_at
            if current is not None
            else (now or datetime.datetime.now(datetime.UTC)),
        )
        await self.upsert(event)
        return event

    async def append_reasoning_delta(
        self,
        session_id: str,
        *,
        delta: str,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Merge streaming reasoning delta into live reasoning projection."""
        event_id = _stable_live_id(session_id, "reasoning")
        current = await self._get(session_id, event_id)
        current_text = (
            current.payload.text
            if current is not None and isinstance(current.payload, ReasoningPayload)
            else ""
        )
        event = _reasoning_live_event(
            session_id=session_id,
            event_id=event_id,
            text=f"{current_text or ''}{delta}",
            created_at=current.created_at
            if current is not None
            else (now or datetime.datetime.now(datetime.UTC)),
        )
        await self.upsert(event)
        return event

    async def append_client_tool_call_delta(
        self,
        session_id: str,
        *,
        call_id: str | None,
        name: str | None,
        arguments_delta: str,
        index: int,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Merge streaming function-call delta into live tool projection."""
        stable_call_id = call_id or _stable_live_id(session_id, "tool", index)
        event_id = _stable_live_id(session_id, "tool", stable_call_id)
        current = await self._get(session_id, event_id)
        current_args = (
            current.payload.arguments
            if current is not None
            and isinstance(current.payload, ClientToolCallPayload)
            else ""
        )
        current_name = (
            current.payload.name
            if current is not None
            and isinstance(current.payload, ClientToolCallPayload)
            else None
        )
        event = _tool_call_live_event(
            session_id=session_id,
            event_id=event_id,
            call_id=stable_call_id,
            name=name or current_name or "tool",
            arguments=f"{current_args}{arguments_delta}",
            source="function_call_delta",
            background=False,
            created_at=current.created_at
            if current is not None
            else (now or datetime.datetime.now(datetime.UTC)),
        )
        await self.upsert(event)
        return event

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: list[ActiveToolCall],
    ) -> None:
        """Replace current active tool call list with live tool projection."""
        existing = await self.list_by_session_id(session_id)
        active_ids = {
            _stable_live_id(session_id, "tool", active_tool_call.call_id)
            for active_tool_call in active_tool_calls
        }
        for event in existing:
            if (
                event.kind == EventKind.CLIENT_TOOL_CALL
                and _is_live_projection(event, "client_tool_call")
                and event.id not in active_ids
            ):
                await self.remove(session_id, event.id)
        for active_tool_call in active_tool_calls:
            event_id = _stable_live_id(session_id, "tool", active_tool_call.call_id)
            await self.upsert(
                _tool_call_live_event(
                    session_id=session_id,
                    event_id=event_id,
                    call_id=active_tool_call.call_id,
                    name=active_tool_call.name,
                    arguments=active_tool_call.arguments or "",
                    source="active_tool_call",
                    background=active_tool_call.background,
                    created_at=active_tool_call.started_at,
                )
            )

    async def remove_live_counterpart(self, event: Event) -> None:
        """Remove corresponding live projection after durable event append."""
        if event.kind == EventKind.ASSISTANT_MESSAGE:
            await self.remove(
                event.session_id,
                _stable_live_id(event.session_id, "assistant", 0),
            )
        elif event.kind == EventKind.REASONING:
            await self.remove(
                event.session_id,
                _stable_live_id(event.session_id, "reasoning"),
            )
        elif event.kind == EventKind.CLIENT_TOOL_RESULT:
            payload = event.payload
            if isinstance(payload, ClientToolResultPayload):
                await self.remove(
                    event.session_id,
                    _stable_live_id(event.session_id, "tool", payload.call_id),
                )


class RedisLiveEventStore(BaseLiveEventStore):
    """Redis-backed non-durable event live event projection store."""

    def __init__(
        self,
        redis: object,
        *,
        ttl_seconds: int = _LIVE_EVENT_TTL_SECONDS,
    ) -> None:
        self._redis = cast(Any, redis)
        self._ttl_seconds = ttl_seconds

    async def list_by_session_id(self, session_id: str) -> list[Event]:
        """Fetch event live event projection list of session."""
        values = await self._redis.hvals(_live_event_key(session_id))
        events = [_live_event_adapter.validate_json(value) for value in values]
        return sorted(events, key=lambda event: (event.created_at, event.id))

    async def upsert(self, event: Event) -> None:
        """Upsert Event live event projection."""
        key = _live_event_key(event.session_id)
        await self._redis.hset(key, event.id, _live_event_adapter.dump_json(event))
        await self._redis.expire(key, self._ttl_seconds)

    async def remove(self, session_id: str, event_id: str) -> None:
        """Remove one Event live event projection."""
        await self._redis.hdel(_live_event_key(session_id), event_id)

    async def clear_session(self, session_id: str) -> None:
        """Remove all event live event projections of session."""
        await self._redis.delete(_live_event_key(session_id))

    async def _get(self, session_id: str, event_id: str) -> Event | None:
        raw = await self._redis.hget(_live_event_key(session_id), event_id)
        if raw is None:
            return None
        return _live_event_adapter.validate_json(raw)


class InMemoryLiveEventStore(BaseLiveEventStore):
    """In-memory event live event projection store for tests/local adapters."""

    def __init__(self) -> None:
        self._events: dict[str, dict[str, Event]] = {}

    async def list_by_session_id(self, session_id: str) -> list[Event]:
        """Fetch event live event projection list of session."""
        return sorted(
            self._events.get(session_id, {}).values(),
            key=lambda event: (event.created_at, event.id),
        )

    async def upsert(self, event: Event) -> None:
        """Upsert Event live event projection."""
        self._events.setdefault(event.session_id, {})[event.id] = event

    async def remove(self, session_id: str, event_id: str) -> None:
        """Remove one Event live event projection."""
        self._events.get(session_id, {}).pop(event_id, None)

    async def clear_session(self, session_id: str) -> None:
        """Remove all event live event projections of session."""
        self._events.pop(session_id, None)

    async def _get(self, session_id: str, event_id: str) -> Event | None:
        return self._events.get(session_id, {}).get(event_id)


async def get_live_event_store(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> LiveEventStore:
    """API-side event live event store dependency."""

    async def create_store() -> AsyncIterator[RedisLiveEventStore]:
        redis = create_redis_client(appctx.config.redis.url)
        store = RedisLiveEventStore(redis)
        try:
            yield store
        finally:
            await redis.aclose()

    return await appctx.get_variable(f"{__name__}.get_live_event_store", create_store)
