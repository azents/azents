"""Cloud/subscription SDK egress with synthetic credentials and no real network."""

import json

import httpx
import httpx2
import pytest
from azents_llm_contract.authority import KimiCredential
from pydantic import SecretStr

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, SERVICE, binding
from azents_llm_proxy.proxy_test import setup_proxy

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


async def test_kimi_uses_exact_request_client_and_preserves_device_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "kimi-for-coding"
    original = binding()
    selected = original.model_copy(
        update={
            "public_model": model,
            "model_identifier": model,
            "credential": KimiCredential(
                kind="kimi_oauth",
                access_token=SecretStr("kimi-call-sentinel"),
                device_id=SecretStr("synthetic-device"),
            ),
            "configuration": original.configuration.model_copy(
                update={"protocol": "chat"}
            ),
        }
    )
    calls: list[httpx2.Request] = []

    def upstream(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl_synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "reply"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
            },
        )

    def controlled_transport(**kwargs: object) -> httpx2.AsyncBaseTransport:
        return httpx2.MockTransport(upstream)

    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", controlled_transport)

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://proxy"
        ) as client:
            response = await client.post(
                "/v1/responses",
                headers={"Authorization": f"Bearer {AGENT}"},
                json={
                    "model": model,
                    "input": "synthetic-prompt",
                    "metadata": {"azents_target_id": selected.target_id},
                },
            )
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    sent = calls[0]
    assert str(sent.url) == "https://api.kimi.com/coding/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer kimi-call-sentinel"
    assert sent.headers["x-msh-device-id"] == "synthetic-device"
    assert json.loads(sent.content)["model"] == model
    assert response.json()["usage"]["total_tokens"] == 3
    assert bootstrap.context.current.get() is None
