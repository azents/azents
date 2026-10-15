"""Browser fixture consumes actual tool-output dialects without guessed paths."""

import json
from typing import NamedTuple

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


class _ObservedCall(NamedTuple):
    call_id: str
    name: str
    arguments: dict[str, object]


class _DispatchHandler(proxy._Handler):
    def __init__(self) -> None:
        self.path = "/v1/responses"
        self.call: _ObservedCall | None = None

    def _write_function_call_response(
        self,
        request: proxy._ModelRequestInput,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
    ) -> None:
        self.call = _ObservedCall(call_id, name, arguments)


def _open_request(page: dict[str, object]) -> proxy._ModelRequest:
    return proxy._decode_model_request(
        {
            "input": [
                {"role": "user", "content": proxy._BROWSER_FILES_PROMPT},
                {
                    "type": "function_call_output",
                    "call_id": "call_browser_files_open",
                    "output": json.dumps({"tasks": [], "page": page}),
                },
            ]
        }
    )


@pytest.mark.parametrize("field", ["task_id", "id", "resource_incarnation"])
@pytest.mark.parametrize("value", [None, 123, False, [], {}])
def test_dispatch_rejects_malformed_browser_identity_before_emitting_capture(
    field: str, value: object
) -> None:
    page: dict[str, object] = {
        "task_id": "task",
        "id": "page",
        "resource_incarnation": "incarnation",
    }
    page[field] = value
    request = _open_request(page)
    handler = _DispatchHandler()
    original = list(proxy._State.browser_files_requests)
    try:
        with pytest.raises(ValueError, match="page identity"):
            handler._dispatch_model_request(request, b"")
        assert handler.call is None
    finally:
        proxy._State.browser_files_requests[:] = original


def test_decoded_dispatch_does_not_rehydrate_provider_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _open_request(
        {
            "task_id": "task",
            "id": "page",
            "resource_incarnation": "incarnation",
            "extension": {"opaque": [None, True]},
        }
    )

    def reject_rehydration(*args: object, **kwargs: object) -> object:
        raise AssertionError("Already-decoded provider wire must stay opaque")

    handler = _DispatchHandler()
    original = list(proxy._State.browser_files_requests)
    monkeypatch.setattr(proxy.json, "loads", reject_rehydration)
    try:
        handler._dispatch_model_request(request, b"")
        assert handler.call == _ObservedCall(
            "call_browser_files_capture",
            "browser_observe",
            {
                "task_id": "task",
                "page_id": "page",
                "resource_incarnation": "incarnation",
                "view": "image",
            },
        )
    finally:
        proxy._State.browser_files_requests[:] = original


@pytest.mark.parametrize(
    "content, flags",
    [
        ([{"type": "input_image", "image_url": "data:image/png;base64,eA=="}], (True,)),
        (
            [{"type": "input_image", "image_url": "https://example.invalid/image"}],
            (False,),
        ),
        ([{"type": "input_image", "image_url": None}], (False,)),
        ([{"type": "input_text", "text": "data:image/png;base64,eA=="}], ()),
        (None, ()),
    ],
)
def test_image_evidence_is_projected_at_input_ingress(
    content: object, flags: tuple[bool, ...]
) -> None:
    item = proxy._decode_model_input_item({"content": content})
    assert item.image_data_flags == flags
