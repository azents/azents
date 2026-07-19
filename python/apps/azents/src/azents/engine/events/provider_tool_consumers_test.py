"""Provider-tool semantic consumer regression tests."""

import datetime
import json

import pytest

from azents.core.enums import EventKind
from azents.engine.events.engine_adapter import (
    _render_event_for_summary,  # pyright: ignore[reportPrivateUsage]
)
from azents.engine.events.filters import (
    _estimate_single_event_tokens,  # pyright: ignore[reportPrivateUsage]
    _model_visible_event_text,  # pyright: ignore[reportPrivateUsage]
    _model_visible_event_value,  # pyright: ignore[reportPrivateUsage]
    _render_continuity_history,  # pyright: ignore[reportPrivateUsage]
)
from azents.engine.events.provider_tool_rendering import (
    render_provider_tool_semantic,
)
from azents.engine.events.types import (
    Event,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolSemanticContent,
    build_native_compat_key,
)


def _native_artifact() -> NativeArtifact:
    """Create native artifact containing data that must stay opaque."""
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
        item={"type": "web_search_call", "opaque_secret": "do-not-render"},
    )


def _semantic() -> ProviderToolSemanticContent:
    """Create semantic content exercising all consumer axes."""
    return ProviderToolSemanticContent(
        input='{"query":"semantic transcript"}',
        output=[OutputTextPart(text="provider output")],
        references=[
            ProviderToolReference(
                kind="url",
                uri="https://example.com/source",
                title="Source",
                excerpt="Bounded excerpt",
                metadata={"rank": "1"},
            )
        ],
    )


def _event(payload: ProviderToolCallPayload) -> Event:
    """Wrap a provider-tool payload as a durable event."""
    return Event(
        id="0" * 32,
        session_id="session-1",
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
    )


@pytest.mark.parametrize(
    "event",
    [
        _event(
            ProviderToolCallPayload(
                call_id="call-1",
                name="web_search",
                status="completed",
                semantic=_semantic(),
                native_artifact=_native_artifact(),
            )
        ),
        _event(
            ProviderToolCallPayload(
                call_id="interrupted-1",
                name="file_search",
                status="interrupted",
                semantic=_semantic(),
                native_artifact=_native_artifact(),
            )
        ),
    ],
    ids=["completed", "interrupted"],
)
def test_provider_tool_consumers_share_the_semantic_renderer(event: Event) -> None:
    """Summary, continuity, and token estimation use the same semantic text."""
    payload = event.payload
    assert isinstance(payload, ProviderToolCallPayload)
    rendered = render_provider_tool_semantic(payload)

    assert _render_event_for_summary(event) == rendered
    assert _model_visible_event_value(event) == {
        "role": "assistant",
        "content": rendered,
    }
    assert _model_visible_event_text(event) == f"Assistant:\n{rendered}"
    continuity = _render_continuity_history([event])
    assert f"Assistant:\n{rendered}" in continuity
    assert "do-not-render" not in continuity

    visible_bytes = len(
        json.dumps(
            {"role": "assistant", "content": rendered},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    assert _estimate_single_event_tokens(event) == (visible_bytes + 3) // 4
