"""Real Proxy callbacks keep verified operational fields, not vendor content."""

import asyncio
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
