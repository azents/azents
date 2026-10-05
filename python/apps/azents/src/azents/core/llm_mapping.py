"""Convert saved integration credentials into operation-scoped SDK settings."""

from typing import assert_never

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
    KimiOAuthConfig,
    KimiOAuthSecrets,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider
from azents.core.kimi_oauth import (
    build_kimi_compatibility_headers,
    resolve_kimi_code_api_base_url,
)
from azents.core.openrouter import OPENROUTER_API_BASE_URL, OPENROUTER_APP_TITLE
from azents.core.xai import resolve_xai_api_base_url
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)


def build_credential_kwargs(
    integration: LLMProviderIntegrationWithSecrets,
) -> dict[str, object]:
    """Convert integration credentials to operation-scoped client settings.

    :param integration: Integration info including secrets
    :return: Settings consumed by the selected official SDK client factory
    """
    match integration.secrets:
        case ApiKeySecrets(api_key=key):
            if integration.provider == LLMProvider.XAI:
                return {
                    "api_key": key,
                    "base_url": resolve_xai_api_base_url(),
                }
            if integration.provider == LLMProvider.OPENROUTER:
                return {
                    "api_key": key,
                    "base_url": OPENROUTER_API_BASE_URL,
                    "extra_headers": {
                        "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
                    },
                }
            return {"api_key": key}
        case ChatGPTOAuthSecrets(access_token=token):
            config = integration.config
            if not isinstance(config, ChatGPTOAuthConfig):
                raise ValueError("ChatGPT OAuth integration config is required")
            return {
                "api_key": token,
                "base_url": CHATGPT_OAUTH_BACKEND_BASE_URL,
                "extra_headers": build_chatgpt_oauth_headers(
                    account_id=config.account_id
                ),
            }
        case XaiOAuthSecrets(access_token=token):
            return {
                "api_key": token,
                "base_url": resolve_xai_api_base_url(),
            }
        case KimiOAuthSecrets(access_token=token, device_id=device_id):
            if not isinstance(integration.config, KimiOAuthConfig):
                raise ValueError("Kimi OAuth integration config is required")
            base_url = resolve_kimi_code_api_base_url()
            return {
                "api_key": token,
                "base_url": base_url,
                "extra_headers": build_kimi_compatibility_headers(device_id=device_id),
            }
        case AwsSecrets(secret_access_key=secret):
            config = integration.config
            if not isinstance(config, AwsConfig):
                raise ValueError("AWS integration config is required")
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
            config = integration.config
            if not isinstance(config, GcpConfig):
                raise ValueError("GCP integration config is required")
            return {
                "vertex_project": config.project_id,
                "vertex_location": config.region,
                "vertex_credentials": json_str,
            }
        case _:
            assert_never(integration.secrets)
