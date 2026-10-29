"""Real Proxy callbacks keep verified operational fields, not vendor content."""

import asyncio
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


@pytest.mark.parametrize("failure", [False, True])
async def test_builtin_events_preserve_allowlisted_verified_fields(
    failure: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )
    emitted = asyncio.Event()

    class Observer(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            emitted.set()

    observer = Observer()
    LOGGER.addHandler(observer)
    caplog.set_level(logging.INFO, logger=LOGGER.name)

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(authority),
            base_url="https://authority/internal/llm/",
        ) as authority_http:
            bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
            app = await setup_proxy()
            with respx.mock(assert_all_called=False) as router:
                upstream = router.post("https://api.openai.com/v1/responses").mock(
                    return_value=httpx.Response(
                        500,
                        json={
                            "error": {
                                "message": "private-provider-error",
                                "type": "server_error",
                            }
                        },
                    )
                    if failure
                    else httpx.Response(200, json=RESULT)
                )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="https://proxy"
                ) as client:
                    response = await client.post(
                        "/v1/responses",
                        headers={"Authorization": "Bearer " + AGENT},
                        json=payload(),
                    )
                assert response.status_code == (500 if failure else 200)
                assert upstream.call_count == 1
                async with asyncio.timeout(5):
                    await emitted.wait()
    finally:
        LOGGER.removeHandler(observer)
    records = [r for r in caplog.records if r.name == LOGGER.name]
    assert len(records) == 1
    event = records[0].__dict__
    assert event["agent_id"] == selected.identity.agent_id
    assert event["workspace_id"] == selected.identity.workspace_id
    assert event["integration_id"] == selected.integration_id
    assert event["model"] == MODEL
    assert event["outcome"] == ("failure" if failure else "success")
    assert event["latency_ms"] >= 0 and len(event["request_id"]) == 32
    assert event["total_tokens"] == (None if failure else 3)
    assert event["failure_classification"] == ("upstream_provider" if failure else None)
    for sentinel in [AGENT, SERVICE, "private-prompt", "private-provider-error"]:
        assert sentinel not in repr(event) + caplog.text


@pytest.mark.parametrize("stream", [False, True])
async def test_incomplete_terminal_is_not_accounting_success(
    stream: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )
    incomplete = {
        **RESULT,
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    terminal = {"type": "response.incomplete", "response": incomplete}

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
                    200,
                    text=(
                        f"event: response.incomplete\ndata: {json.dumps(terminal)}\n\n"
                    ),
                    headers={"Content-Type": "text/event-stream"},
                )
                if stream
                else httpx.Response(200, json=incomplete)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer " + AGENT},
                    json={**payload(), "stream": stream},
                )
            assert response.status_code == 200
            assert upstream.call_count == 1
    events = [r.__dict__ for r in caplog.records if r.name == LOGGER.name]
    assert len(events) == 1
    assert events[0]["outcome"] == "incomplete"
    assert events[0]["input_tokens"] == 2
    assert events[0]["output_tokens"] == 1
    assert events[0]["total_tokens"] == 3


async def test_preparation_rejection_is_not_upstream_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
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
            upstream = router.post("https://api.openai.com/v1/responses")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer " + AGENT},
                    json={**payload(), "reasoning_effort": "high"},
                )
            assert response.status_code == 400
            assert upstream.call_count == 0
    events = [r.__dict__ for r in caplog.records if r.name == LOGGER.name]
    assert len(events) == 1
    assert events[0]["outcome"] == "failure"
    assert events[0]["failure_classification"] == "preparation"
    assert events[0]["total_tokens"] is None
