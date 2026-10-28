"""Closed, request-local provider arguments from the protected credential union."""

import platform
import re
from dataclasses import dataclass
from typing import Required, TypedDict, assert_never

import jwt
from azents_llm_contract.authority import (
    ApiKeyCredential,
    BedrockCredential,
    ChatGPTCredential,
    KimiCredential,
    TargetBinding,
    VertexCredential,
    XaiCredential,
)
from litellm.litellm_core_utils.aws_partition import get_aws_dns_suffix
from litellm.llms.vertex_ai.common_utils import get_gemini_url
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError


class ProviderConfigurationError(Exception):
    """A trusted integration cannot be safely prepared; not an Agent auth error."""


class _ChatGPTClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    auth: dict[str, JsonValue] = Field(alias="https://api.openai.com/auth", repr=False)


def _require_chatgpt_call_token(token: str) -> None:
    # This is only a shape check, never authentication or signature authority.
    # The pinned SDK recognizes this marker to take its request-credential path;
    # without it, even a supplied key causes a local account-file lookup.
    try:
        _ChatGPTClaims.model_validate(
            jwt.decode(token, options={"verify_signature": False})
        )
    except jwt.InvalidTokenError, ValidationError:
        raise ProviderConfigurationError(
            "Provider call credential format is unavailable."
        ) from None


class ProviderArguments(TypedDict, total=False):
    """Only this SDK egress boundary unwraps protected credential strings."""

    model: Required[str]
    api_key: str
    api_base: Required[str]
    extra_headers: dict[str, str]
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region_name: str
    aws_bedrock_runtime_endpoint: str
    aws_role_name: str
    aws_session_name: str
    vertex_credentials: str
    vertex_project: str
    vertex_location: str


@dataclass(frozen=True, repr=False)
class ProviderInvocation:
    arguments: ProviderArguments
    public_model: str


def uses_chat_bridge(binding: TargetBinding) -> bool:
    """Match the pinned Proxy's native Responses versus generic bridge routes."""
    match binding.configuration.protocol:
        case "native_responses" | "responses":
            return False
        case "chat" | "anthropic" | "google" | "bedrock":
            return True
        case _ as unreachable:
            assert_never(unreachable)


def _ascii_header(value: str) -> str:
    return value.encode("ascii", errors="ignore").decode("ascii").strip() or "unknown"


def provider_invocation(binding: TargetBinding) -> ProviderInvocation:
    """Never concatenate client SDK kwargs or use an ambient provider account."""
    model = binding.model_identifier
    credential = binding.credential
    arguments: ProviderArguments
    match credential:
        case ApiKeyCredential(provider=provider, api_key=key):
            match provider:
                case "openai":
                    prefix, base = "openai", "https://api.openai.com/v1"
                case "anthropic":
                    prefix, base = "anthropic", "https://api.anthropic.com"
                case "google_gemini":
                    native_url, _ = get_gemini_url(
                        mode="chat", model=model, stream=False
                    )
                    prefix, base = "gemini", native_url.partition("/models/")[0]
                case "xai":
                    prefix, base = "xai", "https://api.x.ai/v1"
                case "openrouter":
                    prefix, base = "openrouter", "https://openrouter.ai/api/v1"
                case _:
                    assert_never(provider)
            arguments = {
                "model": f"{prefix}/{model}",
                "api_key": key.get_secret_value(),
                "api_base": base,
            }
            if provider == "openrouter":
                arguments["extra_headers"] = {"X-OpenRouter-Title": "Azents"}
        case ChatGPTCredential(access_token=token, account_id=account):
            _require_chatgpt_call_token(token.get_secret_value())
            headers = {
                "Authorization": f"Bearer {token.get_secret_value()}",
                "originator": "azents",
                "user-agent": "azents/0.1.0",
            }
            if account is not None:
                headers["ChatGPT-Account-Id"] = account
            arguments = {
                "model": f"chatgpt/{model}",
                "api_key": token.get_secret_value(),
                "api_base": "https://chatgpt.com/backend-api/codex",
                "extra_headers": headers,
            }
        case XaiCredential(access_token=token):
            arguments = {
                "model": f"xai/{model}",
                "api_key": token.get_secret_value(),
                "api_base": "https://api.x.ai/v1",
            }
        case KimiCredential(access_token=token, device_id=device):
            arguments = {
                "model": f"moonshot/{model}",
                "api_key": token.get_secret_value(),
                "api_base": "https://api.kimi.com/coding/v1",
                "extra_headers": {
                    "X-Msh-Platform": "kimi_cli",
                    "X-Msh-Version": "1.49.0",
                    "X-Msh-Device-Name": "Azents",
                    "X-Msh-Device-Model": "Azents Server",
                    "X-Msh-Os-Version": _ascii_header(
                        f"{platform.system()} {platform.release()}"
                    ),
                    "X-Msh-Device-Id": _ascii_header(device.get_secret_value()),
                },
            }
        case BedrockCredential():
            if re.fullmatch(r"[a-z0-9-]+", credential.region) is None:
                raise ProviderConfigurationError(
                    "Provider region configuration is invalid."
                )
            base = f"https://bedrock-runtime.{credential.region}.{get_aws_dns_suffix(credential.region)}"
            arguments = {
                "model": f"bedrock/{model}",
                "aws_access_key_id": credential.access_key_id.get_secret_value(),
                "aws_secret_access_key": (
                    credential.secret_access_key.get_secret_value()
                ),
                "aws_region_name": credential.region,
                "api_base": base,
                "aws_bedrock_runtime_endpoint": base,
            }
            if credential.role_arn is not None:
                arguments["aws_role_name"] = credential.role_arn
            if credential.role_session_name is not None:
                arguments["aws_session_name"] = credential.role_session_name
        case VertexCredential():
            if re.fullmatch(r"[a-z0-9-]+", credential.location) is None:
                raise ProviderConfigurationError(
                    "Provider location configuration is invalid."
                )
            host = (
                "aiplatform.googleapis.com"
                if credential.location == "global"
                else f"{credential.location}-aiplatform.googleapis.com"
            )
            arguments = {
                "model": f"vertex_ai/{model}",
                "api_base": f"https://{host}",
                "vertex_credentials": (
                    credential.service_account_json.get_secret_value()
                ),
                "vertex_project": credential.project_id,
                "vertex_location": credential.location,
            }
        case _:
            assert_never(credential)
    return ProviderInvocation(arguments=arguments, public_model=binding.public_model)
