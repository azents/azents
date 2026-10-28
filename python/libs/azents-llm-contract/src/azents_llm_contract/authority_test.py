"""Protected channel serialization and closed ingress validation."""

import datetime
import json

import pytest
from pydantic import SecretStr, ValidationError

from azents_llm_contract.authority import (
    ApiKeyCredential,
    AuthenticatedIdentity,
    BedrockCredential,
    ChatGPTCredential,
    IssuedToken,
    KimiCredential,
    ModelListResponse,
    ProviderCredential,
    ResolveRequest,
    TargetBinding,
    VertexCredential,
    XaiCredential,
)
from azents_llm_contract.settings_test import configuration

SENTINEL = "secret-sentinel-not-for-logs"
IDENTITY = AuthenticatedIdentity(
    agent_id="agent-a",
    workspace_id="workspace-a",
    supply_id="supply-a",
    token_id="token-a",
)


def credential_cases() -> list[ProviderCredential]:
    secret = SecretStr(SENTINEL)
    return [
        ApiKeyCredential(kind="api_key", provider="openai", api_key=secret),
        ApiKeyCredential(kind="api_key", provider="anthropic", api_key=secret),
        ApiKeyCredential(kind="api_key", provider="google_gemini", api_key=secret),
        ApiKeyCredential(kind="api_key", provider="xai", api_key=secret),
        ApiKeyCredential(kind="api_key", provider="openrouter", api_key=secret),
        ChatGPTCredential(
            kind="chatgpt_oauth", access_token=secret, account_id="account"
        ),
        XaiCredential(kind="xai_oauth", access_token=secret),
        KimiCredential(kind="kimi_oauth", access_token=secret, device_id=secret),
        BedrockCredential(
            kind="aws_bedrock",
            access_key_id=secret,
            secret_access_key=secret,
            region="us-east-1",
            role_arn=None,
            role_session_name=None,
        ),
        VertexCredential(
            kind="google_vertex_ai",
            service_account_json=secret,
            project_id="project",
            location="us-central1",
        ),
    ]


@pytest.mark.parametrize("credential", credential_cases())
def test_secrets_redacted_normally_and_explicit_wire_roundtrip(
    credential: ProviderCredential,
) -> None:
    binding = TargetBinding(
        identity=IDENTITY,
        integration_id="integration-a",
        target_id="a" * 64,
        public_model="model",
        model_identifier="provider/model",
        credential=credential,
        configuration=configuration(),
    )
    for output in (
        str(binding),
        repr(binding),
        str(binding.model_dump()),
        binding.model_dump_json(),
    ):
        assert SENTINEL not in output
    wire = binding.protected_json()
    assert SENTINEL in wire
    restored = TargetBinding.model_validate_json(wire)
    assert restored == binding
    assert SENTINEL not in restored.model_dump_json()


def test_agent_token_redaction_and_explicit_transport() -> None:
    request = ResolveRequest(
        agent_token=SecretStr(SENTINEL), model="model", target_id="b" * 64
    )
    assert SENTINEL not in str(request)
    assert SENTINEL not in request.model_dump_json()
    assert json.loads(request.protected_json())["agent_token"] == SENTINEL


@pytest.mark.parametrize(
    "field", ["integration_id", "workspace_id", "api_key", "api_base", "extra_headers"]
)
def test_resolve_request_cannot_select_credential_or_claim_identity(field: str) -> None:
    payload = {
        "agent_token": SENTINEL,
        "model": "model",
        "target_id": "a" * 64,
        field: "forged",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResolveRequest.model_validate(payload)


@pytest.mark.parametrize("target", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64])
def test_target_format_is_not_arbitrary(target: str) -> None:
    with pytest.raises(ValidationError):
        ResolveRequest(agent_token=SecretStr(SENTINEL), model="model", target_id=target)


def test_unknown_credentials_and_refresh_token_are_rejected() -> None:
    base = {
        "identity": IDENTITY.model_dump(),
        "integration_id": "integration-a",
        "target_id": "a" * 64,
        "public_model": "model",
        "model_identifier": "model",
        "configuration": configuration().model_dump(),
    }
    for credential in [
        {"kind": "arbitrary_sdk_kwargs", "api_key": SENTINEL},
        {
            "kind": "chatgpt_oauth",
            "access_token": SENTINEL,
            "account_id": None,
            "refresh_token": SENTINEL,
        },
        {"kind": "api_key", "provider": "chatgpt_oauth", "api_key": SENTINEL},
    ]:
        with pytest.raises(ValidationError) as caught:
            TargetBinding.model_validate({**base, "credential": credential})
        assert SENTINEL not in str(caught.value)
        assert SENTINEL not in repr(caught.value)
        safe_errors = caught.value.errors(include_input=False, include_context=False)
        assert SENTINEL not in json.dumps(safe_errors)


def test_empty_model_list_does_not_invent_authority() -> None:
    result = ModelListResponse(identity=IDENTITY, models=())
    assert result.model_dump(mode="json")["models"] == []


def test_token_issue_response_hides_secret_except_on_protected_channel() -> None:
    token = IssuedToken(
        supply_id="supply-a",
        token_id="token-a",
        agent_token=SecretStr(SENTINEL),
        expires_at=datetime.datetime(2026, 10, 28, tzinfo=datetime.UTC),
        predecessor_expires_at=None,
    )
    assert SENTINEL not in token.model_dump_json()
    assert SENTINEL not in repr(token)
    assert SENTINEL in token.protected_json()
