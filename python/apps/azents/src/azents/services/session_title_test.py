"""Session title helper tests."""

import datetime
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal, cast

import pytest

import azents.services.session_title as session_title_module
from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelection,
    SelectableModelOption,
)
from azents.core.credentials import ApiKeySecrets
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    AgentType,
    EventKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    LLMModelDeveloper,
    LLMProvider,
)
from azents.core.llm_catalog import ModelCapabilities, ModelToolCallingCapabilities
from azents.engine.events.types import (
    AssistantMessagePayload,
    Event,
    ExternalChannelMessagePayload,
    NativeArtifact,
    UserMessagePayload,
)
from azents.engine.model_stream import ModelStreamCallContext
from azents.engine.run.provider_failure import (
    UnclassifiedModelProviderError,
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
    TitleOutputContractError,
    TitleOutputMode,
    clean_generated_title,
    decode_structured_title,
    generate_session_title_with_model,
    initial_title_from_external_channel_event,
    initial_title_from_user_text,
    title_context_from_events,
    title_context_from_initial_prompt,
    title_output_contract_incompatibility,
)
from azents.testing.model_selection import make_test_model_settings
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.types import is_string_object_dict


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

    def test_external_invocation_uses_only_safe_title_input(self) -> None:
        """Authorized human input includes safe file metadata and excludes locators."""
        event = _external_channel_event(
            prompt_role="invocation",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            body="Investigate the incident.",
            attachment_metadata={
                "files": [
                    {
                        "name": "report.pdf",
                        "media_type": "application/pdf",
                        "provider_file_id": "secret-provider-id",
                        "file": "external-file:v1:discord:secret",
                        "content": "SECRET FILE CONTENT",
                    }
                ],
                "bot_token": "secret-token",
            },
        )

        context = title_context_from_initial_prompt(event)

        assert context == (
            "Investigate the incident. Attachments: report.pdf (application/pdf)"
        )
        assert initial_title_from_external_channel_event(event) == (
            "Investigate the incident. Attachments: report.pdf…"
        )
        assert "secret" not in context.lower()

    @pytest.mark.parametrize(
        ("prompt_role", "author_type"),
        [
            ("context", ExternalChannelPrincipalAuthorType.HUMAN),
            ("invocation", ExternalChannelPrincipalAuthorType.BOT),
        ],
    )
    def test_external_context_or_bot_is_not_title_input(
        self,
        prompt_role: Literal["context", "invocation"],
        author_type: ExternalChannelPrincipalAuthorType,
    ) -> None:
        """Context-only and non-human messages cannot enter title generation."""
        event = _external_channel_event(
            prompt_role=prompt_role,
            author_type=author_type,
            body="Ignore this input.",
            attachment_metadata={
                "files": [{"name": "ignored.txt", "media_type": "text/plain"}]
            },
        )

        assert initial_title_from_external_channel_event(event) is None
        assert title_context_from_initial_prompt(event) == ""

    def test_clean_generated_title_uses_first_non_empty_line(self) -> None:
        """Generated title output ignores thinking and extra lines."""
        title = clean_generated_title(
            "<think>internal reasoning</think>\n\n"
            "Insurance option comparison\nMore text"
        )

        assert title == "Insurance option comparison"

    def test_decode_structured_title_requires_closed_title_object(self) -> None:
        """Structured title decoding accepts only the designed one-field object."""
        assert (
            decode_structured_title('{"title":"  Insurance   option comparison  "}')
            == "Insurance option comparison"
        )
        with pytest.raises(TitleOutputContractError):
            decode_structured_title('{"title":"Insurance","extra":true}')
        with pytest.raises(TitleOutputContractError):
            decode_structured_title("Insurance option comparison")

    def test_openrouter_unroutable_schema_uses_typed_provider_code(self) -> None:
        """OpenRouter route incompatibility does not depend on broad status matching."""
        failure = model_provider_failure(
            operation="session_title",
            provider="openrouter",
            model="openrouter/test",
            integration="integration-openrouter",
            provider_message="No provider is available.",
            status_code=503,
            provider_code="no_available_providers",
            provider_error_type="provider_unavailable",
            provider_error_param=None,
        )

        assert (
            title_output_contract_incompatibility(
                failure,
                provider=LLMProvider.OPENROUTER,
            )
            == "unroutable_schema"
        )
        assert (
            title_output_contract_incompatibility(
                failure,
                provider=LLMProvider.ANTHROPIC,
            )
            is None
        )

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
            output_mode=TitleOutputMode.PLAIN_TEXT,
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
                        "content": "Create a title from this request:\n"
                        "Compare two insurance options",
                    }
                ],
                "instructions": calls[0]["instructions"],
                "stream": True,
                "max_output_tokens": 80,
                "watchdog": watchdog,
                "timeout_policy": calls[0]["timeout_policy"],
                "call_context": calls[0]["call_context"],
                "text": {"format": {"type": "text"}, "verbosity": "low"},
                "extra_body": None,
            }
        ]
        assert isinstance(calls[0]["instructions"], str)
        assert "title as plain text" in calls[0]["instructions"]
        assert '"summary"' not in calls[0]["instructions"]
        assert "Bot or App" in calls[0]["instructions"]
        assert "mentions" in calls[0]["instructions"]

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
            output_mode=TitleOutputMode.PLAIN_TEXT,
        )

        assert title == "SDK generated title"
        assert len(calls) == 1
        call = calls[0]
        assert call["provider"] == provider
        assert call["model"] == "gpt-test"
        assert call["input_items"] == [
            {
                "role": "user",
                "content": "Create a title from this request:\n"
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

    @pytest.mark.parametrize(
        ("capability", "expected_mode"),
        [
            (True, TitleOutputMode.STRUCTURED),
            (False, TitleOutputMode.PLAIN_TEXT),
            (None, TitleOutputMode.STRUCTURED),
        ],
    )
    async def test_generate_title_selects_mode_from_saved_capability(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capability: bool | None,
        expected_mode: TitleOutputMode,
    ) -> None:
        """The saved tri-state capability selects the initial title mode."""
        modes: list[TitleOutputMode] = []

        async def generate(**kwargs: object) -> str:
            mode = kwargs["output_mode"]
            assert isinstance(mode, TitleOutputMode)
            modes.append(mode)
            return "Generated title"

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            generate,
        )

        result = await _title_service(
            capability
        )._generate_title(  # Exercise the operation-local mode selection.
            agent_id="agent-001",
            session_id="session-001",
            generation_event_id="0" * 32,
            context="Compare two insurance options",
        )

        assert result == "Generated title"
        assert modes == [expected_mode]

    @pytest.mark.parametrize("capability", [True, None])
    async def test_contract_rejection_fallback_is_unknown_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capability: bool | None,
    ) -> None:
        """Only unknown capability changes mode after typed contract rejection."""
        calls: list[dict[str, object]] = []
        rejection = model_provider_failure(
            operation="session_title",
            provider="openai",
            model="gpt-test",
            integration="integration-001",
            provider_message="Unsupported response format.",
            status_code=400,
            provider_code="invalid_request",
            provider_error_type="invalid_request_error",
            provider_error_param="text.format",
        )

        async def generate(**kwargs: object) -> str:
            calls.append(kwargs)
            if len(calls) == 1:
                raise rejection
            return "Plain compatibility title"

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            generate,
        )

        result = await _title_service(
            capability
        )._generate_title(  # Exercise the bounded compatibility transition.
            agent_id="agent-001",
            session_id="session-001",
            generation_event_id="0" * 32,
            context="Compare two insurance options",
        )

        if capability is None:
            assert result == "Plain compatibility title"
            assert [call["output_mode"] for call in calls] == [
                TitleOutputMode.STRUCTURED,
                TitleOutputMode.PLAIN_TEXT,
            ]
            assert [call["attempt_number"] for call in calls] == [1, 1]
            assert {call["model"] for call in calls} == {"gpt-test"}
        else:
            assert result is None
            assert [call["output_mode"] for call in calls] == [
                TitleOutputMode.STRUCTURED
            ]

    async def test_unknown_operational_failure_retries_structured_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Operational provider failures do not trigger output-mode fallback."""
        modes: list[TitleOutputMode] = []
        rate_limit = model_provider_failure(
            operation="session_title",
            provider="openai",
            model="gpt-test",
            integration="integration-001",
            provider_message="Rate limit exceeded.",
            status_code=429,
            provider_code="rate_limit_exceeded",
            provider_error_type="rate_limit_error",
            provider_error_param=None,
        )

        async def generate(**kwargs: object) -> str:
            mode = kwargs["output_mode"]
            assert isinstance(mode, TitleOutputMode)
            modes.append(mode)
            if len(modes) == 1:
                raise rate_limit
            return "Retried structured title"

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            generate,
        )

        result = await _title_service(
            None, max_retries=1
        )._generate_title(  # Exercise retry interaction with the active mode.
            agent_id="agent-001",
            session_id="session-001",
            generation_event_id="0" * 32,
            context="Compare two insurance options",
        )

        assert result == "Retried structured title"
        assert modes == [TitleOutputMode.STRUCTURED, TitleOutputMode.STRUCTURED]

    async def test_retry_after_transition_stays_in_plain_text_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A transient failure after transition retries only plain text."""
        calls: list[dict[str, object]] = []
        rejection = model_provider_failure(
            operation="session_title",
            provider="openai",
            model="gpt-test",
            integration="integration-001",
            provider_message="Unsupported response format.",
            status_code=400,
            provider_code="invalid_request",
            provider_error_type="invalid_request_error",
            provider_error_param="text.format",
        )
        rate_limit = model_provider_failure(
            operation="session_title",
            provider="openai",
            model="gpt-test",
            integration="integration-001",
            provider_message="Rate limit exceeded.",
            status_code=429,
            provider_code="rate_limit_exceeded",
            provider_error_type="rate_limit_error",
            provider_error_param=None,
        )

        async def generate(**kwargs: object) -> str:
            calls.append(kwargs)
            if len(calls) == 1:
                raise rejection
            if len(calls) == 2:
                raise rate_limit
            return "Plain title after retry"

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            generate,
        )

        result = await _title_service(
            None, max_retries=1
        )._generate_title(  # Exercise retry after the one-way transition.
            agent_id="agent-001",
            session_id="session-001",
            generation_event_id="0" * 32,
            context="Compare two insurance options",
        )

        assert result == "Plain title after retry"
        assert [call["output_mode"] for call in calls] == [
            TitleOutputMode.STRUCTURED,
            TitleOutputMode.PLAIN_TEXT,
            TitleOutputMode.PLAIN_TEXT,
        ]
        assert [call["attempt_number"] for call in calls] == [1, 1, 2]

    @pytest.mark.parametrize("capability", [True, None])
    async def test_schema_decode_fallback_is_unknown_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capability: bool | None,
    ) -> None:
        """Only unknown capability changes mode after schema decode failure."""
        modes: list[TitleOutputMode] = []

        async def generate(**kwargs: object) -> str:
            mode = kwargs["output_mode"]
            assert isinstance(mode, TitleOutputMode)
            modes.append(mode)
            if len(modes) == 1:
                raise TitleOutputContractError("schema_decode")
            return "Plain title after decode failure"

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            generate,
        )

        result = await _title_service(
            capability
        )._generate_title(  # Exercise schema-decode transition policy.
            agent_id="agent-001",
            session_id="session-001",
            generation_event_id="0" * 32,
            context="Compare two insurance options",
        )

        if capability is None:
            assert result == "Plain title after decode failure"
            assert modes == [
                TitleOutputMode.STRUCTURED,
                TitleOutputMode.PLAIN_TEXT,
            ]
        else:
            assert result is None
            assert modes == [TitleOutputMode.STRUCTURED]

    async def test_openrouter_structured_title_requires_routable_parameters(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OpenRouter receives require_parameters only for Structured titles."""
        calls: list[dict[str, object]] = []

        async def fake_call_responses_model(**kwargs: object) -> object:
            calls.append(kwargs)
            return {"output_text": '{"title":"OpenRouter title"}'}

        monkeypatch.setattr(
            session_title_module,
            "call_responses_model",
            fake_call_responses_model,
        )

        title = await generate_session_title_with_model(
            provider=LLMProvider.OPENROUTER,
            provider_integration_id="integration-openrouter",
            model="openrouter/test",
            credential_kwargs={},
            context="Review the routing configuration",
            session_id="session-1",
            attempt_number=1,
            watchdog=make_test_model_stream_watchdog(),
            output_mode=TitleOutputMode.STRUCTURED,
        )

        assert title == "OpenRouter title"
        assert calls[0]["extra_body"] == {"provider": {"require_parameters": True}}
        text = calls[0]["text"]
        assert is_string_object_dict(text)
        text_format = text["format"]
        assert is_string_object_dict(text_format)
        assert text_format["type"] == "json_schema"
        instructions = calls[0]["instructions"]
        assert isinstance(instructions, str)
        assert "title as plain text" not in instructions

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
            external_channel_thread_title_service=cast(Any, _ThreadTitleService()),
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
            provider_error_param=None,
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
                sender_user_id=None,
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
        assert fields["provider_failure_message"] == "Stream must be set to true"
        assert fields["provider_failure_fingerprint"] == failure.fingerprint
        assert fields["provider_failure_retry_outcome"] == "exhausted"

    async def test_generate_title_propagates_unclassified_provider_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Standalone title generation does not retry unclassified outcomes."""
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
            external_channel_thread_title_service=cast(Any, _ThreadTitleService()),
        )
        attempts: list[int] = []

        async def fail_once(**kwargs: object) -> str | None:
            attempt_number = kwargs["attempt_number"]
            assert isinstance(attempt_number, int)
            attempts.append(attempt_number)
            model_provider_failure(
                operation="session_title",
                provider="openai",
                model="gpt-5.1",
                integration="integration-001",
                provider_message="A new provider outcome occurred.",
                status_code=None,
                provider_code="future_failure",
                provider_error_type="future_error",
                provider_error_param=None,
            )

        monkeypatch.setattr(
            session_title_module,
            "generate_session_title_with_model",
            fail_once,
        )
        caplog.set_level(logging.WARNING, logger=session_title_module.logger.name)

        with pytest.raises(UnclassifiedModelProviderError):
            # Exercise the standalone retry boundary directly.
            await service._generate_title(
                agent_id="agent-001",
                session_id="session-001",
                generation_event_id="0" * 32,
                context="Compare two insurance options",
            )

        assert attempts == [1]
        assert not [
            record
            for record in caplog.records
            if record.getMessage() == "Automatic session title provider attempt failed"
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
            external_channel_thread_title_service=cast(Any, _ThreadTitleService()),
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
            provider_error_param=None,
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

        result = (
            await service._generate_title(  # Exercise retry ownership revalidation.
                agent_id="agent-001",
                session_id="session-001",
                generation_event_id="0" * 32,
                context="Compare two insurance options",
            )
        )

        assert result is None
        assert attempts == 1

    async def test_generated_external_title_projects_only_after_commit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The winning final title commits before the one-shot provider helper."""
        calls: list[str] = []

        class WinningRepository(_AgentSessionRepository):
            async def replace_initial_auto_title(
                self,
                session: object,
                *,
                session_id: str,
                title: str,
                event_id: str,
            ) -> AgentSession:
                calls.append("replace")
                current = await self.get_by_id(session, session_id)
                return current.model_copy(
                    update={
                        "title": title,
                        "title_source": AgentSessionTitleSource.AUTO_GENERATED,
                        "title_generation_event_id": event_id,
                    }
                )

        class RecordingSession:
            async def commit(self) -> None:
                calls.append("commit")

        @asynccontextmanager
        async def session_manager() -> AsyncIterator[RecordingSession]:
            yield RecordingSession()

        class RecordingThreadTitleService:
            async def project_generated_title(self, **kwargs: object) -> None:
                assert calls[-1] == "commit"
                assert kwargs["title"] == "Incident response"
                calls.append("project")

        repository = WinningRepository()
        service = SessionTitleService(
            agent_repository=cast(AgentRepository, _AgentRepository()),
            agent_session_repository=cast(AgentSessionRepository, repository),
            integration_repository=cast(
                LLMProviderIntegrationRepository,
                _IntegrationRepository(),
            ),
            session_manager=cast(Any, session_manager),
            model_stream_watchdog=make_test_model_stream_watchdog(),
            retry_policy=FailedRunRetryPolicy(
                max_retries=0,
                base_backoff_seconds=0,
                backoff_multiplier=1,
                max_backoff_seconds=0,
            ),
            external_channel_thread_title_service=cast(
                Any,
                RecordingThreadTitleService(),
            ),
        )

        async def generate_title(**kwargs: object) -> str:
            del kwargs
            calls.append("generate")
            return "Incident response"

        monkeypatch.setattr(service, "_generate_title", generate_title)
        event = _external_channel_event(
            prompt_role="invocation",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            body="Investigate the incident.",
            attachment_metadata={},
        ).model_copy(update={"id": "0" * 32})

        result = await service.generate_from_initial_prompt(
            session_id="session-001",
            event=event,
        )

        assert result is not None
        assert calls == ["generate", "replace", "commit", "project"]

    def test_initial_prompt_context_uses_only_user_text(self) -> None:
        """Initial prompt context excludes later transcript content."""
        event = Event(
            id="0" * 32,
            session_id="session-001",
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                sender_user_id=None,
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
                sender_user_id=None,
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


def _external_channel_event(
    *,
    prompt_role: Literal["context", "invocation"],
    author_type: ExternalChannelPrincipalAuthorType,
    body: str | None,
    attachment_metadata: dict[str, object],
) -> Event:
    """Create one External Channel Event for title-input tests."""
    return Event(
        id="2" * 32,
        session_id="session-001",
        kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
        payload=ExternalChannelMessagePayload(
            provider=ExternalChannelProvider.DISCORD,
            provider_tenant_id="111",
            resource_id="resource-001",
            resource_label="incident-thread",
            resource_type=ExternalChannelResourceType.THREAD,
            binding_id="binding-001",
            invocation_batch_id="batch-001",
            external_message_id="message-001",
            projection_root_id="external-channel:binding-001:message-001",
            provider_message_key="message-001",
            provider_position="1",
            principal_id="principal-001",
            provider_user_id="provider-user-001",
            sender_display_name="Participant",
            author_type=author_type,
            prompt_role=prompt_role,
            body=body,
            attachment_metadata=attachment_metadata,
            provider_created_at=datetime.datetime.now(datetime.UTC),
            provider_updated_at=None,
            original_url=None,
            truncated_context_message_count=0,
            truncated_context_size=0,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _model_selection(
    strict_json_schema: bool | None = None,
) -> AgentModelSelection:
    return AgentModelSelection(
        llm_provider_integration_id="integration-001",
        provider=LLMProvider.OPENAI,
        model_identifier="gpt-test",
        model_display_name="GPT Test",
        model_developer=LLMModelDeveloper.OPENAI,
        normalized_capabilities=ModelCapabilities(
            tool_calling=ModelToolCallingCapabilities(
                strict_json_schema=strict_json_schema
            )
        ),
        model_snapshot={},
    )


class _AgentRepository:
    def __init__(self, strict_json_schema: bool | None = None) -> None:
        self.strict_json_schema = strict_json_schema

    async def get_by_id(self, session: object, agent_id: str) -> Agent:
        del session, agent_id
        now = datetime.datetime.now(datetime.UTC)
        selection = _model_selection(self.strict_json_schema)
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
            tool_search_enabled=False,
            external_channel_default_response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            auto_archive_ttl_days=30,
            enabled=True,
            lifecycle_status=AgentLifecycleStatus.ACTIVE,
            type=AgentType.PUBLIC,
            runtime_profile_id=None,
            runtime_profile_selection_version=1,
            runtime_capability=AgentRuntimeCapability.MANAGED,
            runtime_capability_version=1,
            terminal_enabled=True,
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


class _ThreadTitleService:
    async def project_generated_title(self, **kwargs: object) -> None:
        del kwargs


def _title_service(
    strict_json_schema: bool | None,
    *,
    max_retries: int = 0,
) -> SessionTitleService:
    return SessionTitleService(
        agent_repository=cast(
            AgentRepository,
            _AgentRepository(strict_json_schema),
        ),
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
            max_retries=max_retries,
            base_backoff_seconds=0,
            backoff_multiplier=1,
            max_backoff_seconds=0,
        ),
        external_channel_thread_title_service=cast(Any, _ThreadTitleService()),
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
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            status=AgentSessionStatus.ACTIVE,
            start_reason=AgentSessionStartReason.INITIAL,
            title="Compare two insurance options",
            title_source=AgentSessionTitleSource.AUTO_INITIAL,
            title_generated_at=now,
            title_generation_event_id="0" * 32,
            last_user_input_at=now,
            last_activity_at=now,
            pinned=False,
            started_at=now,
            run_heartbeat_at=now,
            created_at=now,
            updated_at=now,
        )

    async def replace_initial_auto_title(
        self,
        session: object,
        *,
        session_id: str,
        title: str,
        event_id: str,
    ) -> AgentSession | None:
        del session, session_id, title, event_id
        raise AssertionError("replace should not be called when generation fails")
