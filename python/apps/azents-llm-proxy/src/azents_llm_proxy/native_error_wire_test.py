"""Native provider error events keep standard failure schema without raw errors."""

import json
import logging

import httpx
import pytest
import respx
from pydantic import SecretStr

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, SERVICE, binding
from azents_llm_proxy.observability import LOGGER
from azents_llm_proxy.proxy_test import MODEL, RESULT, payload, setup_proxy

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


@pytest.mark.parametrize("event_type", ["error", "response.failed"])
async def test_native_error_event_privacy_and_no_false_completion(
    event_type: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )
    error = {
        "code": "server_error",
        "message": "private-native-error-sentinel",
        "param": None,
    }
    failure: dict[str, object] = {"type": event_type, "sequence_number": 1}
    if event_type == "error":
        failure.update(error)
    else:
        failure["response"] = {**RESULT, "status": "failed", "error": error}
    created = {"type": "response.created", "response": RESULT}
    wire = (
        f"event: response.created\ndata: {json.dumps(created)}\n\n"
        f"event: {event_type}\ndata: {json.dumps(failure)}\n\n"
    )

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.post("https://api.openai.com/v1/responses").mock(
                return_value=httpx.Response(
                    200, text=wire, headers={"Content-Type": "text/event-stream"}
                )
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer " + AGENT},
                    json={**payload(), "stream": True},
                )
            assert upstream.call_count == 1
    assert response.status_code == 200
    assert (
        "response.failed" in response.text and "response.completed" not in response.text
    )
    captured = capsys.readouterr()
    assert (
        "private-native-error-sentinel"
        not in response.text + caplog.text + captured.out + captured.err
    )
    events = [r.__dict__ for r in caplog.records if r.name == LOGGER.name]
    assert len(events) == 1
    assert events[0]["outcome"] == "failure"
    assert events[0]["failure_classification"] == "upstream_provider"
