"""SDK origin parser tests."""

from typing import Any

from azents.core.enums import SDK_ORIGIN_EVENT_TYPES, EventType
from azents.engine.events.parsers import (
    PARSERS,
    parse_image_generation_item,
    parse_reasoning_item,
    parse_text_item,
    parse_tool_call_item,
    parse_tool_call_output_item,
    parse_unknown_item,
)


class TestParserCoverage:
    def test_all_sdk_origin_types_have_parser(self) -> None:
        """All SDK origin EventTypes are registered in PARSERS."""
        assert set(PARSERS.keys()) == SDK_ORIGIN_EVENT_TYPES


class TestParseTextItem:
    def test_assistant_with_output_text(self) -> None:
        raw = {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": "hello"},
                {"type": "output_text", "text": "world"},
            ],
        }
        data = parse_text_item(raw)
        assert data == {"content": "hello\nworld", "attachments": []}

    def test_assistant_with_image_content(self) -> None:
        raw = {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": "see this"},
                {"type": "input_image", "image_url": "file:///runtime/img.png"},
            ],
        }
        data = parse_text_item(raw)
        assert data["content"] == "see this"
        assert data["attachments"] == [
            {"type": "image", "url": "file:///runtime/img.png"}
        ]

    def test_string_content_fallback(self) -> None:
        """When content is plain string, use it as content as-is."""
        raw = {"type": "message", "role": "assistant", "content": "plain"}
        data = parse_text_item(raw)
        assert data == {"content": "plain", "attachments": []}

    def test_empty_content(self) -> None:
        raw = {"type": "message", "role": "assistant", "content": []}
        data = parse_text_item(raw)
        assert data == {"content": "", "attachments": []}


class TestParseReasoningItem:
    def test_summary_text_combined(self) -> None:
        raw = {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [
                {"type": "summary_text", "text": "step1"},
                {"type": "summary_text", "text": "step2"},
            ],
        }
        data = parse_reasoning_item(raw)
        assert data["reasoning_text"] == "step1\nstep2"
        assert data["reasoning"] == raw

    def test_empty_summary(self) -> None:
        raw = {"type": "reasoning", "id": "rs_1", "summary": []}
        data = parse_reasoning_item(raw)
        assert data == {"reasoning_text": "", "reasoning": raw}


class TestParseToolCallItem:
    def test_function_call(self) -> None:
        raw = {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_abc",
            "name": "shell",
            "arguments": '{"cmd": "ls"}',
        }
        data = parse_tool_call_item(raw)
        assert data == {
            "id": "fc_1",
            "name": "shell",
            "arguments": '{"cmd": "ls"}',
            "call_id": "call_abc",
        }

    def test_web_search_call_falls_back_to_id(self) -> None:
        """When only id exists, id becomes call_id and type becomes name."""
        raw = {
            "type": "web_search_call",
            "id": "ws_1",
        }
        data = parse_tool_call_item(raw)
        assert data == {
            "id": "ws_1",
            "call_id": "ws_1",
            "name": "web_search_call",
            "arguments": "",
        }


class TestParseToolCallOutputItem:
    def test_string_output(self) -> None:
        raw = {
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": "command result",
        }
        data = parse_tool_call_output_item(raw)
        assert data == {
            "call_id": "call_abc",
            "output": {
                "content": "command result",
                "attachments": [],
                "images": [],
            },
        }

    def test_multipart_output_with_image(self) -> None:
        raw = {
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": [
                {"type": "output_text", "text": "screenshot saved"},
                {"type": "input_image", "image_url": "file:///out.png"},
            ],
        }
        data = parse_tool_call_output_item(raw)
        assert data == {
            "call_id": "call_abc",
            "output": {
                "content": "screenshot saved",
                "attachments": [{"type": "image", "url": "file:///out.png"}],
                "images": [],
            },
        }


class TestParseImageGenerationItem:
    def test_attachments_extracted(self) -> None:
        """Extract only file URI preprocessed by emit pipeline into _attachments."""
        raw = {
            "type": "image_generation_call",
            "id": "ig_1",
            "_attachments": [{"type": "image", "url": "file:///out.png"}],
        }
        data = parse_image_generation_item(raw)
        assert data == {"attachments": [{"type": "image", "url": "file:///out.png"}]}

    def test_missing_attachments_defaults_empty(self) -> None:
        raw = {"type": "image_generation_call", "id": "ig_1", "result": "base64..."}
        data = parse_image_generation_item(raw)
        assert data == {"attachments": []}


class TestParseUnknownItem:
    def test_no_extra_fields(self) -> None:
        raw = {"type": "future_xyz", "id": "x_1", "data": "anything"}
        data = parse_unknown_item(raw)
        assert data == {}


class TestPARSERSDispatch:
    def test_each_type_dispatches_to_correct_parser(self) -> None:
        """PARSERS dict maps each type to the appropriate function."""
        cases: list[tuple[EventType, dict[str, Any]]] = [
            (
                EventType.TEXT_ITEM,
                {"type": "message", "role": "assistant", "content": []},
            ),
            (EventType.REASONING_ITEM, {"type": "reasoning", "summary": []}),
            (
                EventType.TOOL_CALL_ITEM,
                {"type": "function_call", "call_id": "c", "name": "n", "arguments": ""},
            ),
            (
                EventType.TOOL_CALL_OUTPUT_ITEM,
                {"type": "function_call_output", "call_id": "c", "output": ""},
            ),
            (
                EventType.IMAGE_GENERATION_ITEM,
                {"type": "image_generation_call", "id": "ig"},
            ),
            (EventType.UNKNOWN_ITEM, {"type": "future_xyz"}),
        ]
        for event_type, raw in cases:
            parser = PARSERS[event_type]
            result = parser(raw)
            assert isinstance(result, dict)
