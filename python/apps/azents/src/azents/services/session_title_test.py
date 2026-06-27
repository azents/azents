"""Session title helper tests."""

import datetime

import pytest
from litellm.types.utils import ModelResponse

import azents.services.session_title as session_title_module
from azents.core.enums import EventKind
from azents.engine.events.types import (
    AssistantMessagePayload,
    Event,
    NativeArtifact,
    UserMessagePayload,
)
from azents.services.session_title import (
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

    async def test_generate_session_title_reads_typed_model_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Generated title reads LiteLLM's typed ModelResponse shape."""

        async def fake_acompletion(*args: object, **kwargs: object) -> ModelResponse:
            del args, kwargs
            return ModelResponse(
                choices=[
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Insurance option comparison",
                        },
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ]
            )

        monkeypatch.setattr(session_title_module, "acompletion", fake_acompletion)

        title = await generate_session_title_with_model(
            model="openai/test",
            credential_kwargs={},
            context="Compare two insurance options",
        )

        assert title == "Insurance option comparison"

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
