"""Provider-tool semantic rendering tests."""

from azents.engine.events.provider_tool_rendering import (
    render_provider_tool_semantic,
)
from azents.engine.events.types import (
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolSemanticContent,
    build_native_compat_key,
)


def _native_artifact() -> NativeArtifact:
    """Create an incompatible-agnostic native artifact fixture."""
    compat_key = build_native_compat_key(
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
    )
    return NativeArtifact(
        compat_key=compat_key,
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item={"type": "web_search_call"},
    )


def test_render_provider_tool_call_includes_all_semantic_axes() -> None:
    """Render input, output, and deterministic typed references from a call."""
    payload = ProviderToolCallPayload(
        call_id="call-search",
        name="web_search",
        status="completed",
        semantic=ProviderToolSemanticContent(
            input='{"query":"Azents compaction","type":"search"}',
            output=[OutputTextPart(text="Search completed")],
            references=[
                ProviderToolReference(
                    kind="url",
                    uri="https://example.com/docs",
                    title="Azents docs",
                    excerpt="Relevant excerpt",
                    metadata={"z": "last", "a": "first"},
                )
            ],
        ),
        native_artifact=_native_artifact(),
    )

    assert render_provider_tool_semantic(payload) == (
        "[Provider tool call: web_search completed]\n"
        "Input:\n"
        '{"query":"Azents compaction","type":"search"}\n'
        "Output:\n"
        "Search completed\n"
        "References:\n"
        "- url: https://example.com/docs\n"
        "  Title: Azents docs\n"
        "  Excerpt:\n"
        "    Relevant excerpt\n"
        '  Metadata: {"a":"first","z":"last"}'
    )


def test_render_provider_tool_call_preserves_empty_semantic_identity() -> None:
    """Render name and status even when the provider exposed no semantic body."""
    payload = ProviderToolCallPayload(
        call_id="call-image",
        name="image_generation",
        status="failed",
        semantic=ProviderToolSemanticContent(input=None, output=[], references=[]),
        native_artifact=_native_artifact(),
    )

    assert render_provider_tool_semantic(payload) == (
        "[Provider tool call: image_generation failed]"
    )
