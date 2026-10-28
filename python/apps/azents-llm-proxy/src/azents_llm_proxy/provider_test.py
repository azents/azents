"""All provider identities receive closed request-local credentials and endpoints."""

import json
from dataclasses import replace

import jwt
import pytest
from azents_llm_contract.authority import (
    ApiKeyCredential,
    BedrockCredential,
    ChatGPTCredential,
    KimiCredential,
    ProviderCredential,
    VertexCredential,
    XaiCredential,
)
from pydantic import SecretStr

from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.provider import ProviderConfigurationError, provider_invocation

SECRET = SecretStr("provider-call-sentinel")
CHATGPT_SECRET = SecretStr(
    jwt.encode(
        {"https://api.openai.com/auth": {"chatgpt_account_id": "synthetic"}},
        "",
        algorithm="none",
    )
)


def vertex(location: str) -> VertexCredential:
    return VertexCredential(
        kind="google_vertex_ai",
        location=location,
        project_id="project",
        service_account_json=SecretStr(
            json.dumps(
                {
                    "type": "service_account",
                    "private_key": "key-sentinel",
                    "client_email": "test@example.iam.gserviceaccount.com",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )
        ),
    )


def bedrock(region: str) -> BedrockCredential:
    return BedrockCredential(
        kind="aws_bedrock",
        access_key_id=SECRET,
        secret_access_key=SECRET,
        region=region,
        role_arn=None,
        role_session_name=None,
    )


@pytest.mark.parametrize(
    "credential,prefix,base",
    [
        (
            ApiKeyCredential(kind="api_key", provider="openai", api_key=SECRET),
            "openai",
            "https://api.openai.com/v1",
        ),
        (
            ApiKeyCredential(kind="api_key", provider="anthropic", api_key=SECRET),
            "anthropic",
            "https://api.anthropic.com",
        ),
        (
            ApiKeyCredential(kind="api_key", provider="google_gemini", api_key=SECRET),
            "gemini",
            "https://generativelanguage.googleapis.com/v1alpha",
        ),
        (
            ApiKeyCredential(kind="api_key", provider="xai", api_key=SECRET),
            "xai",
            "https://api.x.ai/v1",
        ),
        (
            ApiKeyCredential(kind="api_key", provider="openrouter", api_key=SECRET),
            "openrouter",
            "https://openrouter.ai/api/v1",
        ),
        (
            ChatGPTCredential(
                kind="chatgpt_oauth", access_token=CHATGPT_SECRET, account_id="account"
            ),
            "chatgpt",
            "https://chatgpt.com/backend-api/codex",
        ),
        (
            XaiCredential(kind="xai_oauth", access_token=SECRET),
            "xai",
            "https://api.x.ai/v1",
        ),
        (
            KimiCredential(
                kind="kimi_oauth", access_token=SECRET, device_id=SecretStr("device")
            ),
            "moonshot",
            "https://api.kimi.com/coding/v1",
        ),
        (
            bedrock("us-east-1"),
            "bedrock",
            "https://bedrock-runtime.us-east-1.amazonaws.com",
        ),
        (
            vertex("us-central1"),
            "vertex_ai",
            "https://us-central1-aiplatform.googleapis.com",
        ),
    ],
)
def test_exhaustive_provider_account_and_endpoint_shapes(
    credential: ProviderCredential,
    prefix: str,
    base: str,
) -> None:
    selected = binding().model_copy(update={"credential": credential})
    invocation = provider_invocation(selected)
    assert invocation.arguments["model"] == f"{prefix}/model"
    assert invocation.arguments["api_base"] == base
    assert invocation.public_model == "model"
    assert "provider-call-sentinel" not in repr(invocation)
    assert "key-sentinel" not in repr(invocation)
    assert replace(invocation, public_model="public").public_model == "public"


@pytest.mark.parametrize(
    "credential", [bedrock("evil.invalid/path"), vertex("bad/path")]
)
def test_cloud_location_cannot_select_an_endpoint(
    credential: ProviderCredential,
) -> None:
    with pytest.raises(ProviderConfigurationError):
        provider_invocation(binding().model_copy(update={"credential": credential}))


def test_vertex_global_and_bedrock_china_endpoints() -> None:
    selected = binding()
    assert (
        provider_invocation(
            selected.model_copy(update={"credential": vertex("global")})
        ).arguments["api_base"]
        == "https://aiplatform.googleapis.com"
    )
    assert (
        provider_invocation(
            selected.model_copy(update={"credential": bedrock("cn-north-1")})
        ).arguments["api_base"]
        == "https://bedrock-runtime.cn-north-1.amazonaws.com.cn"
    )


def test_subscription_account_headers_are_call_local() -> None:
    selected = binding()
    first = provider_invocation(
        selected.model_copy(
            update={
                "credential": ChatGPTCredential(
                    kind="chatgpt_oauth",
                    access_token=CHATGPT_SECRET,
                    account_id="first",
                )
            }
        )
    )
    second = provider_invocation(
        selected.model_copy(
            update={
                "credential": ChatGPTCredential(
                    kind="chatgpt_oauth",
                    access_token=SecretStr(
                        jwt.encode(
                            {
                                "https://api.openai.com/auth": {
                                    "chatgpt_account_id": "second"
                                }
                            },
                            "",
                            algorithm="none",
                        )
                    ),
                    account_id="second",
                )
            }
        )
    )
    assert first.arguments["extra_headers"]["ChatGPT-Account-Id"] == "first"
    assert second.arguments["extra_headers"]["ChatGPT-Account-Id"] == "second"
    assert (
        first.arguments["extra_headers"]["Authorization"]
        != second.arguments["extra_headers"]["Authorization"]
    )


@pytest.mark.parametrize(
    "token",
    ["not-a-jwt", jwt.encode({"sub": "wrong-issuer-shape"}, "", algorithm="none")],
)
def test_chatgpt_credential_cannot_enter_local_file_fallback(token: str) -> None:
    selected = binding().model_copy(
        update={
            "credential": ChatGPTCredential(
                kind="chatgpt_oauth",
                access_token=SecretStr(token),
                account_id="account",
            )
        }
    )
    with pytest.raises(ProviderConfigurationError):
        provider_invocation(selected)
