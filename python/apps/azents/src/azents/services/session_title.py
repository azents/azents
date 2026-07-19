"""Automatic AgentSession title helpers."""

import asyncio
import dataclasses
import logging
import re
from collections.abc import Sequence
from typing import Annotated

from azcommon.logging import bind_extra
from fastapi import Depends
from litellm.exceptions import OpenAIError as LiteLLMOpenAIError
from openai import OpenAIError as OpenAIBaseError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionTitleSource, EventKind, LLMProvider
from azents.core.llm_mapping import build_credential_kwargs, to_runtime_model
from azents.engine.events.litellm_responses import map_litellm_provider_error
from azents.engine.events.openai_responses import call_openai_responses_text
from azents.engine.events.types import (
    AssistantMessagePayload,
    Event,
    FileOutputPart,
    InputTextPart,
    OutputTextPart,
    UserMessagePayload,
)
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamWatchdog,
    get_model_stream_watchdog,
)
from azents.engine.responses import (
    DEFAULT_RESPONSES_TEXT_CONFIG,
    ResponsesOutputError,
    call_responses_model,
    extract_response_text,
)
from azents.engine.run.errors import ModelCallError, ModelStreamTimeoutError
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    model_provider_error_log_fields,
    model_provider_failure,
)
from azents.engine.run.retry_policy import (
    FailedRunRetryPolicy,
    get_failed_run_retry_policy,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
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
Generate a brief title from the user's initial prompt so the user can find
this agent session later. You only receive the first user prompt, not the
assistant response or later transcript.

Your output must be:
- A single line
- 50 characters or fewer
- No explanations
</task>

<rules>
- Use the same language as the user's main request.
- Make the title grammatically correct and natural.
- Focus on the user's main goal, topic, question, request, or decision from
  the initial prompt.
- Do not rely on assistant responses, tool results, or later user corrections.
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
    if event.kind is not EventKind.USER_MESSAGE:
        return None
    return initial_title_from_user_text(_user_payload_text(event.payload))


def title_context_from_initial_prompt(event: Event) -> str:
    """Render the initial user prompt for title generation."""
    if event.kind is not EventKind.USER_MESSAGE:
        return ""
    return _user_payload_text(event.payload)[:_TITLE_CONTEXT_CHAR_LIMIT]


def title_context_from_events(events: Sequence[Event]) -> str:
    """Render recent transcript events for title generation."""
    lines: list[str] = []
    for event in events:
        if event.kind in {
            EventKind.USER_MESSAGE,
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
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    model_stream_watchdog: Annotated[
        ModelStreamWatchdog,
        Depends(get_model_stream_watchdog),
    ]
    retry_policy: Annotated[
        FailedRunRetryPolicy,
        Depends(get_failed_run_retry_policy),
    ]

    async def generate_from_initial_prompt(
        self,
        session_id: str,
        event: Event,
    ) -> AgentSession | None:
        """Generate LLM title from the first prompt without waiting for run end."""
        context = title_context_from_initial_prompt(event)
        if not context:
            return None
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.title_source != AgentSessionTitleSource.AUTO_INITIAL
                or agent_session.title_generation_event_id != event.id
            ):
                return None

        generated = await self._generate_title(
            agent_id=agent_session.agent_id,
            session_id=session_id,
            generation_event_id=event.id,
            context=context,
        )
        if generated is None:
            return None
        async with self.session_manager() as session:
            updated = await self.agent_session_repository.replace_initial_auto_title(
                session,
                session_id=session_id,
                title=generated,
                event_id=event.id,
            )
            await session.commit()
            return updated

    async def _generate_title(
        self,
        *,
        agent_id: str,
        session_id: str,
        generation_event_id: str,
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

        model = to_runtime_model(selection.provider, selection.model_identifier)
        credential_kwargs = build_credential_kwargs(integration)
        attempt_number = 1
        while True:
            if attempt_number > 1 and not await self._generation_is_current(
                session_id=session_id,
                generation_event_id=generation_event_id,
            ):
                return None
            try:
                return await generate_session_title_with_model(
                    provider=selection.provider,
                    provider_integration_id=selection.llm_provider_integration_id,
                    model=model,
                    credential_kwargs=credential_kwargs,
                    context=context,
                    session_id=session_id,
                    attempt_number=attempt_number,
                    watchdog=self.model_stream_watchdog,
                )
            except ModelProviderFailure as exc:
                retry_available = self.retry_policy.retry_available(attempt_number)
                L = bind_extra(
                    logger,
                    {
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "attempt_number": attempt_number,
                        **model_provider_error_log_fields(exc),
                        "provider_failure_retry_outcome": (
                            "scheduled" if retry_available else "exhausted"
                        ),
                    },
                )
                L.warning("Automatic session title provider attempt failed")
                if not retry_available:
                    return None
                await asyncio.sleep(self.retry_policy.backoff_seconds(attempt_number))
                attempt_number += 1
            except ModelStreamTimeoutError as exc:
                logger.warning(
                    "Automatic session title generation timed out",
                    extra={
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "attempt_number": attempt_number,
                        "provider": selection.provider.value,
                        "model": model,
                        "model_stream_timeout_kind": exc.timeout_kind,
                        "model_stream_failure_code": exc.failure_code,
                        "model_stream_deadline_seconds": exc.deadline_seconds,
                        "model_stream_elapsed_seconds": exc.elapsed_seconds,
                    },
                )
                return None
            except ModelCallError, ResponsesOutputError:
                logger.exception(
                    "Automatic session title generation failed",
                    extra={
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "attempt_number": attempt_number,
                        "provider": selection.provider.value,
                        "model": model,
                    },
                )
                return None

    async def _generation_is_current(
        self,
        *,
        session_id: str,
        generation_event_id: str,
    ) -> bool:
        """Return whether the initial automatic title still owns generation."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
        return (
            agent_session is not None
            and agent_session.title_source == AgentSessionTitleSource.AUTO_INITIAL
            and agent_session.title_generation_event_id == generation_event_id
        )


async def generate_session_title_with_model(
    *,
    provider: LLMProvider,
    provider_integration_id: str | None,
    model: str,
    credential_kwargs: dict[str, object],
    context: str,
    session_id: str | None,
    attempt_number: int | None,
    watchdog: ModelStreamWatchdog,
) -> str | None:
    """Generate a session title with the standard LiteLLM Responses API path."""
    timeout_policy = watchdog.resolve_policy(
        provider=provider.value,
        model=model,
        inference_profile=None,
    )
    call_context = ModelStreamCallContext(
        call_kind="session_title",
        provider=provider.value,
        provider_integration_id=provider_integration_id,
        model=model,
        session_id=session_id,
        run_id=None,
        attempt_number=attempt_number,
        check_stop=None,
    )
    input_items: list[dict[str, object]] = [
        {
            "role": "user",
            "content": "Generate a title for this initial user prompt:\n" + context,
        }
    ]
    try:
        if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
            text = await call_openai_responses_text(
                provider=provider,
                model=model,
                credential_kwargs=credential_kwargs,
                input_items=input_items,
                instructions=_TITLE_PROMPT,
                text=DEFAULT_RESPONSES_TEXT_CONFIG,
                watchdog=watchdog,
                timeout_policy=timeout_policy,
                call_context=call_context,
            )
        else:
            response = await call_responses_model(
                provider=provider,
                model=model,
                credential_kwargs=credential_kwargs,
                input_items=input_items,
                instructions=_TITLE_PROMPT,
                stream=True,
                max_output_tokens=_TITLE_RESPONSE_MAX_OUTPUT_TOKENS,
                watchdog=watchdog,
                timeout_policy=timeout_policy,
                call_context=call_context,
            )
            text = await extract_response_text(response)
    except ModelProviderFailure:
        raise
    except ResponsesOutputError as exc:
        raise model_provider_failure(
            operation="session_title",
            provider=provider.value,
            model=model,
            integration=provider_integration_id,
            provider_message=exc.message,
            status_code=None,
            provider_code=exc.code,
            provider_error_type=exc.event_type,
        ) from None
    except (LiteLLMOpenAIError, OpenAIBaseError) as exc:
        failure = map_litellm_provider_error(exc, call_context=call_context)
        raise failure from None
    if not text:
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
