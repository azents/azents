"""Chat session context inspector service."""

import dataclasses
import datetime
from typing import Annotated, Literal, cast

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    ReasoningPayload,
    SystemPromptAnalysisPayload,
    SystemPromptFragmentPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.chat.data import AgentNotFound, NotWorkspaceMember

ContextBreakdownKey = Literal["system", "user", "assistant", "tool", "other"]


class SessionContextSession(BaseModel):
    """Context inspector session summary."""

    id: str | None = Field(description="AgentSession ID")
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
        return cls(
            id=event.id,
            kind=event.kind,
            payload=event.payload.model_dump(mode="json", exclude_none=True),
            external_id=event.external_id,
            adapter=event.adapter,
            provider=event.provider,
            model=event.model,
            native_format=event.native_format,
            schema_version=event.schema_version,
            created_at=event.created_at,
        )


class SessionContext(BaseModel):
    """Agent active session context inspector payload."""

    session: SessionContextSession
    usage: TokenUsagePayload | None
    stats: SessionContextStats
    breakdown: list[SessionContextBreakdownSegment]
    system_prompt: SessionContextSystemPrompt | None
    raw_events: list[SessionContextRawEvent]


@dataclasses.dataclass
class SessionContextService:
    """Agent active session context inspector service."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def get_agent_context(
        self,
        *,
        agent_id: str,
        user_id: str,
        limit: int,
    ) -> Result[SessionContext, AgentNotFound | NotWorkspaceMember]:
        """Fetch active session context of Agent accessible by user."""
        bounded_limit = max(1, min(limit, 500))
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())

            active_session = await self.agent_session_repository.get_active_by_agent_id(
                session,
                agent_id,
            )
            if active_session is None:
                return Success(_empty_context(agent_id))

            events = await self.transcript_repository.list_recent_by_session_id(
                session,
                active_session.id,
                limit=bounded_limit,
            )
            return Success(_build_context(active_session, events))


def _empty_context(agent_id: str) -> SessionContext:
    """Create empty context for Agent without active session."""
    return SessionContext(
        session=SessionContextSession(
            id=None,
            agent_id=agent_id,
            created_at=None,
            updated_at=None,
        ),
        usage=None,
        stats=SessionContextStats(),
        breakdown=[],
        system_prompt=None,
        raw_events=[],
    )


def _build_context(
    active_session: AgentSession,
    events: list[Event],
) -> SessionContext:
    """Build context inspector payload from events."""
    usage = _latest_usage(events)
    return SessionContext(
        session=SessionContextSession(
            id=active_session.id,
            agent_id=active_session.agent_id,
            created_at=active_session.created_at,
            updated_at=active_session.updated_at,
        ),
        usage=usage,
        stats=_build_stats(events),
        breakdown=_build_breakdown(events),
        system_prompt=_latest_system_prompt(events),
        raw_events=[SessionContextRawEvent.from_event(event) for event in events],
    )


def _latest_usage(events: list[Event]) -> TokenUsagePayload | None:
    """Return latest turn marker usage."""
    for event in reversed(events):
        payload = event.payload
        if isinstance(payload, TurnMarkerPayload):
            return payload.usage
    return None


def _latest_system_prompt(
    events: list[Event],
) -> SessionContextSystemPrompt | None:
    """Return system prompt analysis payload of latest turn marker."""
    for event in reversed(events):
        payload = event.payload
        if isinstance(payload, TurnMarkerPayload) and payload.system_prompt is not None:
            return SessionContextSystemPrompt.from_payload(payload.system_prompt)
    return None


def _build_stats(events: list[Event]) -> SessionContextStats:
    """Calculate Event statistics."""
    cost_total = 0.0
    has_cost = False
    stats = SessionContextStats(total_events=len(events))
    for event in events:
        match event.kind:
            case EventKind.USER_MESSAGE:
                stats.user_messages += 1
            case EventKind.ASSISTANT_MESSAGE:
                stats.assistant_messages += 1
            case EventKind.REASONING:
                stats.reasoning_events += 1
            case EventKind.CLIENT_TOOL_CALL | EventKind.PROVIDER_TOOL_CALL:
                stats.tool_calls += 1
            case EventKind.CLIENT_TOOL_RESULT | EventKind.PROVIDER_TOOL_RESULT:
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
) -> list[SessionContextBreakdownSegment]:
    """Create prompt breakdown based on Event payload character count."""
    chars: dict[ContextBreakdownKey, int] = {
        "system": 0,
        "user": 0,
        "assistant": 0,
        "tool": 0,
        "other": 0,
    }
    system_prompt = _latest_system_prompt(events)
    if system_prompt is not None:
        chars["system"] += _system_prompt_chars(system_prompt)

    for event in events:
        payload = event.payload
        if isinstance(payload, UserMessagePayload):
            chars["user"] += _content_chars(payload.content)
        elif isinstance(payload, AssistantMessagePayload):
            chars["assistant"] += _content_chars(payload.content)
        elif isinstance(payload, ReasoningPayload):
            chars["assistant"] += len(payload.text or "") + len(payload.summary or "")
        elif isinstance(payload, ClientToolCallPayload | ProviderToolCallPayload):
            chars["tool"] += len(payload.name) + len(payload.arguments or "")
        elif isinstance(payload, ClientToolResultPayload | ProviderToolResultPayload):
            chars["tool"] += sum(_output_part_chars(part) for part in payload.output)

    known_chars = {key: value for key, value in chars.items() if value > 0}
    total_chars = sum(known_chars.values())
    if total_chars <= 0:
        return []

    return [
        SessionContextBreakdownSegment(
            key=cast(ContextBreakdownKey, key),
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


def _content_chars(content: object) -> int:
    """Calculate approximate character count from Event content part."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            part_type = getattr(part, "type", None)
            if part_type in {"input_text", "output_text"}:
                total += len(getattr(part, "text", "") or "")
            else:
                total += len(str(part_type or ""))
        return total
    return len(str(content))


def _output_part_chars(part: object) -> int:
    """Calculate approximate character count from Tool output part."""
    if getattr(part, "type", None) == "output_text":
        return len(getattr(part, "text", "") or "")
    name = getattr(part, "name", None)
    attachment_id = getattr(part, "attachment_id", None)
    return len(str(name or attachment_id or getattr(part, "type", "")))
