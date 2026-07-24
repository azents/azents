"""Session context breakdown tests for provider-tool semantics."""

import datetime
from types import SimpleNamespace
from typing import cast

from azents.core.enums import (
    EventKind,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.engine.events.external_channel_rendering import (
    render_external_channel_message,
)
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.types import (
    Event,
    ExternalChannelMessagePayload,
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


def test_context_breakdown_counts_external_file_metadata() -> None:
    """Count the complete shared External Channel file rendering."""
    payload = ExternalChannelMessagePayload(
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        resource_id="resource-1",
        resource_label="#incident / thread",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding-1",
        invocation_batch_id="batch-1",
        external_message_id="message-1",
        revision_id="revision-1",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        projection_root_id="external-channel:binding-1:message-1",
        provider_message_key="slack:tenant-1:C1:1.000001",
        provider_position="00000000000000000001.000001",
        principal_id="principal-1",
        provider_user_id="U1",
        sender_display_name="Alice",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        authorization="authorized_invocation",
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        body="Process the attached report.",
        attachment_metadata={
            "files": [
                {
                    "name": "report.csv",
                    "title": "Report",
                    "media_type": "text/csv",
                    "declared_size": 1024,
                    "supported": True,
                    "unsupported_reason": None,
                    "file": "external-file:v1:slack:binding-1:F123",
                }
            ]
        },
        reference_mappings={},
        provider_created_at=datetime.datetime(2026, 7, 22, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url=None,
        truncated_context_message_count=0,
        truncated_context_size=0,
        correction_of_revision_id=None,
    )
    event = Event(
        id="2" * 32,
        session_id="session-1",
        kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
        payload=payload,
        created_at=datetime.datetime(2026, 7, 22, tzinfo=datetime.UTC),
    )

    breakdown = _build_breakdown([event], None)
    rendered = render_external_channel_message(payload)

    assert len(breakdown) == 1
    assert breakdown[0].key == "user"
    assert breakdown[0].tokens == len(rendered)
    assert "File: external-file:v1:slack:binding-1:F123" in rendered


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
