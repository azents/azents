"""Remaining API-key/subscription identities use their exact admitted account."""

import json

import pytest
from azents_llm_contract.authority import ApiKeyCredential, XaiCredential
from pydantic import SecretStr

from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.proxy_test import RESULT
from azents_llm_proxy.tool_wire_test import invoke

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


async def test_xai_oauth_uses_its_access_token_on_the_native_responses_route() -> None:
    original = binding()
    value = original.model_copy(
        update={
            "credential": XaiCredential(
                kind="xai_oauth", access_token=SecretStr("xai-access-sentinel")
            ),
            "configuration": original.configuration.model_copy(
                update={"protocol": "responses"}
            ),
        }
    )
    model = "grok-4"
    observed = await invoke(
        value,
        model=model,
        endpoint="https://api.x.ai/v1/responses",
        result={**RESULT, "model": model},
        functions=False,
        controls=None,
    )
    assert observed.request.headers["authorization"] == "Bearer xai-access-sentinel"
    assert json.loads(observed.request.content)["model"] == model


async def test_openrouter_uses_exact_qualified_model_and_application_header() -> None:
    original = binding()
    value = original.model_copy(
        update={
            "credential": ApiKeyCredential(
                kind="api_key",
                provider="openrouter",
                api_key=SecretStr("openrouter-key-sentinel"),
            ),
            "configuration": original.configuration.model_copy(
                update={"protocol": "responses"}
            ),
        }
    )
    model = "openai/gpt-4o-mini"
    observed = await invoke(
        value,
        model=model,
        endpoint="https://openrouter.ai/api/v1/responses",
        result={**RESULT, "model": model},
        functions=False,
        controls=None,
    )
    assert observed.request.headers["authorization"] == "Bearer openrouter-key-sentinel"
    assert observed.request.headers["x-openrouter-title"] == "Azents"
    assert json.loads(observed.request.content)["model"] == model
    assert observed.response.json()["usage"]["total_tokens"] == 3
