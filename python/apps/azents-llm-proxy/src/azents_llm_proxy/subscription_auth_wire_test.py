"""Published-dev ChatGPT forwarding stays request-local across shared callbacks."""

import asyncio
import json

import httpx
import jwt
import pytest
import respx
from azents_llm_contract.authority import ChatGPTCredential
from litellm.llms.chatgpt.authenticator import Authenticator
from pydantic import SecretStr

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import SERVICE, binding
from azents_llm_proxy.proxy_test import RESULT, payload, setup_proxy

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


async def test_chatgpt_concurrent_account_and_token_pairs_never_use_file_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "gpt-5.5"
    credentials = {
        suffix: jwt.encode(
            {
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "account-" + suffix
                }
            },
            "",
            algorithm="none",
        )
        for suffix in ("a", "b")
    }
    arrived = asyncio.Event()
    captured: dict[str, tuple[str, str]] = {}

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Local ChatGPT authentication was reached.")

    monkeypatch.setattr(Authenticator, "get_access_token", forbidden)
    monkeypatch.setattr(Authenticator, "get_account_id", forbidden)

    def authority(request: httpx.Request) -> httpx.Response:
        suffix = json.loads(request.content)["agent_token"][-1]
        original = binding()
        selected = original.model_copy(
            update={
                "public_model": model,
                "model_identifier": model,
                "identity": original.identity.model_copy(
                    update={
                        "agent_id": "agent-" + suffix,
                        "workspace_id": "workspace-" + suffix,
                    }
                ),
                "credential": ChatGPTCredential(
                    kind="chatgpt_oauth",
                    access_token=SecretStr(credentials[suffix]),
                    account_id="account-" + suffix,
                ),
            }
        )
        return httpx.Response(200, content=selected.protected_json())

    async def provider(request: httpx.Request) -> httpx.Response:
        content = json.dumps(json.loads(request.content)["input"])
        labels = [
            label for label in ("a-first", "b-middle", "a-last") if label in content
        ]
        assert len(labels) == 1
        captured[labels[0]] = (
            request.headers["authorization"],
            request.headers["ChatGPT-Account-Id"],
        )
        if len(captured) == 3:
            arrived.set()
        await arrived.wait()
        event = {"type": "response.completed", "response": {**RESULT, "model": model}}
        return httpx.Response(
            200,
            text=f"event: response.completed\ndata: {json.dumps(event)}\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            route = router.post("https://chatgpt.com/backend-api/codex/responses").mock(
                side_effect=provider
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                async with asyncio.timeout(10):
                    responses = await asyncio.gather(
                        *(
                            client.post(
                                "/v1/responses",
                                headers={"Authorization": "Bearer agent-" + suffix},
                                json={**payload(), "model": model, "input": label},
                            )
                            for suffix, label in [
                                ("a", "a-first"),
                                ("b", "b-middle"),
                                ("a", "a-last"),
                            ]
                        )
                    )
            assert all(response.status_code == 200 for response in responses)
            assert route.call_count == 3
    assert captured == {
        label: ("Bearer " + credentials[suffix], "account-" + suffix)
        for suffix, label in [("a", "a-first"), ("b", "b-middle"), ("a", "a-last")]
    }
    assert bootstrap.context.current.get() is None
