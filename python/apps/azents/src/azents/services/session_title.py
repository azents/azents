"""Automatic AgentSession title helpers."""

import dataclasses
import logging
import re
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from litellm import acompletion
from litellm.types.utils import ModelResponse
from openai import OpenAIError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionTitleSource, EventKind
from azents.core.llm_mapping import build_credential_kwargs, to_litellm_model
from azents.engine.events.types import (
    AssistantMessagePayload,
    Event,
    FileOutputPart,
    InputTextPart,
    OutputTextPart,
    UserMessagePayload,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.services.chatgpt_oauth.runtime import ensure_runtime_tokens

logger = logging.getLogger(__name__)
_TITLE_MAX_CHARS = 50
_TITLE_RESPONSE_MAX_OUTPUT_TOKENS = 80
_TITLE_CONTEXT_EVENT_LIMIT = 40
_TITLE_CONTEXT_CHAR_LIMIT = 12_000
_TITLE_PROMPT = """\
You are a session title generator. Output ONLY a session title. Nothing else.

<task>
Generate a brief title that helps the user find this agent session later.

Your output must be:
- A single line
- 50 characters or fewer
- No explanations
</task>

<rules>
- Use the same language as the user's main request.
- Make the title grammatically correct and natural.
- Focus on the user's main goal, topic, question, request, or decision.
- Preserve important names, places, dates, numbers, filenames, product names,
  error codes, and domain-specific terms when relevant.
- Do not mention tool names or internal agent actions.
- Do not mention "session", "conversation", "chat", "summary",
  "summarizing", or "generating".
- Never answer the user's question.
- Never say you cannot generate a title.
- Do not assume unstated context or domain.
- If the request is short or conversational, produce a meaningful short title
  such as Greeting, Quick question, or Check-in.
</rules>

<examples>
"plan a 3 day trip to Kyoto" -> Kyoto 3-day trip plan
"help me write a birthday message for Mina" -> Birthday message for Mina
"compare these two insurance options" -> Insurance option comparison
"what should I cook with eggs and spinach" -> Egg and spinach meal ideas
"debug 500 errors in production" -> Production 500 error debugging
"refactor user service" -> User service refactor
"look at @config.json" -> Config review
"translate this email into Spanish" -> Spanish email translation
"summarize the attached notes" -> Attached notes summary
</examples>
"""


def initial_title_from_user_text(text: str) -> str | None:
    """Create a deterministic first-message title candidate."""
    normalized = _normalize_space(text)
    if not normalized:
        return None
    title = normalized.splitlines()[0].strip()
    if not title:
        title = normalized
    return _truncate_title(title)


def initial_title_from_event(event: Event) -> str | None:
    """Create an initial automatic title from a user-like event."""
    if event.kind not in {EventKind.USER_MESSAGE, EventKind.BACKGROUND_COMPLETION}:
        return None
    return initial_title_from_user_text(_user_payload_text(event.payload))


def title_context_from_events(events: Sequence[Event]) -> str:
    """Render recent transcript events for title generation."""
    lines: list[str] = []
    for event in events:
        if event.kind in {
            EventKind.USER_MESSAGE,
            EventKind.BACKGROUND_COMPLETION,
            EventKind.GOAL_CONTINUATION,
        }:
            text = _user_payload_text(event.payload)
            if text:
                lines.append(f"User: {text}")
        elif event.kind == EventKind.ASSISTANT_MESSAGE:
            text = _assistant_payload_text(event.payload)
            if text:
                lines.append(f"Assistant: {text}")
        if sum(len(line) for line in lines) > _TITLE_CONTEXT_CHAR_LIMIT:
            break
    return "\n".join(lines)[:_TITLE_CONTEXT_CHAR_LIMIT]


def clean_generated_title(text: str) -> str | None:
    """Normalize model output into a valid title."""
    cleaned = re.sub(r"<think>[\s\S]*?</think>\s*", "", text).strip()
    for line in cleaned.splitlines():
        candidate = line.strip().strip("\"'`")
        if candidate:
            return _truncate_title(candidate)
    return None


@dataclasses.dataclass
class SessionTitleService:
    """Generate and persist automatic session titles."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def generate_after_first_run(self, session_id: str) -> AgentSession | None:
        """Generate LLM title after first run and replace only auto-initial title."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.title_source != AgentSessionTitleSource.AUTO_INITIAL
            ):
                return None
            agent = await self.agent_repository.get_by_id(
                session,
                agent_session.agent_id,
            )
            if agent is None:
                return None
            events = await self.event_transcript_repository.list_recent_by_session_id(
                session,
                session_id,
                limit=_TITLE_CONTEXT_EVENT_LIMIT,
            )

        context = title_context_from_events(events)
        if not context:
            return None
        generated = await self._generate_title(
            agent_id=agent_session.agent_id,
            session_id=session_id,
            context=context,
        )
        if generated is None:
            return None
        event_id = _latest_event_id(events)
        if event_id is None:
            return None
        async with self.session_manager() as session:
            updated = await self.agent_session_repository.replace_initial_auto_title(
                session,
                session_id=session_id,
                title=generated,
                event_id=event_id,
            )
            await session.commit()
            return updated

    async def _generate_title(
        self,
        *,
        agent_id: str,
        session_id: str,
        context: str,
    ) -> str | None:
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return None
            selection = agent.lightweight_model_selection
            integration = await self.integration_repository.get_by_id_with_secrets(
                session,
                selection.llm_provider_integration_id,
            )
            if integration is None or not integration.enabled:
                return None
            refreshed = await ensure_runtime_tokens(
                integration=integration,
                integration_repository=self.integration_repository,
                session_manager=self.session_manager,
            )
            if refreshed.failure:
                return None
            integration = refreshed.value

        model = to_litellm_model(selection.provider, selection.model_identifier)
        try:
            return await generate_session_title_with_model(
                model=model,
                credential_kwargs=build_credential_kwargs(integration),
                context=context,
                session_id=session_id,
            )
        except OpenAIError:
            logger.warning(
                "Automatic session title generation failed",
                extra={"session_id": session_id, "agent_id": agent_id},
                exc_info=True,
            )
            return None


async def generate_session_title_with_model(
    *,
    model: str,
    credential_kwargs: dict[str, object],
    context: str,
    session_id: str | None = None,
) -> str | None:
    """Generate a session title with LiteLLM chat completion."""
    response = await acompletion(
        model=model,
        messages=[
            {"role": "system", "content": _TITLE_PROMPT},
            {
                "role": "user",
                "content": "Generate a title for this agent session:\n" + context,
            },
        ],
        stream=False,
        max_tokens=_TITLE_RESPONSE_MAX_OUTPUT_TOKENS,
        temperature=0.5,
        **credential_kwargs,  # pyright: ignore[reportArgumentType] # LiteLLM accepts provider-specific credential kwargs through **kwargs.
    )
    del session_id
    if not isinstance(response, ModelResponse):
        return None
    text = _response_text(response)
    if text is None:
        return None
    return clean_generated_title(text)


def _user_payload_text(payload: object) -> str:
    if not isinstance(payload, UserMessagePayload):
        return ""
    return _content_text(payload.content)


def _assistant_payload_text(payload: object) -> str:
    if not isinstance(payload, AssistantMessagePayload):
        return ""
    return _content_text(payload.content)


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, InputTextPart | OutputTextPart):
            parts.append(part.text)
        elif isinstance(part, FileOutputPart) and part.name:
            parts.append(part.name)
    return _normalize_space("\n".join(parts))


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate_title(title: str) -> str:
    normalized = _normalize_space(title)
    if len(normalized) <= _TITLE_MAX_CHARS:
        return normalized
    return normalized[: _TITLE_MAX_CHARS - 1].rstrip() + "…"


def _response_text(response: ModelResponse) -> str | None:
    if not response.choices:
        return None
    return response.choices[0].message.content


def _latest_event_id(events: Sequence[Event]) -> str | None:
    if not events:
        return None
    return events[-1].id
