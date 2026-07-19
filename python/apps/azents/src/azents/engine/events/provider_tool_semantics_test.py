"""Provider-hosted tool semantic normalization tests."""

from azents.core.enums import EventKind
from azents.engine.events.provider_tool_semantics import (
    RESPONSES_PROVIDER_TOOL_SPECS,
    normalize_responses_provider_tool_item,
)
from azents.engine.events.responses_output import ResponsesOutputNormalizer
from azents.engine.events.types import (
    OutputTextPart,
    ProviderToolCallPayload,
    UnknownAdapterOutputPayload,
)


class _ResponsesOutputNormalizer(ResponsesOutputNormalizer):
    """Concrete shared Responses normalizer for contract tests."""

    adapter = "test"


def _normalizer() -> _ResponsesOutputNormalizer:
    """Create a provider-neutral Responses normalizer."""
    return _ResponsesOutputNormalizer(
        provider="openai",
        model="gpt-5.1",
        operation="sampling",
        integration=None,
    )


def test_registry_requires_semantic_extractor_for_every_recognized_item() -> None:
    """Keep recognition and semantic extraction in one registry contract."""
    assert set(RESPONSES_PROVIDER_TOOL_SPECS) == {
        "web_search_call",
        "web_search",
        "file_search_call",
        "code_interpreter_call",
        "image_generation_call",
        "mcp_call",
    }
    assert all(
        callable(spec.extract) for spec in RESPONSES_PROVIDER_TOOL_SPECS.values()
    )


def test_normalizes_web_search_input_and_source_references() -> None:
    """Preserve exposed search action, query, and source URLs."""
    event = _normalizer().normalize_output_item(
        "session-1",
        {
            "type": "web_search_call",
            "id": "search-1",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "Azents compaction",
                "sources": [
                    {"type": "url", "url": "https://example.com/one"},
                    {"type": "url", "url": "https://example.com/two"},
                ],
            },
        },
        output_index=0,
    )

    assert event.kind == EventKind.PROVIDER_TOOL_CALL
    payload = event.payload
    assert isinstance(payload, ProviderToolCallPayload)
    assert payload.name == "web_search"
    assert payload.status == "completed"
    assert payload.semantic.input == '{"query":"Azents compaction","type":"search"}'
    assert payload.semantic.output == []
    assert [reference.uri for reference in payload.semantic.references] == [
        "https://example.com/one",
        "https://example.com/two",
    ]


def test_normalizes_web_open_page_url_as_input_and_reference() -> None:
    """Retain page URLs exposed directly by Web-search actions."""
    normalized = normalize_responses_provider_tool_item(
        {
            "type": "web_search_call",
            "id": "search-1",
            "action": {
                "type": "open_page",
                "url": "https://example.com/page",
            },
        }
    )

    assert normalized is not None
    assert normalized.semantic.input == (
        '{"type":"open_page","url":"https://example.com/page"}'
    )
    assert [reference.uri for reference in normalized.semantic.references] == [
        "https://example.com/page"
    ]


def test_normalizes_file_search_results_and_file_references() -> None:
    """Preserve file queries, result text, identity, score, and excerpt."""
    normalized = normalize_responses_provider_tool_item(
        {
            "type": "file_search_call",
            "id": "file-search-1",
            "queries": ["semantic transcript"],
            "results": [
                {
                    "file_id": "file-1",
                    "filename": "design.md",
                    "score": 0.875,
                    "text": "Provider tools use one semantic contract.",
                }
            ],
        }
    )

    assert normalized is not None
    assert normalized.name == "file_search"
    assert normalized.semantic.input == '{"queries":["semantic transcript"]}'
    assert normalized.semantic.output == [
        OutputTextPart(text="design.md:\nProvider tools use one semantic contract.")
    ]
    reference = normalized.semantic.references[0]
    assert reference.kind == "file"
    assert reference.title == "design.md"
    assert reference.excerpt == "Provider tools use one semantic contract."
    assert reference.metadata == {"file_id": "file-1", "score": "0.875"}


def test_normalizes_code_interpreter_code_logs_and_image_reference() -> None:
    """Preserve code, textual logs, and exposed output image URLs."""
    normalized = normalize_responses_provider_tool_item(
        {
            "type": "code_interpreter_call",
            "id": "code-1",
            "code": "print('done')",
            "outputs": [
                {"type": "logs", "logs": "done\n"},
                {"type": "image", "url": "https://example.com/chart.png"},
            ],
        }
    )

    assert normalized is not None
    assert normalized.name == "code_interpreter"
    assert normalized.semantic.input == "print('done')"
    assert normalized.semantic.output == [OutputTextPart(text="done\n")]
    assert normalized.semantic.references[0].model_dump(mode="json") == {
        "kind": "url",
        "uri": "https://example.com/chart.png",
        "title": "Output image",
        "excerpt": None,
        "metadata": {},
    }


def test_normalizes_image_generation_prompt_without_persisting_result_bytes() -> None:
    """Keep image input semantic while transient bytes use materialization."""
    event = _normalizer().normalize_output_item(
        "session-1",
        {
            "type": "image_generation_call",
            "id": "image-1",
            "status": "completed",
            "prompt": "Draw a semantic transcript diagram",
            "quality": "high",
            "result": "base64-must-not-enter-semantic-output",
        },
        output_index=0,
    )

    assert event.kind == EventKind.PROVIDER_TOOL_CALL
    payload = event.payload
    assert isinstance(payload, ProviderToolCallPayload)
    assert payload.semantic.input == (
        '{"prompt":"Draw a semantic transcript diagram","quality":"high"}'
    )
    assert payload.semantic.output == []
    assert "result" not in payload.native_artifact.item


def test_normalizes_mcp_arguments_output_error_name_and_status() -> None:
    """Preserve MCP call semantics without leaking arbitrary native metadata."""
    event = _normalizer().normalize_output_item(
        "session-1",
        {
            "type": "mcp_call",
            "id": "mcp-1",
            "name": "lookup",
            "server_label": "docs",
            "arguments": '{"query":"Azents"}',
            "output": "Found the design.",
            "error": "Partial provider warning",
            "status": "incomplete",
            "provider_extension": "opaque",
        },
        output_index=0,
    )

    assert event.kind == EventKind.PROVIDER_TOOL_CALL
    payload = event.payload
    assert isinstance(payload, ProviderToolCallPayload)
    assert payload.name == "mcp:lookup"
    assert payload.status == "failed"
    assert payload.semantic.input == (
        '{"arguments":"{\\"query\\":\\"Azents\\"}",'
        '"name":"lookup","server_label":"docs"}'
    )
    assert payload.semantic.output == [
        OutputTextPart(text="Found the design."),
        OutputTextPart(text="Error: Partial provider warning"),
    ]


def test_bounds_semantic_input_reference_count_and_reference_fields() -> None:
    """Apply deterministic persistence bounds before canonical event creation."""
    normalized = normalize_responses_provider_tool_item(
        {
            "type": "web_search_call",
            "id": "search-1",
            "action": {
                "type": "search",
                "query": "q" * 40_000,
                "sources": [
                    {"url": f"https://example.com/{index}/" + "u" * 5000}
                    for index in range(101)
                ],
            },
        }
    )

    assert normalized is not None
    assert normalized.semantic.input is not None
    assert len(normalized.semantic.input) == 30_000
    assert normalized.semantic.input.endswith("... [truncated]")
    assert len(normalized.semantic.references) == 100
    assert all(
        reference.uri is not None and len(reference.uri) <= 4096
        for reference in normalized.semantic.references
    )


def test_missing_provider_tool_call_id_becomes_unknown_output() -> None:
    """Avoid inventing durable association identity for malformed output."""
    event = _normalizer().normalize_output_item(
        "session-1",
        {
            "type": "web_search_call",
            "status": "completed",
            "action": {"type": "search", "query": "Azents"},
        },
        output_index=0,
    )

    assert event.kind == EventKind.UNKNOWN_ADAPTER_OUTPUT
    assert isinstance(event.payload, UnknownAdapterOutputPayload)
    assert event.payload.reason == "web_search_call:missing_call_id"
