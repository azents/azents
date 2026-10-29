"""Real Proxy config loader and ASGI ingress with controlled provider transport."""

import asyncio
import json

import httpx
import jwt
import litellm
import litellm.proxy.proxy_server as proxy
import pytest
import respx
from azents_llm_contract.authority import (
    ApiKeyCredential,
    ChatGPTCredential,
    ModelListResponse,
)
from litellm.llms.chatgpt.authenticator import Authenticator
from pydantic import SecretStr

from azents_llm_proxy import bootstrap
from azents_llm_proxy.application import select_direct_dispatch
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, SERVICE, binding
from azents_llm_proxy.history_test import PNG
from azents_llm_proxy.ingress import AgentIngress
from azents_llm_proxy.privacy import install_vendor_diagnostics

pytestmark = pytest.mark.usefixtures("protected_provider_clients")

MODEL = "gpt-4o-mini"
RESULT = {
    "id": "resp_offline",
    "object": "response",
    "created_at": 1,
    "status": "completed",
    "error": None,
    "incomplete_details": None,
    "instructions": None,
    "model": MODEL,
    "output": [],
    "parallel_tool_calls": True,
    "tools": [],
    "tool_choice": "auto",
    "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
}


async def setup_proxy() -> AgentIngress:
    install_vendor_diagnostics()
    # A real process loads this config once. Tests compose fresh applications
    # in the same interpreter; the SDK appends callbacks on repeated loading.
    litellm.callbacks.clear()
    await proxy.initialize(config=str(bootstrap.CONFIG), drop_params=False)
    assert sum(callback is bootstrap.boundary for callback in litellm.callbacks) == 1
    # Config loading constructs a Router even without deployments. The
    # composition root must release it and choose the approved direct path.
    assert proxy.llm_router is not None
    assert not proxy.llm_router.get_model_list()
    select_direct_dispatch()
    assert proxy.user_custom_auth is bootstrap.authenticate
    return AgentIngress(proxy.app, bootstrap.context)


def payload() -> dict[str, object]:
    return {
        "model": MODEL,
        "input": "private-prompt",
        "metadata": {"azents_target_id": "a" * 64},
    }


async def test_actual_proxy_ingress_resolves_one_request_and_dispatches_once() -> None:
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )
    authority_requests: list[httpx.Request] = []

    def authority(request: httpx.Request) -> httpx.Response:
        authority_requests.append(request)
        return httpx.Response(200, content=selected.protected_json())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.post("https://api.openai.com/v1/responses").mock(
                return_value=httpx.Response(200, json=RESULT)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {AGENT}"},
                    json=payload(),
                )
            assert response.status_code == 200, response.text
            assert upstream.call_count == 1
            assert len(authority_requests) == 1
            sent = upstream.calls[0].request
            assert sent.headers["authorization"] == "Bearer provider-sentinel"
            wire = json.loads(sent.content)
            assert wire["model"] == MODEL and wire["input"] == "private-prompt"
            assert "metadata" not in wire
            assert response.json()["usage"]["total_tokens"] == 3
            assert (
                AGENT not in response.text and "provider-sentinel" not in response.text
            )
        assert bootstrap.context.current.get() is None


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/responses"),
        ("GET", "/models"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/key/generate"),
        ("GET", "/model/info"),
        ("GET", "/docs"),
        ("POST", "/v1/responses/"),
        ("POST", "/v1/responses?api_key=secret"),
    ],
)
async def test_outer_ingress_denies_other_proxy_surfaces(
    method: str, path: str
) -> None:
    app = AgentIngress(proxy.app, bootstrap.context)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://proxy"
    ) as client:
        response = await client.request(
            method, path, headers={"Authorization": f"Bearer {AGENT}"}
        )
    assert response.status_code == 403
    assert AGENT not in response.text


async def test_actual_proxy_concurrent_a_b_a_keeps_accounts_request_local() -> None:
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )
    all_arrived = asyncio.Event()
    captured: dict[str, str] = {}

    def authority(request: httpx.Request) -> httpx.Response:
        token = json.loads(request.content)["agent_token"]
        suffix = "a" if token == "agent-a" else "b"
        scoped = selected.model_copy(
            update={
                "identity": selected.identity.model_copy(
                    update={
                        "agent_id": f"agent-{suffix}",
                        "workspace_id": f"workspace-{suffix}",
                    }
                ),
                "credential": ApiKeyCredential(
                    kind="api_key",
                    provider="openai",
                    api_key=SecretStr(f"provider-{suffix}"),
                ),
            }
        )
        return httpx.Response(200, content=scoped.protected_json())

    async def upstream(request: httpx.Request) -> httpx.Response:
        captured[json.loads(request.content)["input"]] = request.headers[
            "authorization"
        ]
        if len(captured) == 3:
            all_arrived.set()
        await all_arrived.wait()
        return httpx.Response(200, json=RESULT)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            dispatch = router.post("https://api.openai.com/v1/responses").mock(
                side_effect=upstream
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                async with asyncio.timeout(10):
                    responses = await asyncio.gather(
                        *(
                            client.post(
                                "/v1/responses",
                                headers={"Authorization": f"Bearer agent-{account}"},
                                json={**payload(), "input": content},
                            )
                            for account, content in (
                                ("a", "a-first"),
                                ("b", "b-middle"),
                                ("a", "a-last"),
                            )
                        )
                    )
            assert all(response.status_code == 200 for response in responses)
            assert dispatch.call_count == 3
    assert captured == {
        "a-first": "Bearer provider-a",
        "b-middle": "Bearer provider-b",
        "a-last": "Bearer provider-a",
    }
    assert bootstrap.context.current.get() is None


@pytest.mark.parametrize("models", [(), ("allowed-actual-model",)])
async def test_actual_standard_listing_uses_only_current_agent_names(
    models: tuple[str, ...],
) -> None:
    def authority(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/llm/models"
        return httpx.Response(
            200,
            content=ModelListResponse(
                identity=binding().identity, models=models
            ).protected_json(),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://proxy"
        ) as client:
            response = await client.get(
                "/v1/models", headers={"Authorization": f"Bearer {AGENT}"}
            )
    assert response.status_code == 200, response.text
    assert tuple(item["id"] for item in response.json()["data"]) == models


@pytest.mark.parametrize(
    "header",
    [
        "x-litellm-api-base",
        "x-litellm-user-config",
        "chatgpt-account-id",
        "openai-project",
    ],
)
async def test_actual_header_overrides_fail_before_authority(header: str) -> None:
    calls: list[httpx.Request] = []

    def authority(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

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
                headers={"Authorization": f"Bearer {AGENT}", header: "untrusted"},
                json=payload(),
            )
    assert response.status_code == 401, response.text
    assert not calls


@pytest.mark.parametrize("status", [429, 500])
async def test_actual_provider_errors_have_one_dispatch_and_safe_diagnostics(
    status: int,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )
    sentinel = "sensitive-upstream-error-body"

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    install_vendor_diagnostics()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.post("https://api.openai.com/v1/responses").mock(
                return_value=httpx.Response(
                    status,
                    json={
                        "error": {
                            "message": f"{sentinel} provider-sentinel private-prompt",
                            "type": "server_error",
                        }
                    },
                )
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {AGENT}"},
                    json=payload(),
                )
            assert response.status_code == status, response.text
            assert upstream.call_count == 1
            assert response.json()["error"]["param"] == "upstream_provider"
    captured = capsys.readouterr()
    for secret in (sentinel, "provider-sentinel", "private-prompt", AGENT, SERVICE):
        assert secret not in response.text
        assert secret not in caplog.text
        assert secret not in captured.out + captured.err


@pytest.mark.parametrize("stream", [False, True])
async def test_chatgpt_native_corrections_preserve_cache_tier_and_never_load_file_auth(
    stream: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_auth(*args: object, **kwargs: object) -> None:
        raise AssertionError("Ambient ChatGPT authentication must not be used.")

    monkeypatch.setattr(Authenticator, "get_access_token", forbidden_auth)
    monkeypatch.setattr(Authenticator, "get_account_id", forbidden_auth)
    token = jwt.encode(
        {"https://api.openai.com/auth": {"chatgpt_account_id": "synthetic"}},
        "",
        algorithm="none",
    )
    selected = binding().model_copy(
        update={
            "public_model": MODEL,
            "model_identifier": MODEL,
            "credential": ChatGPTCredential(
                kind="chatgpt_oauth",
                access_token=SecretStr(token),
                account_id="synthetic-account",
            ),
            "configuration": binding().configuration.model_copy(
                update={
                    "supported_execution_options": ("fast", "ultrafast"),
                }
            ),
        }
    )

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    completed = {"type": "response.completed", "response": RESULT}
    sse = (
        f"event: response.completed\ndata: {json.dumps(completed)}\n\ndata: [DONE]\n\n"
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.post(
                "https://chatgpt.com/backend-api/codex/responses"
            ).mock(
                return_value=httpx.Response(
                    200, text=sse, headers={"Content-Type": "text/event-stream"}
                )
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {AGENT}"},
                    json={
                        **payload(),
                        "stream": stream,
                        "prompt_cache_key": "approved-cache-key",
                        "service_tier": "ultrafast",
                    },
                )
            assert response.status_code == 200, response.text
            assert upstream.call_count == 1
            sent = upstream.calls[0].request
            assert sent.headers["authorization"] == f"Bearer {token}"
            assert sent.headers["ChatGPT-Account-Id"] == "synthetic-account"
            wire = json.loads(sent.content)
            assert wire["prompt_cache_key"] == "approved-cache-key"
            assert wire["service_tier"] == "ultrafast"
            assert wire["store"] is False
            assert token not in response.text and AGENT not in response.text


@pytest.mark.parametrize("image_history", [False, True])
async def test_anthropic_generic_bridge_retains_account_cap_and_usage(
    image_history: bool,
) -> None:
    model = "claude-sonnet-4-5"
    selected = binding().model_copy(
        update={
            "public_model": model,
            "model_identifier": model,
            "credential": ApiKeyCredential(
                kind="api_key",
                provider="anthropic",
                api_key=SecretStr("provider-sentinel"),
            ),
            "configuration": binding().configuration.model_copy(
                update={
                    "max_output_tokens": 100,
                    "protocol": "anthropic",
                    "supported_features": (
                        "input:text",
                        "input:image",
                        "max_output_tokens",
                    ),
                }
            ),
        }
    )

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    result = {
        "id": "msg_offline",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "reply"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 2, "output_tokens": 1},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(200, json=result)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                invocation = {**payload(), "model": model}
                if image_history:
                    invocation["input"] = [
                        {
                            "type": "image_generation_call",
                            "id": "ig_synthetic",
                            "status": "completed",
                            "result": PNG,
                        },
                        {"role": "user", "content": "describe previous image"},
                    ]
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {AGENT}"},
                    json=invocation,
                )
            assert response.status_code == 200, response.text
            assert upstream.call_count == 1
            wire = json.loads(upstream.calls[0].request.content)
            assert wire["model"] == model and wire["max_tokens"] == 100
            if image_history:
                assert PNG in json.dumps(wire["messages"])
                assert "image/png" in json.dumps(wire["messages"])
                assert "image_generation completed" in json.dumps(wire["messages"])
            assert upstream.calls[0].request.headers["x-api-key"] == "provider-sentinel"
            assert response.json()["usage"]["total_tokens"] == 3
            assert response.json()["model"] == model
