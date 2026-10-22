"""Provider diagnostics survive the actual SDK-to-model tool boundary."""

import json

import httpx
import pytest

from azents.core.google_policy import GoogleService
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.google_files_test import _bridge
from azents.engine.tools.google_operations_test import _workspace_toolkit
from azents.engine.tools.google_test import _sdk, _turn
from azents.services.google_workspace.gmail_models import GmailSearchInput
from azents.services.google_workspace.transport_test import _Stream


async def test_model_receives_original_google_reason_message_status() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            403,
            headers={"content-type": "application/json"},
            stream=_Stream(
                (
                    json.dumps(
                        {
                            "error": {
                                "status": "PERMISSION_DENIED",
                                "message": (
                                    "Gmail API disabled for project 123456789; "
                                    "enable at "
                                    "https://console.cloud.google.com/apis/library/"
                                    "gmail.googleapis.com?project=123456789. "
                                    "Authorization: Bearer private-token; "
                                    'client_secret="credential,tail"; '
                                    'password="two words"; '
                                    'refresh_token="fixture&suffix"'
                                ),
                                "errors": [{"reason": "accessNotConfigured"}],
                            }
                        }
                    ).encode(),
                )
            ),
        )

    toolkit = _workspace_toolkit(
        GoogleService.GMAIL, "gmail.readonly", _sdk(handler), _bridge()
    )
    tool = next(
        item
        for item in (await toolkit.update_context(_turn())).tools
        if item.spec.name == "gmail_search_messages"
    )
    value = GmailSearchInput(
        query="", page_token=None, page_size=1, include_spam_trash=False, label_ids=[]
    )
    with pytest.raises(FunctionToolError) as caught:
        await tool.handler(value.model_dump_json())
    text = str(caught.value)
    assert "accessNotConfigured" in text and "HTTP 403" in text
    assert "Gmail API disabled for project 123456789" in text
    assert (
        "https://console.cloud.google.com/apis/library/gmail.googleapis.com?project=123456789"
        in text
    )
    assert "private-token" in text
    for secret in ("credential", "tail", "two words", "fixture", "suffix"):
        assert secret in text
        assert secret in json.dumps(caught.value.metadata)
    assert len(requests) == 1
    assert "private-token" in json.dumps(caught.value.metadata)
