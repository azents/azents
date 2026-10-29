"""Server-prepared Bedrock sessions reach the real Proxy/SDK SigV4 boundary."""

import datetime

import httpx
import pytest
import respx
from azents_llm_contract.authority import BedrockCredential
from litellm.llms.bedrock.base_aws_llm import BaseAWSLLM
from pydantic import SecretStr

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, SERVICE, binding
from azents_llm_proxy.proxy_test import setup_proxy

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


@pytest.mark.parametrize("expired", [False, True])
async def test_explicit_session_signing_without_role_or_ambient_lookup(
    expired: bool,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = "amazon.nova-lite-v1:0"
    original = binding()
    selected = original.model_copy(
        update={
            "public_model": model,
            "model_identifier": model,
            "configuration": original.configuration.model_copy(
                update={"protocol": "bedrock"}
            ),
            "credential": BedrockCredential(
                kind="aws_bedrock",
                access_key_id=SecretStr("ASIA" + "A" * 16),
                secret_access_key=SecretStr("A" * 40),
                session_token=SecretStr("bedrock-session-sentinel"),
                region="us-west-2",
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(minutes=-1 if expired else 15),
            ),
        }
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Unexpected ambient/role credential branch.")

    # Failure-only traps leave the genuine session-token signer unchanged.
    monkeypatch.setattr(BaseAWSLLM, "_auth_with_env_vars", forbidden)
    monkeypatch.setattr(BaseAWSLLM, "_get_or_set_cached_credentials", forbidden)
    monkeypatch.setattr("boto3.client", forbidden)

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    def provider(request: httpx.Request) -> httpx.Response:
        assert "Credential=ASIA" + "A" * 16 + "/" in request.headers["authorization"]
        assert request.headers["x-amz-security-token"] == "bedrock-session-sentinel"
        return httpx.Response(
            200,
            json={
                "output": {
                    "message": {"role": "assistant", "content": [{"text": "reply"}]}
                },
                "stopReason": "end_turn",
                "usage": {"inputTokens": 2, "outputTokens": 1, "totalTokens": 3},
                "metrics": {"latencyMs": 1},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.route(
                method="POST", host="bedrock-runtime.us-west-2.amazonaws.com"
            ).mock(side_effect=provider)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer " + AGENT},
                    json={
                        "model": model,
                        "input": "bedrock-private-prompt",
                        "metadata": {"azents_target_id": "a" * 64},
                    },
                )
            assert upstream.call_count == (0 if expired else 1)
    assert response.status_code == (503 if expired else 200), response.text
    for sentinel in ["bedrock-session-sentinel", "bedrock-private-prompt", "A" * 40]:
        assert sentinel not in response.text + caplog.text
    assert bootstrap.context.current.get() is None
