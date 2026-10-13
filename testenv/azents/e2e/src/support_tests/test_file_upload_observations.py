"""Docker-free message parsing regressions for file-upload E2E helpers."""

import pytest
from pydantic import ValidationError

from support.observations import decode_history_page
from tests.required.public.test_file_upload import (
    _content_text,
    _message_with_content,
    _MessagePayload,
)


def test_structured_text_and_opaque_file_parts_keep_upload_evidence() -> None:
    payload = _MessagePayload.model_validate(
        {
            "content": [
                {"type": "input_text", "text": "Describe uploaded image and file"},
                {"type": "file", "uri": "exchange://opaque", "kind": "image"},
            ],
            "attachments": [{"uri": "exchange://opaque", "media_type": "image/png"}],
            "sender_user_id": None,
        }
    )
    assert _content_text(payload.content) == "Describe uploaded image and file"
    assert payload.attachments == [
        {"uri": "exchange://opaque", "media_type": "image/png"}
    ]
    assert payload.model_extra == {"sender_user_id": None}


def test_history_selection_uses_typed_identity_and_preserves_output_shape() -> None:
    page = decode_history_page(
        {
            "items": [
                {
                    "id": "event-1",
                    "external_id": "message-1",
                    "session_id": "session-1",
                    "kind": "user_message",
                    "schema_version": "1",
                    "created_at": "2026-10-13T00:00:00Z",
                    "payload": {"content": "uploaded", "attachments": []},
                }
            ],
            "has_more": False,
        }
    )
    assert _message_with_content(page, "uploaded") == {
        "id": "message-1",
        "content": "uploaded",
        "attachments": [],
    }
    with pytest.raises(AssertionError, match="message content not found"):
        _message_with_content(page, "unobserved")


def test_nontext_parts_and_structured_assistant_preserve_nonmatching_behavior() -> None:
    payload = _MessagePayload.model_validate(
        {"content": [{"type": "output_text", "text": "structured assistant"}]}
    )
    assert _content_text(payload.content) == ""
    assert (
        _content_text(_MessagePayload.model_validate({"content": "assistant"}).content)
        == "assistant"
    )


@pytest.mark.parametrize(
    "content", [None, True, 3, {}, [True], [{"type": "input_text", "text": 3}]]
)
def test_invalid_message_content_is_not_an_empty_success_placeholder(
    content: object,
) -> None:
    with pytest.raises(ValidationError):
        _MessagePayload.model_validate({"content": content})
