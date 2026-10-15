"""Browser fixture consumes actual tool-output dialects without guessed paths."""

import json

import pytest

from support import image_generation_openai_proxy as proxy


@pytest.mark.parametrize("structured_output", [False, True])
def test_capture_fixture_decodes_text_and_multimodal_tool_output(
    structured_output: bool,
) -> None:
    result = {
        "tasks": [],
        "capture": {"path": "/current/session/browser-files/original.png"},
    }
    output: object = json.dumps(result)
    if structured_output:
        output = [
            {"type": "input_text", "text": json.dumps(result)},
            {
                "type": "input_image",
                "image_url": "data:image/jpeg;base64,c3ludGhldGlj",
            },
        ]
    request = proxy._decode_model_request(
        {
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_browser_files_capture",
                    "output": output,
                },
            ],
        }
    )
    assert proxy._browser_capture_path(request) == result["capture"]["path"]


def test_capture_fixture_rejects_a_relative_returned_path() -> None:
    request = proxy._decode_model_request(
        {
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_browser_files_capture",
                    "output": json.dumps(
                        {"tasks": [], "capture": {"path": "relative.png"}}
                    ),
                }
            ],
        }
    )
    with pytest.raises(ValueError, match="capture path"):
        proxy._browser_capture_path(request)


def test_browser_journal_clear_excludes_an_older_positive_image_witness() -> None:
    class JournalDelete(proxy._Handler):
        def __init__(self) -> None:
            self.path = "/v1/_browser_files_requests"
            self.response_status: int | None = None
            self.response_body: object = None

        def _write_json(self, status: int, value: object) -> None:
            self.response_status = status
            self.response_body = value

    original = list(proxy._State.browser_files_requests)
    try:
        proxy._State.browser_files_requests[:] = [
            {
                "model": "fixture",
                "completed_calls": ["call_browser_files_capture"],
                "model_image_count": 1,
                "model_images_are_data": True,
            }
        ]
        handler = JournalDelete()
        handler.do_DELETE()
        assert handler.response_status == 200
        assert handler.response_body == {"cleared": True}
        assert proxy._State.browser_files_requests == []
        current: dict[str, object] = {
            "model": "fixture",
            "completed_calls": ["call_browser_files_capture"],
            "model_image_count": 0,
            "model_images_are_data": True,
        }
        proxy._State.browser_files_requests.append(current)
        assert proxy._State.browser_files_requests == [current]
        assert not any(
            row["model_image_count"] for row in proxy._State.browser_files_requests
        )
    finally:
        proxy._State.browser_files_requests[:] = original
