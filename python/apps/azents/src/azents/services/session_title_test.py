"""Session title helper tests."""

import datetime
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest

import azents.services.session_title as session_title_module
from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelection,
    SelectableModelOption,
)
from azents.core.credentials import ApiKeySecrets
from azents.core.enums import (
    AgentSessionKind,
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
from azents.engine.model_stream import ModelStreamCallContext
from azents.engine.run.provider_failure import (
    ModelProviderFailureCategory,
    model_provider_failure,
)
from azents.engine.run.retry_policy import FailedRunRetryPolicy
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
from azents.testing.model_selection import make_test_model_settings
from azents.testing.model_stream import make_test_model_stream_watchdog


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

        watchdog = make_test_model_stream_watchdog()
        title = await generate_session_title_with_model(
            provider=LLMProvider.ANTHROPIC,
            provider_integration_id=None,
            model="anthropic/test",
            credential_kwargs={},
            context="Compare two insurance options",
            session_id=None,
            attempt_number=None,
            watchdog=watchdog,
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
                "watchdog": watchdog,
                "timeout_policy": calls[0]["timeout_policy"],
                "call_context": calls[0]["call_context"],
            }
        ]
        assert isinstance(calls[0]["instructions"], str)
        assert "session title generator" in calls[0]["instructions"]

    @pytest.mark.parametrize(
        "provider",
        [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH],
    )
    async def test_generate_session_title_routes_openai_compatible_providers_to_sdk(
        self,
        monkeypatch: pytest.MonkeyPatch,
        provider: LLMProvider,
    ) -> None:
        """Both OpenAI-compatible title routes use the bounded SDK helper."""
        calls: list[dict[str, object]] = []

        async def fake_call_openai_responses_text(**kwargs: object) -> str:
            calls.append(kwargs)
            return "SDK generated title"

        monkeypatch.setattr(
            session_title_module,
            "call_openai_responses_text",
            fake_call_openai_responses_text,
        )

        watchdog = make_test_model_stream_watchdog()
        title = await generate_session_title_with_model(
            provider=provider,
            provider_integration_id="integration-title",
            model="gpt-test",
            credential_kwargs={"api_key": "test-key"},
            context="Describe the SDK migration",
            session_id="session-1",
            attempt_number=3,
            watchdog=watchdog,
        )

        assert title == "SDK generated title"
        assert len(calls) == 1
        call = calls[0]
        assert call["provider"] == provider
        assert call["model"] == "gpt-test"
        assert call["input_items"] == [
            {
                "role": "user",
                "content": "Generate a title for this initial user prompt:\n"
                "Describe the SDK migration",
            }
        ]
        assert call["text"] == {
            "format": {"type": "text"},
            "verbosity": "low",
        }
        call_context = call["call_context"]
        assert isinstance(call_context, ModelStreamCallContext)
        assert call_context.provider_integration_id == "integration-title"
        assert call_context.attempt_number == 3
        assert "max_output_tokens" not in call

    async def test_generate_title_logs_model_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
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
            model_stream_watchdog=make_test_model_stream_watchdog(),
            retry_policy=FailedRunRetryPolicy(
                max_retries=0,
                base_backoff_seconds=0,
                backoff_multiplier=1,
                max_backoff_seconds=0,
            ),
        )

        failure = model_provider_failure(
            operation="session_title",
            provider="openai",
            model="gpt-5.1",
            integration=None,
            provider_message="Stream must be set to true",
            status_code=400,
            provider_code="invalid_request",
            provider_error_type="bad_request",
        )

        async def raise_bad_request(**kwargs: object) -> str | None:
            del kwargs
            raise failure

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

        caplog.set_level(logging.WARNING, logger=session_title_module.logger.name)

        result = await service.generate_from_initial_prompt(
            session_id="session-001",
            event=event,
        )

        assert result is None
        records = [
            record
            for record in caplog.records
            if record.getMessage() == "Automatic session title provider attempt failed"
        ]
        assert len(records) == 1
        fields = records[0].__dict__
        assert fields["session_id"] == "session-001"
        assert fields["agent_id"] == "agent-001"
        assert fields["attempt_number"] == 1
        assert fields["provider_failure_operation"] == "session_title"
        assert fields["provider_failure_provider"] == "openai"
        assert fields["provider_failure_integration"] is None
        assert fields["provider_failure_model"] == "gpt-5.1"
        assert fields["provider_failure_category"] == "invalid_request"
        assert fields["provider_failure_retryability"] == "non_retryable"
        assert fields["provider_failure_status_code"] == 400
        assert fields["provider_failure_code"] == "invalid_request"
        assert fields["provider_failure_error_type"] == "bad_request"
        assert fields["provider_failure_fingerprint"] == failure.fingerprint
        assert fields["provider_failure_retry_outcome"] == "exhausted"

    async def test_generate_title_retries_unknown_provider_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Standalone title generation uses the shared full retry budget."""
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
            model_stream_watchdog=make_test_model_stream_watchdog(),
            retry_policy=FailedRunRetryPolicy(
                max_retries=2,
                base_backoff_seconds=0,
                backoff_multiplier=1,
                max_backoff_seconds=0,
            ),
        )
        failure = model_provider_failure(
            operation="session_title",
            provider="openai",
            model="gpt-5.1",
            integration="integration-001",
            provider_message="A new provider outcome occurred.",
            status_code=None,
            provider_code="future_failure",
            provider_error_type="future_error",
            category=ModelProviderFailureCategory.UNKNOWN,
        )
        attempts: list[int] = []

        async def fail_twice(**kwargs: object) -> str | None:
            attempt_number = kwargs["attempt_number"]
            assert isinstance(attempt_number, int)
            attempts.append(attempt_number)
            if len(attempts) <= 2:
                raise failure
            return "Recovered title"

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            fail_twice,
        )
        caplog.set_level(logging.WARNING, logger=session_title_module.logger.name)

        result = await service._generate_title(  # pyright: ignore[reportPrivateUsage]  # Exercise the standalone retry boundary directly.
            agent_id="agent-001",
            session_id="session-001",
            generation_event_id="0" * 32,
            context="Compare two insurance options",
        )

        assert result == "Recovered title"
        assert attempts == [1, 2, 3]
        warning_records = [
            record
            for record in caplog.records
            if record.getMessage() == "Automatic session title provider attempt failed"
        ]
        assert [
            record.__dict__["provider_failure_retry_outcome"]
            for record in warning_records
        ] == ["scheduled", "scheduled"]
        error_records = [
            record
            for record in caplog.records
            if record.getMessage() == "Unknown model provider failure"
        ]
        assert len(error_records) == 2
        assert [
            record.__dict__["provider_failure_fingerprint"] for record in error_records
        ] == [
            failure.fingerprint,
            failure.fingerprint,
        ]

    async def test_title_retry_stops_after_manual_title_change(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A manual title change prevents the next provider attempt."""

        class MutableTitleRepository(_AgentSessionRepository):
            source = AgentSessionTitleSource.AUTO_INITIAL

            async def get_by_id(
                self,
                session: object,
                session_id: str,
            ) -> AgentSession:
                current = await super().get_by_id(session, session_id)
                return current.model_copy(update={"title_source": self.source})

        title_repository = MutableTitleRepository()
        service = SessionTitleService(
            agent_repository=cast(AgentRepository, _AgentRepository()),
            agent_session_repository=cast(AgentSessionRepository, title_repository),
            integration_repository=cast(
                LLMProviderIntegrationRepository,
                _IntegrationRepository(),
            ),
            session_manager=cast(Any, _session_manager),
            model_stream_watchdog=make_test_model_stream_watchdog(),
            retry_policy=FailedRunRetryPolicy(
                max_retries=2,
                base_backoff_seconds=0,
                backoff_multiplier=1,
                max_backoff_seconds=0,
            ),
        )
        failure = model_provider_failure(
            operation="session_title",
            provider="openai",
            model="gpt-5.1",
            integration="integration-001",
            provider_message="Temporarily unavailable.",
            status_code=503,
            provider_code="service_unavailable",
            provider_error_type="server_error",
        )
        attempts = 0

        async def fail_after_manual_update(**kwargs: object) -> str | None:
            nonlocal attempts
            del kwargs
            attempts += 1
            title_repository.source = AgentSessionTitleSource.MANUAL
            raise failure

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            fail_after_manual_update,
        )

        result = await service._generate_title(  # pyright: ignore[reportPrivateUsage]  # Exercise retry ownership revalidation.
            agent_id="agent-001",
            session_id="session-001",
            generation_event_id="0" * 32,
            context="Compare two insurance options",
        )

        assert result is None
        assert attempts == 1

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
            selectable_model_options=[
                SelectableModelOption(
                    label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                    model_selection=selection,
                    settings=make_test_model_settings(),
                )
            ],
            main_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
            lightweight_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
            enabled=True,
            type=AgentType.PUBLIC,
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
            owner_generation=0,
            inference_state=None,
            id="session-001",
            workspace_id="workspace-001",
            agent_id="agent-001",
            handle="test-session-handle",
            session_kind=AgentSessionKind.ROOT,
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
