"""Session title helper tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from openai import OpenAIError

import azents.services.session_title as session_title_module
from azents.core.agent import AgentModelSelection
from azents.core.credentials import ApiKeySecrets
from azents.core.enums import (
    AgentRole,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    AgentType,
    EventKind,
    LLMModelDeveloper,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.types import (
    AssistantMessagePayload,
    Event,
    NativeArtifact,
    UserMessagePayload,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.services.session_title import (
    SessionTitleService,
    clean_generated_title,
    generate_session_title_with_model,
    initial_title_from_user_text,
    title_context_from_events,
    title_context_from_initial_prompt,
)


class TestSessionTitleHelpers:
    """Automatic title helper behavior."""

    def test_initial_title_normalizes_and_truncates(self) -> None:
        """First-message title uses normalized text and a hard length cap."""
        title = initial_title_from_user_text(
            "  Plan    a 3 day trip to Kyoto with family and museum visits  "
        )

        assert title == "Plan a 3 day trip to Kyoto with family and museum…"
        assert title is not None
        assert len(title) <= 50

    def test_clean_generated_title_uses_first_non_empty_line(self) -> None:
        """Generated title output ignores thinking and extra lines."""
        title = clean_generated_title(
            "<think>internal reasoning</think>\n\n"
            "Insurance option comparison\nMore text"
        )

        assert title == "Insurance option comparison"

    async def test_generate_session_title_uses_shared_responses_helper(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Generated title delegates to the shared Responses helper."""
        calls: list[dict[str, object]] = []

        async def fake_call_responses_model(**kwargs: object) -> object:
            calls.append(kwargs)
            return {"output_text": "Insurance option comparison"}

        monkeypatch.setattr(
            session_title_module,
            "call_responses_model",
            fake_call_responses_model,
        )

        title = await generate_session_title_with_model(
            provider=LLMProvider.ANTHROPIC,
            model="anthropic/test",
            credential_kwargs={},
            context="Compare two insurance options",
        )

        assert title == "Insurance option comparison"
        assert calls == [
            {
                "provider": LLMProvider.ANTHROPIC,
                "model": "anthropic/test",
                "credential_kwargs": {},
                "input_items": [
                    {
                        "role": "user",
                        "content": "Generate a title for this initial user prompt:\n"
                        "Compare two insurance options",
                    }
                ],
                "instructions": calls[0]["instructions"],
                "stream": True,
                "max_output_tokens": 80,
            }
        ]
        assert isinstance(calls[0]["instructions"], str)
        assert "session title generator" in calls[0]["instructions"]

    async def test_generate_title_logs_model_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Model call failures are logged by the title service and not re-raised."""
        service = SessionTitleService(
            agent_repository=cast(AgentRepository, _AgentRepository()),
            agent_session_repository=cast(
                AgentSessionRepository,
                _AgentSessionRepository(),
            ),
            integration_repository=cast(
                LLMProviderIntegrationRepository,
                _IntegrationRepository(),
            ),
            session_manager=cast(Any, _session_manager),
        )

        async def raise_bad_request(**kwargs: object) -> str | None:
            del kwargs
            raise OpenAIError("Stream must be set to true")

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            raise_bad_request,
        )

        event = Event(
            id="0" * 32,
            session_id="session-001",
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                content="Compare two insurance options",
                attachments=[],
                metadata={},
            ),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        log_calls: list[tuple[str, dict[str, object]]] = []

        def record_exception(message: str, **kwargs: object) -> None:
            log_calls.append((message, kwargs))

        monkeypatch.setattr(session_title_module.logger, "exception", record_exception)

        result = await service.generate_from_initial_prompt(
            session_id="session-001",
            event=event,
        )

        assert result is None
        assert log_calls == [
            (
                "Automatic session title generation failed",
                {
                    "extra": {
                        "session_id": "session-001",
                        "agent_id": "agent-001",
                        "provider": "openai",
                        "model": "gpt-test",
                    }
                },
            )
        ]

    def test_initial_prompt_context_uses_only_user_text(self) -> None:
        """Initial prompt context excludes later transcript content."""
        event = Event(
            id="0" * 32,
            session_id="session-001",
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                content="Compare two insurance options",
                attachments=[],
                metadata={},
            ),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        assert title_context_from_initial_prompt(event) == (
            "Compare two insurance options"
        )

    def test_title_context_uses_user_and_assistant_text(self) -> None:
        """Title context includes user and assistant transcript text."""
        created_at = datetime.datetime.now(datetime.UTC)
        user = Event(
            id="0" * 32,
            session_id="session-001",
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                content="Compare two insurance options",
                attachments=[],
                metadata={},
            ),
            created_at=created_at,
        )
        assistant = Event(
            id="1" * 32,
            session_id="session-001",
            kind=EventKind.ASSISTANT_MESSAGE,
            payload=AssistantMessagePayload(
                content="I can compare coverage and cost.",
                attachments=[],
                native_artifact=NativeArtifact(
                    adapter="test",
                    provider="test",
                    model="test",
                    native_format="test",
                    schema_version="1",
                    compat_key="test:test:test:test:1",
                    item={},
                ),
            ),
            created_at=created_at,
        )

        assert title_context_from_events([user, assistant]) == (
            "User: Compare two insurance options\n"
            "Assistant: I can compare coverage and cost."
        )


def _model_selection() -> AgentModelSelection:
    return AgentModelSelection(
        llm_provider_integration_id="integration-001",
        provider=LLMProvider.OPENAI,
        model_identifier="gpt-test",
        model_display_name="GPT Test",
        model_developer=LLMModelDeveloper.OPENAI,
        normalized_capabilities=ModelCapabilities(),
        model_snapshot={},
    )


class _AgentRepository:
    async def get_by_id(self, session: object, agent_id: str) -> Agent:
        del session, agent_id
        now = datetime.datetime.now(datetime.UTC)
        selection = _model_selection()
        return Agent(
            id="agent-001",
            workspace_id="workspace-001",
            name="Test agent",
            model_selection=selection,
            lightweight_model_selection=selection,
            enabled=True,
            type=AgentType.PUBLIC,
            role=AgentRole.AGENT,
            created_at=now,
            updated_at=now,
        )


class _IntegrationRepository:
    async def get_by_id_with_secrets(
        self,
        session: object,
        integration_id: str,
    ) -> LLMProviderIntegrationWithSecrets:
        del session, integration_id
        now = datetime.datetime.now(datetime.UTC)
        return LLMProviderIntegrationWithSecrets(
            id="integration-001",
            workspace_id="workspace-001",
            provider=LLMProvider.OPENAI,
            name="OpenAI test",
            secrets=ApiKeySecrets(api_key="test-key"),
            enabled=True,
            created_at=now,
            updated_at=now,
        )


@asynccontextmanager
async def _session_manager() -> AsyncIterator[object]:
    yield object()


class _AgentSessionRepository:
    async def get_by_id(self, session: object, session_id: str) -> AgentSession:
        del session, session_id
        now = datetime.datetime.now(datetime.UTC)
        return AgentSession(
            id="session-001",
            workspace_id="workspace-001",
            agent_id="agent-001",
            status=AgentSessionStatus.ACTIVE,
            start_reason=AgentSessionStartReason.INITIAL,
            title="Compare two insurance options",
            title_source=AgentSessionTitleSource.AUTO_INITIAL,
            title_generated_at=now,
            title_generation_event_id="0" * 32,
            last_user_input_at=now,
            started_at=now,
            run_heartbeat_at=now,
            created_at=now,
            updated_at=now,
        )

    async def replace_initial_auto_title(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("replace should not be called when generation fails")
