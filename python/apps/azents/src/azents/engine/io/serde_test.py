"""Attachment/FunctionToolCall/Usage serialization utility tests."""

from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.io.serde import (
    deserialize_attachment,
    deserialize_attachments,
    deserialize_tool_calls,
    deserialize_usage,
    serialize_attachment,
    serialize_attachments,
    serialize_tool_calls,
    serialize_usage,
)
from azents.engine.run.types import FunctionToolCall, TokenUsage


class TestAttachmentSerde:
    """Attachment serialization/deserialization tests."""

    def test_round_trip_full(self) -> None:
        """Attachment round-trip with all fields populated."""
        att = RuntimeAttachment(
            uri="s3://bucket/file.png",
            media_type="image/png",
            size=1024,
            name="file.png",
            text_preview="preview text",
            preview_thumbnail_uri="exchange://exchange/workspace/files/thumb/preview.jpg",
        )
        d = serialize_attachment(att)
        restored = deserialize_attachment(d)
        assert restored == att

    def test_round_trip_minimal(self) -> None:
        """Attachment round-trip without optional fields."""
        att = RuntimeAttachment(
            uri="s3://bucket/file.txt",
            media_type="text/plain",
            size=42,
            name="file.txt",
            text_preview=None,
        )
        d = serialize_attachment(att)

        # optional fields are not included in dict
        assert "text_preview" not in d
        assert "preview_thumbnail_uri" not in d

        restored = deserialize_attachment(d)
        assert restored.uri == att.uri
        assert restored.media_type == att.media_type
        assert restored.size == att.size
        assert restored.name == att.name

    def test_serialize_attachments_empty(self) -> None:
        """Empty list returns None."""
        assert serialize_attachments([]) is None

    def test_serialize_attachments_list(self) -> None:
        """List serialization."""
        atts = [
            RuntimeAttachment(
                uri="a",
                media_type="b",
                size=1,
                name="a",
                text_preview=None,
            ),
            RuntimeAttachment(
                uri="c",
                media_type="d",
                size=2,
                name="c",
                text_preview=None,
            ),
        ]
        result = serialize_attachments(atts)
        assert result is not None
        assert len(result) == 2

    def test_deserialize_attachments_none(self) -> None:
        """None returns empty list."""
        assert deserialize_attachments(None) == []

    def test_deserialize_attachments_list(self) -> None:
        """Dict list deserialization."""
        raw = [{"uri": "a", "media_type": "b", "size": 1}]
        result = deserialize_attachments(raw)
        assert len(result) == 1
        assert result[0].uri == "a"


class TestToolCallSerde:
    """FunctionToolCall serialization/deserialization tests."""

    def test_round_trip(self) -> None:
        """FunctionToolCall round-trip."""
        tcs = [
            FunctionToolCall(
                id="tc-1",
                name="search",
                arguments='{"q": "hello"}',
                wire_dialect="json_function",
            )
        ]
        serialized = serialize_tool_calls(tcs)
        assert serialized is not None
        restored = deserialize_tool_calls(serialized)
        assert restored is not None
        assert restored[0].id == "tc-1"
        assert restored[0].name == "search"
        assert restored[0].arguments == '{"q": "hello"}'
        assert restored[0].wire_dialect == "json_function"

    def test_serialize_empty(self) -> None:
        """Empty list returns None."""
        assert serialize_tool_calls([]) is None

    def test_deserialize_none(self) -> None:
        """None returns None."""
        assert deserialize_tool_calls(None) is None

    def test_deserialize_legacy_call_defaults_to_json_function(self) -> None:
        """Legacy serialized calls retain their JSON-function interpretation."""
        result = deserialize_tool_calls(
            [{"id": "tc-legacy", "name": "read", "arguments": "{}"}]
        )

        assert result is not None
        assert result[0].wire_dialect == "json_function"

    def test_deserialize_malformed_arguments_truncated_json(self) -> None:
        """Truncated JSON arguments are replaced with empty object."""
        raw = [
            {
                "id": "tc-1",
                "name": "write",
                "arguments": '{"uri": "session/dog.txt"',
            }
        ]
        result = deserialize_tool_calls(raw)
        assert result is not None
        assert result[0].arguments == "{}"

    def test_deserialize_malformed_arguments_empty_string(self) -> None:
        """Empty string arguments are replaced with empty object."""
        raw = [{"id": "tc-2", "name": "read", "arguments": ""}]
        result = deserialize_tool_calls(raw)
        assert result is not None
        assert result[0].arguments == "{}"

    def test_deserialize_valid_arguments_preserved(self) -> None:
        """Valid JSON arguments are preserved as-is."""
        raw = [
            {
                "id": "tc-3",
                "name": "search",
                "arguments": '{"query": "test", "limit": 10}',
            }
        ]
        result = deserialize_tool_calls(raw)
        assert result is not None
        assert result[0].arguments == '{"query": "test", "limit": 10}'

    def test_deserialize_mixed_valid_and_malformed(self) -> None:
        """A mix of valid and malformed values is handled normally."""
        raw = [
            {"id": "tc-ok", "name": "a", "arguments": '{"x": 1}'},
            {"id": "tc-bad", "name": "b", "arguments": '{"y":'},
        ]
        result = deserialize_tool_calls(raw)
        assert result is not None
        assert result[0].arguments == '{"x": 1}'
        assert result[1].arguments == "{}"


class TestUsageSerde:
    """TokenUsage serialization/deserialization tests."""

    def test_round_trip_full(self) -> None:
        """TokenUsage round-trip with all fields populated."""
        usage = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cached_tokens=10,
            cache_creation_tokens=5,
            reasoning_tokens=20,
            cost_usd=0.000123,
            raw={"model": "test"},
            raw_hidden_params={"response_cost": 0.000123, "model_id": "claude-sonnet"},
        )
        d = serialize_usage(usage)
        assert d is not None
        restored = deserialize_usage(d)
        assert restored == usage

    def test_round_trip_minimal(self) -> None:
        """TokenUsage round-trip without optional fields."""
        usage = TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cached_tokens=None,
            reasoning_tokens=None,
            raw=None,
        )
        d = serialize_usage(usage)
        assert d is not None
        assert "cached_tokens" not in d
        assert "cache_creation_tokens" not in d
        assert "cost_usd" not in d
        assert "raw_hidden_params" not in d
        restored = deserialize_usage(d)
        assert restored is not None
        assert restored.prompt_tokens == 100
        assert restored.cache_creation_tokens is None
        assert restored.cost_usd is None
        assert restored.raw_hidden_params is None

    def test_round_trip_cache_creation_only(self) -> None:
        """Round-trip with only cache_creation_tokens."""
        usage = TokenUsage(
            prompt_tokens=12017,
            completion_tokens=50,
            total_tokens=12067,
            cache_creation_tokens=12002,
        )
        d = serialize_usage(usage)
        assert d is not None
        assert d["cache_creation_tokens"] == 12002
        assert "cached_tokens" not in d
        restored = deserialize_usage(d)
        assert restored == usage

    def test_serialize_none(self) -> None:
        """None returns None."""
        assert serialize_usage(None) is None

    def test_deserialize_none(self) -> None:
        """None returns None."""
        assert deserialize_usage(None) is None
