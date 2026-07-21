"""Session context breakdown tests for provider-tool semantics."""

import datetime
from types import SimpleNamespace
from typing import cast

from azents.core.enums import EventKind
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.types import (
    Event,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolSemanticContent,
    SystemPromptAnalysisPayload,
    SystemPromptFragmentPayload,
    build_native_compat_key,
)
from azents.repos.agent_session.data import AgentSession
from azents.services.chat.context import (
    SessionContextSystemPrompt,
    _build_breakdown,  # pyright: ignore[reportPrivateUsage]
    _build_context,  # pyright: ignore[reportPrivateUsage]
)


def _native_artifact() -> NativeArtifact:
    """Create native artifact for context projection tests."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item={"type": "provider_tool"},
    )


def _semantic(label: str) -> ProviderToolSemanticContent:
    """Create complete provider-tool semantic content."""
    return ProviderToolSemanticContent(
        input=f"input {label}",
        output=[OutputTextPart(text=f"output {label}")],
        references=[
            ProviderToolReference(
                kind="url",
                uri=f"https://example.com/{label}",
                title=None,
                excerpt=None,
                metadata={},
            )
        ],
    )


def test_context_breakdown_counts_full_provider_call_semantics() -> None:
    """Count provider input, output, and references through shared rendering."""
    call = ProviderToolCallPayload(
        call_id="call-1",
        name="web_search",
        status="completed",
        semantic=_semantic("call"),
        native_artifact=_native_artifact(),
    )
    result = ProviderToolCallPayload(
        call_id="result-1",
        name="file_search",
        status="completed",
        semantic=_semantic("result"),
        native_artifact=_native_artifact(),
    )
    now = datetime.datetime.now(datetime.UTC)
    events = [
        Event(
            id="0" * 32,
            session_id="session-1",
            kind=EventKind.PROVIDER_TOOL_CALL,
            payload=call,
            created_at=now,
        ),
        Event(
            id="1" * 32,
            session_id="session-1",
            kind=EventKind.PROVIDER_TOOL_CALL,
            payload=result,
            created_at=now,
        ),
    ]

    breakdown = _build_breakdown(events, None)

    assert len(breakdown) == 1
    assert breakdown[0].key == "tool"
    assert breakdown[0].tokens == len(render_provider_tool_semantic(call)) + len(
        render_provider_tool_semantic(result)
    )
    assert breakdown[0].percent == 100.0


def test_context_breakdown_uses_session_prompt_snapshot() -> None:
    """Count the final prompt from the replaceable session snapshot."""
    final_prompt = SystemPromptFragmentPayload(
        id="final",
        source="final",
        label="Final system prompt",
        content="latest system prompt",
        preview="latest system prompt",
        length=len("latest system prompt"),
    )

    breakdown = _build_breakdown(
        [],
        SessionContextSystemPrompt.from_payload(
            SystemPromptAnalysisPayload(final_prompt=final_prompt)
        ),
    )

    assert len(breakdown) == 1
    assert breakdown[0].key == "system"
    assert breakdown[0].tokens == final_prompt.length
    assert breakdown[0].percent == 100.0


def test_context_projection_uses_session_prompt_snapshot() -> None:
    """Expose snapshot prompt analysis without reading a turn marker."""
    now = datetime.datetime.now(datetime.UTC)
    agent_session = cast(
        AgentSession,
        SimpleNamespace(
            id="session-1",
            agent_id="agent-1",
            created_at=now,
            updated_at=now,
        ),
    )
    final_prompt = SystemPromptFragmentPayload(
        id="final",
        source="final",
        label="Final system prompt",
        content="latest prompt",
        preview="latest prompt",
        length=len("latest prompt"),
    )

    context = _build_context(
        agent_session,
        [],
        SystemPromptAnalysisPayload(final_prompt=final_prompt),
    )

    assert context.system_prompt is not None
    assert context.system_prompt.final_prompt is not None
    assert context.system_prompt.final_prompt.content == "latest prompt"
