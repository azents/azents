"""Event chat live event projection store."""

import datetime
import hashlib
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any, Literal, Protocol, assert_never, cast

from fastapi import Depends
from pydantic import TypeAdapter

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.core.enums import EventKind, MailboxItemKind
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
)
from azents.core.redis import create_redis_client
from azents.engine.events.action_messages import (
    ActionMessagePayload,
    PersistedChatAction,
)
from azents.engine.events.provider_tool_semantics import (
    provider_tool_semantic_input_content,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    Event,
    ExternalChannelMessagePayload,
    InputTextPart,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ReasoningPayload,
    ToolkitSourceSnapshot,
    UserContentPart,
    UserMessagePayload,
)
from azents.repos.mailbox.data import MailboxItem
from azents.services.chat.data import (
    PendingMailboxActionPresentation,
    PendingMailboxAgentMessagePresentation,
    PendingMailboxEnvelope,
    PendingMailboxExternalChannelContinuationPresentation,
    PendingMailboxExternalChannelPresentation,
    PendingMailboxGoalContinuationPresentation,
    PendingMailboxItem,
    PendingMailboxUserMessagePresentation,
)
from azents.utils.appctx import AppContext

_LIVE_EVENT_TTL_SECONDS = 300
_live_event_adapter = TypeAdapter(Event)
_chat_action_adapter = TypeAdapter(PersistedChatAction)
_agent_message_adapter = TypeAdapter(AgentMessagePayload)


def _live_event_key(session_id: str) -> str:
    return f"azents:chat:{session_id}:live_events"


def _stable_live_id(session_id: str, *parts: object) -> str:
    raw = ":".join([session_id, *(str(part) for part in parts)])
    return hashlib.md5(raw.encode("utf-8"), usedforsecurity=False).hexdigest()


def reasoning_live_event_id(
    session_id: str,
    *,
    item_id: str | None,
    output_index: int | None,
) -> str:
    """Return the deterministic live projection ID for one reasoning item."""
    if item_id is not None:
        return _stable_live_id(session_id, "reasoning", "item", item_id)
    if output_index is not None:
        return _stable_live_id(session_id, "reasoning", "output", output_index)
    return _stable_live_id(session_id, "reasoning")


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
    item_id: str | None,
    output_index: int | None,
    summary_index: int | None,
    created_at: datetime.datetime,
) -> Event:
    native_item: dict[str, object] = {}
    if item_id is not None:
        native_item["id"] = item_id
    if output_index is not None:
        native_item["output_index"] = output_index
    if summary_index is not None:
        native_item["summary_index"] = summary_index
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
                item=native_item,
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
    wire_dialect: Literal["json_function", "plaintext_custom"],
    source: str,
    created_at: datetime.datetime,
    toolkit_source: ToolkitSourceSnapshot | None = None,
) -> Event:
    return Event(
        id=event_id,
        session_id=session_id,
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id=call_id,
            name=name,
            arguments=arguments,
            wire_dialect=wire_dialect,
            toolkit_source=toolkit_source,
            native_artifact=_live_native_artifact(
                projection="client_tool_call",
                source=source,
                item={},
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


def provider_tool_activity_live_event_id(session_id: str, call_id: str) -> str:
    """Return the deterministic live projection ID for provider-tool activity."""
    return _stable_live_id(session_id, "provider-tool", call_id)


def _provider_tool_activity_live_event(
    *,
    session_id: str,
    event_id: str,
    call_id: str,
    name: str,
    status: Literal["running", "completed", "failed"],
    arguments: str | None,
    created_at: datetime.datetime,
) -> Event:
    """Build one provider-neutral hosted-tool live Event projection."""
    return Event(
        id=event_id,
        session_id=session_id,
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=ProviderToolCallPayload(
            call_id=call_id,
            name=name,
            status=status,
            semantic=provider_tool_semantic_input_content(arguments),
            native_artifact=_live_native_artifact(
                projection="provider_tool_call",
                source="provider_tool_activity",
                item={},
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


def active_tool_call_live_event_id(session_id: str, call_id: str) -> str:
    """Return the deterministic live projection ID for one active tool call."""
    return _stable_live_id(session_id, "tool", call_id)


def active_tool_call_to_live_event(
    session_id: str,
    active_tool_call: ActiveToolCall,
) -> Event:
    """Project one PostgreSQL active call into the stable live event shape."""
    return _tool_call_live_event(
        session_id=session_id,
        event_id=active_tool_call_live_event_id(session_id, active_tool_call.call_id),
        call_id=active_tool_call.call_id,
        name=active_tool_call.name,
        arguments=active_tool_call.arguments or "",
        wire_dialect=active_tool_call.wire_dialect,
        source="active_tool_call",
        created_at=active_tool_call.started_at,
        toolkit_source=active_tool_call.toolkit_source,
    )


def _mailbox_item_requested_profile(
    mailbox_item: MailboxItem,
) -> RequestedInferenceProfile | None:
    """Build the requested profile exposed by a pending input buffer."""
    if mailbox_item.requested_model_target_label is None:
        return None
    return RequestedInferenceProfile(
        model_target_label=mailbox_item.requested_model_target_label,
        reasoning_effort=mailbox_item.requested_reasoning_effort,
    )


def mailbox_item_to_pending_projection(
    mailbox_item: MailboxItem,
) -> PendingMailboxEnvelope:
    """Project a durable typed MailboxItem into a safe public envelope."""
    if mailbox_item.payload is None:
        raise ValueError("Mailbox item payload is required for pending projection")
    projected_items: list[PendingMailboxItem] = []
    for item in mailbox_item.payload.items:
        if mailbox_item.kind is MailboxItemKind.USER_MESSAGE:
            presentation = PendingMailboxUserMessagePresentation(
                type="user_message",
                content=item.content,
                attachments=list(item.attachments),
                file_parts=list(item.file_parts),
                requested_inference_profile=_mailbox_item_requested_profile(
                    mailbox_item
                ),
            )
        elif mailbox_item.kind is MailboxItemKind.GOAL_CONTINUATION:
            presentation = PendingMailboxGoalContinuationPresentation(
                type="goal_continuation",
                content=item.content,
                requested_inference_profile=_mailbox_item_requested_profile(
                    mailbox_item
                ),
            )
        elif mailbox_item.kind is MailboxItemKind.EXTERNAL_CHANNEL_CONTINUATION:
            presentation = PendingMailboxExternalChannelContinuationPresentation(
                type="external_channel_continuation",
                content=item.content,
                requested_inference_profile=_mailbox_item_requested_profile(
                    mailbox_item
                ),
            )
        elif mailbox_item.kind is MailboxItemKind.AGENT_MESSAGE:
            message_kind = item.metadata.get("message_kind")
            if message_kind not in {
                "spawn_agent",
                "send_message",
                "followup_task",
                "agent_result",
            }:
                raise ValueError("Agent mailbox item has an invalid message kind")
            presentation = PendingMailboxAgentMessagePresentation(
                type="agent_message",
                message_kind=cast(
                    Literal[
                        "spawn_agent",
                        "send_message",
                        "followup_task",
                        "agent_result",
                    ],
                    message_kind,
                ),
                content=item.content,
            )
        elif mailbox_item.kind is MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION:
            raw_payload = item.metadata.get("external_channel_message")
            if not isinstance(raw_payload, dict):
                raise ValueError("External mailbox item payload is malformed")
            external = ExternalChannelMessagePayload.model_validate(raw_payload)
            presentation = PendingMailboxExternalChannelPresentation(
                type="external_channel_message",
                provider=external.provider.value,
                resource_label=external.resource_label,
                resource_type=external.resource_type.value,
                external_message_id=external.external_message_id,
                sender_display_name=external.sender_display_name,
                author_type=external.author_type.value,
                authorization=external.authorization,
                body=external.body,
                original_url=external.original_url,
            )
        elif mailbox_item.kind is MailboxItemKind.ACTION_MESSAGE:
            if item.action is None:
                raise ValueError("Action mailbox item payload is missing action")
            presentation = PendingMailboxActionPresentation(
                type="action_message",
                action=_chat_action_adapter.validate_python(item.action),
                message=item.content,
                requested_inference_profile=_mailbox_item_requested_profile(
                    mailbox_item
                ),
            )
        else:
            assert_never(mailbox_item.kind)
        projected_items.append(
            PendingMailboxItem(
                id=f"{mailbox_item.id}:{item.item_key}",
                mailbox_item_id=mailbox_item.id,
                item_key=item.item_key,
                kind=item.presentation_kind,
                created_at=mailbox_item.created_at,
                presentation=presentation,
            )
        )
    return PendingMailboxEnvelope(
        mailbox_item_id=mailbox_item.id,
        session_id=mailbox_item.session_id,
        kind=mailbox_item.kind.value,
        scheduling_mode=mailbox_item.scheduling_mode.value,
        created_at=mailbox_item.created_at,
        items=projected_items,
    )


def mailbox_item_to_live_event(mailbox_item: MailboxItem) -> Event | None:
    """Convert MailboxItem to non-durable live event projection."""
    if mailbox_item.kind == MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION:
        return None
    if mailbox_item.kind == MailboxItemKind.ACTION_MESSAGE:
        if mailbox_item.presentation.action is None:
            raise ValueError("Action message input buffer requires action payload")
        payload = ActionMessagePayload(
            sender_user_id=mailbox_item.sender_user_id,
            action=_chat_action_adapter.validate_python(
                mailbox_item.presentation.action
            ),
            message=mailbox_item.presentation.content,
            requested_inference_profile=_mailbox_item_requested_profile(mailbox_item),
        )
    elif mailbox_item.kind == MailboxItemKind.AGENT_MESSAGE:
        message_payload: dict[str, object] = {
            "message_kind": mailbox_item.presentation.metadata["message_kind"],
            "source_session_agent_id": mailbox_item.presentation.metadata[
                "source_session_agent_id"
            ],
            "source_path": mailbox_item.presentation.metadata["source_path"],
            "target_session_agent_id": mailbox_item.presentation.metadata[
                "target_session_agent_id"
            ],
            "target_path": mailbox_item.presentation.metadata["target_path"],
            "content": mailbox_item.presentation.content,
        }
        for key in (
            "source_run_id",
            "source_run_index",
            "run_status",
            "source_terminal_result_event_id",
        ):
            value = mailbox_item.presentation.metadata.get(key)
            if value is not None:
                message_payload[key] = value
        payload = _agent_message_adapter.validate_python(message_payload)
    else:
        content: str | list[UserContentPart]
        if mailbox_item.presentation.file_parts:
            content = [
                InputTextPart(text=mailbox_item.presentation.content),
                *mailbox_item.presentation.file_parts,
            ]
        else:
            content = mailbox_item.presentation.content
        metadata = {
            key: str(value) for key, value in mailbox_item.presentation.metadata.items()
        }
        metadata["input_buffer_id"] = mailbox_item.id
        metadata["live_projection"] = "input_buffer"
        requested_profile = _mailbox_item_requested_profile(mailbox_item)
        payload = UserMessagePayload(
            sender_user_id=mailbox_item.sender_user_id,
            content=content,
            attachments=[],
            metadata=metadata,
            requested_inference_profile=requested_profile,
            applied_inference_profile=(
                AppliedInferenceProfile(
                    model_target_label=requested_profile.model_target_label,
                    model_display_name=None,
                    reasoning_effort=requested_profile.reasoning_effort,
                )
                if requested_profile is not None
                else None
            ),
        )
    return Event(
        id=mailbox_item.id,
        session_id=mailbox_item.session_id,
        kind=_event_kind_for_mailbox_item(mailbox_item.kind),
        payload=payload,
        model_order=0,
        external_id=mailbox_item.id,
        adapter=None,
        provider=None,
        model=None,
        native_format=None,
        schema_version="1",
        created_at=mailbox_item.created_at,
    )


def _event_kind_for_mailbox_item(kind: MailboxItemKind) -> EventKind:
    """Return live event kind corresponding to MailboxItem kind."""
    match kind:
        case MailboxItemKind.USER_MESSAGE:
            return EventKind.USER_MESSAGE
        case MailboxItemKind.GOAL_CONTINUATION:
            return EventKind.GOAL_CONTINUATION
        case MailboxItemKind.EXTERNAL_CHANNEL_CONTINUATION:
            return EventKind.EXTERNAL_CHANNEL_CONTINUATION
        case MailboxItemKind.ACTION_MESSAGE:
            return EventKind.ACTION_MESSAGE
        case MailboxItemKind.AGENT_MESSAGE:
            return EventKind.AGENT_MESSAGE
        case MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION:
            return EventKind.EXTERNAL_CHANNEL_MESSAGE
        case _:
            raise ValueError(f"Unsupported MailboxItem kind: {kind}")


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
        item_id: str | None,
        output_index: int | None,
        summary_index: int | None,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Merge streaming reasoning delta into live reasoning projection."""
        ...

    async def upsert_provider_tool_activity(
        self,
        session_id: str,
        *,
        call_id: str,
        name: str,
        status: Literal["running", "completed", "failed"],
        arguments: str | None,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Upsert one provider-tool activity snapshot."""
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
        item_id: str | None,
        output_index: int | None,
        summary_index: int | None,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Merge streaming reasoning delta into its live reasoning item."""
        event_id = reasoning_live_event_id(
            session_id,
            item_id=item_id,
            output_index=output_index,
        )
        current = await self._get(session_id, event_id)
        if current is None and item_id is not None and output_index is not None:
            output_event_id = reasoning_live_event_id(
                session_id,
                item_id=None,
                output_index=output_index,
            )
            current = await self._get(session_id, output_event_id)
            if current is not None:
                await self.remove(session_id, output_event_id)
        current_payload = (
            current.payload
            if current is not None and isinstance(current.payload, ReasoningPayload)
            else None
        )
        current_text = current_payload.text if current_payload is not None else ""
        current_summary_index: int | None = None
        if current_payload is not None:
            value = current_payload.native_artifact.item.get("summary_index")
            if isinstance(value, int) and not isinstance(value, bool):
                current_summary_index = value
        separator = (
            "\n"
            if current_text
            and current_summary_index is not None
            and summary_index is not None
            and current_summary_index != summary_index
            else ""
        )
        event = _reasoning_live_event(
            session_id=session_id,
            event_id=event_id,
            text=f"{current_text or ''}{separator}{delta}",
            item_id=item_id,
            output_index=output_index,
            summary_index=summary_index,
            created_at=current.created_at
            if current is not None
            else (now or datetime.datetime.now(datetime.UTC)),
        )
        await self.upsert(event)
        return event

    async def upsert_provider_tool_activity(
        self,
        session_id: str,
        *,
        call_id: str,
        name: str,
        status: Literal["running", "completed", "failed"],
        arguments: str | None,
        now: datetime.datetime | None = None,
    ) -> Event:
        """Upsert one provider-tool activity snapshot."""
        event_id = provider_tool_activity_live_event_id(session_id, call_id)
        current = await self._get(session_id, event_id)
        event = _provider_tool_activity_live_event(
            session_id=session_id,
            event_id=event_id,
            call_id=call_id,
            name=name,
            status=status,
            arguments=arguments,
            created_at=current.created_at
            if current is not None
            else (now or datetime.datetime.now(datetime.UTC)),
        )
        await self.upsert(event)
        return event

    async def remove_live_counterpart(self, event: Event) -> None:
        """Remove corresponding live projection after durable event append."""
        if event.kind == EventKind.ASSISTANT_MESSAGE:
            live_events = await self.list_by_session_id(event.session_id)
            for live_event in live_events:
                if (
                    live_event.kind == EventKind.ASSISTANT_MESSAGE
                    and live_event.adapter == "azents-live"
                ):
                    await self.remove(event.session_id, live_event.id)
        elif isinstance(event.payload, ReasoningPayload):
            native_item = event.payload.native_artifact.item
            raw_item_id = native_item.get("id")
            item_id = raw_item_id if isinstance(raw_item_id, str) else None
            raw_output_index = native_item.get("output_index")
            output_index = (
                raw_output_index
                if isinstance(raw_output_index, int)
                and not isinstance(raw_output_index, bool)
                else None
            )
            live_events = [
                live_event
                for live_event in await self.list_by_session_id(event.session_id)
                if live_event.kind == EventKind.REASONING
                and live_event.adapter == "azents-live"
            ]
            if item_id is not None or output_index is not None:
                counterpart_ids = {
                    reasoning_live_event_id(
                        event.session_id,
                        item_id=item_id,
                        output_index=None,
                    )
                    if item_id is not None
                    else None,
                    reasoning_live_event_id(
                        event.session_id,
                        item_id=None,
                        output_index=output_index,
                    )
                    if output_index is not None
                    else None,
                }
                for live_event in live_events:
                    if live_event.id in counterpart_ids:
                        await self.remove(event.session_id, live_event.id)
            else:
                for live_event in live_events:
                    await self.remove(event.session_id, live_event.id)
        elif isinstance(
            event.payload,
            ProviderToolCallPayload,
        ):
            await self.remove(
                event.session_id,
                provider_tool_activity_live_event_id(
                    event.session_id,
                    event.payload.call_id,
                ),
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
