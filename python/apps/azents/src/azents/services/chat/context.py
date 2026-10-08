"""Chat session context inspector service."""

import dataclasses
import datetime
from typing import Annotated, Literal

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from pydantic import BaseModel, Field

from azents.core.agent_session_data import AgentSession
from azents.core.chat_data import (
    NotWorkspaceMember,
    SessionNotFound,
)
from azents.core.enums import EventKind
from azents.core.json_value import JSONValue
from azents.engine.events.external_channel_rendering import (
    render_external_channel_message,
)
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.types import (
    AssistantMessagePayload,
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    ExternalChannelMessagePayload,
    InputTextPart,
    OutputContentPart,
    OutputTextPart,
    ProviderToolCallPayload,
    ReasoningPayload,
    ScheduledTaskContinuationPayload,
    ScheduledTaskResultPayload,
    ScheduledTaskTriggerPayload,
    SkillLoadedPayload,
    SystemPromptAnalysisPayload,
    SystemPromptFragmentPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserContentPart,
    UserMessagePayload,
    public_event_payload,
)
from azents.repos.chat_context_snapshot import SessionContextSnapshotRepository

ContextBreakdownKey = Literal["system", "user", "assistant", "tool", "other"]


class SessionContextSession(BaseModel):
    """Context inspector session summary."""

    id: str = Field(description="AgentSession ID")
    agent_id: str = Field(description="Agent ID")
    created_at: datetime.datetime | None = Field(default=None)
    updated_at: datetime.datetime | None = Field(default=None)


class SessionContextStats(BaseModel):
    """Context inspector aggregate stats."""

    total_events: int = 0
    user_messages: int = 0
    assistant_messages: int = 0
    reasoning_events: int = 0
    tool_calls: int = 0
    tool_results: int = 0
    turn_markers: int = 0
    total_cost_usd: float | None = None


class SessionContextBreakdownSegment(BaseModel):
    """Approximate prompt token breakdown segment."""

    key: ContextBreakdownKey
    tokens: int
    percent: float


class SessionContextSystemPromptFragment(BaseModel):
    """Context inspector system prompt fragment."""

    id: str
    source: Literal["agent", "toolkit", "turn_injected", "final"]
    label: str
    content: str
    preview: str
    length: int
    metadata: dict[str, str]

    @classmethod
    def from_payload(
        cls,
        payload: SystemPromptFragmentPayload,
    ) -> "SessionContextSystemPromptFragment":
        """Convert from Event payload."""
        return cls(
            id=payload.id,
            source=payload.source,
            label=payload.label,
            content=payload.content,
            preview=payload.preview,
            length=payload.length,
            metadata=dict(payload.metadata),
        )


class SessionContextSystemPrompt(BaseModel):
    """Context inspector system prompt analysis payload."""

    agent_prompt: SessionContextSystemPromptFragment | None = None
    toolkit_prompts: list[SessionContextSystemPromptFragment] = Field(
        default_factory=list
    )
    injected_prompts: list[SessionContextSystemPromptFragment] = Field(
        default_factory=list
    )
    final_prompt: SessionContextSystemPromptFragment | None = None

    @classmethod
    def from_payload(
        cls,
        payload: SystemPromptAnalysisPayload,
    ) -> "SessionContextSystemPrompt":
        """Convert from Event payload."""
        return cls(
            agent_prompt=(
                SessionContextSystemPromptFragment.from_payload(payload.agent_prompt)
                if payload.agent_prompt is not None
                else None
            ),
            toolkit_prompts=[
                SessionContextSystemPromptFragment.from_payload(fragment)
                for fragment in payload.toolkit_prompts
            ],
            injected_prompts=[
                SessionContextSystemPromptFragment.from_payload(fragment)
                for fragment in payload.injected_prompts
            ],
            final_prompt=(
                SessionContextSystemPromptFragment.from_payload(payload.final_prompt)
                if payload.final_prompt is not None
                else None
            ),
        )


class SessionContextRawEvent(BaseModel):
    """Raw event for context inspector."""

    id: str
    kind: EventKind
    payload: dict[str, JSONValue]
    external_id: str | None
    adapter: str | None
    provider: str | None
    model: str | None
    native_format: str | None
    schema_version: str
    created_at: datetime.datetime

    @classmethod
    def from_event(cls, event: Event) -> "SessionContextRawEvent":
        """Convert Event to raw event response model."""
        return cls.model_validate(
            {
                "id": event.id,
                "kind": event.kind,
                "payload": public_event_payload(event.kind, event.payload),
                "external_id": event.external_id,
                "adapter": event.adapter,
                "provider": event.provider,
                "model": event.model,
                "native_format": event.native_format,
                "schema_version": event.schema_version,
                "created_at": event.created_at,
            }
        )


class SessionContext(BaseModel):
    """AgentSession context inspector payload."""

    session: SessionContextSession
    usage: TokenUsagePayload | None
    stats: SessionContextStats
    breakdown: list[SessionContextBreakdownSegment]
    system_prompt: SessionContextSystemPrompt | None
    raw_events: list[SessionContextRawEvent]


@dataclasses.dataclass
class SessionContextService:
    """AgentSession context inspector service."""

    snapshot_repository: Annotated[
        SessionContextSnapshotRepository, Depends(SessionContextSnapshotRepository)
    ]

    async def get_session_context(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        limit: int,
    ) -> Result[SessionContext, SessionNotFound | NotWorkspaceMember]:
        """Fetch context of an AgentSession accessible by user."""
        result = await self.snapshot_repository.read(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            limit=limit,
        )
        if isinstance(result, Failure):
            return Failure(result.error)
        snapshot = result.value
        return Success(
            _build_context(
                snapshot.session,
                list(snapshot.events),
                snapshot.system_prompt,
            )
        )


def _build_context(
    agent_session: AgentSession,
    events: list[Event],
    system_prompt_analysis: SystemPromptAnalysisPayload | None,
) -> SessionContext:
    """Build context inspector payload from events."""
    usage = _latest_usage(events)
    system_prompt = (
        SessionContextSystemPrompt.from_payload(system_prompt_analysis)
        if system_prompt_analysis is not None
        else None
    )
    return SessionContext(
        session=SessionContextSession(
            id=agent_session.id,
            agent_id=agent_session.agent_id,
            created_at=agent_session.created_at,
            updated_at=agent_session.updated_at,
        ),
        usage=usage,
        stats=_build_stats(events),
        breakdown=_build_breakdown(events, system_prompt),
        system_prompt=system_prompt,
        raw_events=[SessionContextRawEvent.from_event(event) for event in events],
    )


def _latest_usage(events: list[Event]) -> TokenUsagePayload | None:
    """Return latest turn marker usage."""
    for event in reversed(events):
        payload = event.payload
        if isinstance(payload, TurnMarkerPayload):
            return payload.usage
    return None


def _build_stats(events: list[Event]) -> SessionContextStats:
    """Calculate Event statistics."""
    cost_total = 0.0
    has_cost = False
    stats = SessionContextStats(total_events=len(events))
    for event in events:
        match event.kind:
            case EventKind.USER_MESSAGE | EventKind.EXTERNAL_CHANNEL_MESSAGE:
                stats.user_messages += 1
            case EventKind.ASSISTANT_MESSAGE:
                stats.assistant_messages += 1
            case EventKind.REASONING:
                stats.reasoning_events += 1
            case EventKind.CLIENT_TOOL_CALL | EventKind.PROVIDER_TOOL_CALL:
                stats.tool_calls += 1
            case EventKind.CLIENT_TOOL_RESULT:
                stats.tool_results += 1
            case EventKind.TURN_MARKER:
                stats.turn_markers += 1
                if isinstance(event.payload, TurnMarkerPayload):
                    cost = event.payload.usage.cost_usd
                    if cost is not None:
                        cost_total += cost
                        has_cost = True
            case _:
                pass
    if has_cost:
        stats.total_cost_usd = cost_total
    return stats


def _build_breakdown(
    events: list[Event],
    system_prompt: SessionContextSystemPrompt | None,
) -> list[SessionContextBreakdownSegment]:
    """Create prompt breakdown based on Event payload character count."""
    chars: dict[ContextBreakdownKey, int] = {
        "system": 0,
        "user": 0,
        "assistant": 0,
        "tool": 0,
        "other": 0,
    }
    if system_prompt is not None:
        chars["system"] += _system_prompt_chars(system_prompt)

    for event in events:
        payload = event.payload
        if isinstance(payload, UserMessagePayload):
            chars["user"] += _content_chars(payload.content)
        elif isinstance(payload, ExternalChannelMessagePayload):
            chars["user"] += len(render_external_channel_message(payload))
        elif isinstance(
            payload,
            ScheduledTaskTriggerPayload | ScheduledTaskContinuationPayload,
        ):
            chars["user"] += len(payload.content)
        elif isinstance(payload, ScheduledTaskResultPayload):
            chars["assistant"] += len(payload.result) + len(payload.title)
        elif isinstance(payload, SkillLoadedPayload):
            chars["user"] += len(payload.body)
        elif isinstance(payload, AssistantMessagePayload):
            chars["assistant"] += _content_chars(payload.content)
        elif isinstance(payload, ReasoningPayload):
            chars["assistant"] += len(payload.text or "") + len(payload.summary or "")
        elif isinstance(payload, ClientToolCallPayload):
            chars["tool"] += len(payload.name) + len(payload.arguments)
        elif isinstance(payload, ClientToolResultPayload):
            chars["tool"] += sum(_output_part_chars(part) for part in payload.output)
        elif isinstance(payload, ProviderToolCallPayload):
            chars["tool"] += len(render_provider_tool_semantic(payload))

    known_chars: dict[ContextBreakdownKey, int] = {
        key: value for key, value in chars.items() if value > 0
    }
    total_chars = sum(known_chars.values())
    if total_chars <= 0:
        return []

    return [
        SessionContextBreakdownSegment(
            key=key,
            tokens=value,
            percent=round((value / total_chars) * 100, 1),
        )
        for key, value in known_chars.items()
    ]


def _system_prompt_chars(system_prompt: SessionContextSystemPrompt) -> int:
    """Calculate character count of system prompt fragment."""
    if system_prompt.final_prompt is not None:
        return system_prompt.final_prompt.length
    fragments = [
        system_prompt.agent_prompt,
        *system_prompt.toolkit_prompts,
        *system_prompt.injected_prompts,
    ]
    return sum(fragment.length for fragment in fragments if fragment is not None)


def _content_chars(
    content: str | list[UserContentPart] | list[OutputContentPart],
) -> int:
    """Calculate approximate character count from Event content part."""
    if isinstance(content, str):
        return len(content)
    total = 0
    for part in content:
        if isinstance(part, InputTextPart) or (
            isinstance(part, OutputTextPart) and part.type == "output_text"
        ):
            total += len(part.text)
        else:
            total += len(part.type)
    return total


def _output_part_chars(part: OutputContentPart | str) -> int:
    """Calculate approximate character count from Tool output part."""
    if isinstance(part, str):
        return 0
    if isinstance(part, OutputTextPart):
        return len(part.text) if part.type == "output_text" else len(part.type)
    if isinstance(part, AttachmentOutputPart):
        return len(part.name or part.attachment_id or part.type)
    return len(part.name or part.type)
