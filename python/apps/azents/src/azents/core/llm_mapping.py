"""LiteLLM mapping by LLM provider.

Converts provider + model identifiers to LiteLLM model strings and converts
credentials to LiteLLM kwargs format.
"""

from typing import cast

from azents.core.chatgpt_oauth import (
    CHATGPT_OAUTH_BACKEND_BASE_URL,
    build_chatgpt_oauth_headers,
)
from azents.core.credentials import (
    ApiKeySecrets,
    AwsConfig,
    AwsSecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    GcpConfig,
    GcpSecrets,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider
from azents.core.xai import resolve_xai_api_base_url
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)

# Provider to LiteLLM model string prefix mapping
PROVIDER_LITELLM_PREFIX: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "openai/",
    LLMProvider.ANTHROPIC: "anthropic/",
    LLMProvider.GOOGLE_GEMINI: "gemini/",
    LLMProvider.AWS_BEDROCK: "bedrock/",
    LLMProvider.GOOGLE_VERTEX_AI: "vertex_ai/",
    LLMProvider.CHATGPT_OAUTH: "",
    LLMProvider.XAI: "xai/",
    LLMProvider.XAI_OAUTH: "xai/",
}


def to_litellm_model(provider: LLMProvider, model_identifier: str) -> str:
    """Convert provider and model identifier to LiteLLM model string.

    :param provider: LLM provider
    :param model_identifier: Provider-specific model identifier
    :return: LiteLLM model string, e.g. ``openai/gpt-4o``
    """
    return f"{PROVIDER_LITELLM_PREFIX[provider]}{model_identifier}"


def to_runtime_model(provider: LLMProvider, model_identifier: str) -> str:
    """Return model identifier to pass to SDK runtime.

    OpenAI Responses API provider uses native OpenAI SDK, so pass raw model id
    without provider prefix. Other providers pass through LiteLLM adapter, so keep
    LiteLLM routing prefix.

    :param provider: LLM provider
    :param model_identifier: Provider-specific model identifier
    :return: Model identifier to pass to SDK execution
    """
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return model_identifier
    return to_litellm_model(provider, model_identifier)


def build_credential_kwargs(
    integration: LLMProviderIntegrationWithSecrets,
) -> dict[str, object]:
    """Convert integration credentials to LiteLLM kwargs format.

    :param integration: Integration info including secrets
    :return: Credential kwargs passed to litellm.acompletion()
    """
    match integration.secrets:
        case ApiKeySecrets(api_key=key):
            if integration.provider == LLMProvider.XAI:
                return {
                    "api_key": key,
                    "base_url": resolve_xai_api_base_url(),
                    "api_base": resolve_xai_api_base_url(),
                    "custom_llm_provider": "xai",
                }
            return {"api_key": key}
        case ChatGPTOAuthSecrets(access_token=token):
            config = integration.config
            if not isinstance(config, ChatGPTOAuthConfig):
                raise ValueError("ChatGPT OAuth integration config is required")
            return {
                "api_key": token,
                "base_url": CHATGPT_OAUTH_BACKEND_BASE_URL,
                "api_base": CHATGPT_OAUTH_BACKEND_BASE_URL,
                "extra_headers": build_chatgpt_oauth_headers(
                    account_id=config.account_id
                ),
            }
        case XaiOAuthSecrets(access_token=token):
            return {
                "api_key": token,
                "base_url": resolve_xai_api_base_url(),
                "api_base": resolve_xai_api_base_url(),
                "custom_llm_provider": "xai",
            }
        case AwsSecrets(secret_access_key=secret):
            config = cast(AwsConfig, integration.config)
            kwargs: dict[str, object] = {
                "aws_access_key_id": config.access_key_id,
                "aws_secret_access_key": secret,
                "aws_region_name": config.region,
            }
            if config.role_arn is not None:
                kwargs["aws_role_name"] = config.role_arn
                kwargs["aws_session_name"] = f"azents-{integration.workspace_id[:8]}"
            return kwargs
        case GcpSecrets(service_account_json=json_str):
            config = cast(GcpConfig, integration.config)
            return {
                "vertex_project": config.project_id,
                "vertex_location": config.region,
                "vertex_credentials": json_str,
            }
        case _:
            msg = f"Unsupported secrets type: {type(integration.secrets).__name__}"
            raise ValueError(msg)
