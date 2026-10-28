"""Resolve current Agent authority without holding DB transactions across OAuth."""

from dataclasses import dataclass
from typing import Annotated, assert_never

from azents_llm_contract.authority import (
    ApiKeyCredential,
    BedrockCredential,
    ChatGPTCredential,
    KimiCredential,
    ModelListResponse,
    ProviderCredential,
    TargetBinding,
    VertexCredential,
    XaiCredential,
)
from azents_llm_contract.settings import ModelConfiguration
from fastapi import Depends
from pydantic import SecretStr

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
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider
from azents.core.llm_access import token_digest
from azents.repos.llm_authority import LLMAuthorityRepository, PreparedLLMAuthority
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver


class LLMCredentialUnavailable(Exception):
    """Preparation failed; this is not a claim that the Agent bearer is invalid."""


def project_configuration(prepared: PreparedLLMAuthority) -> ModelConfiguration:
    """Project only current configuration, with no independent policy defaults."""
    selection = prepared.candidate.model_selection
    settings = prepared.candidate.settings
    capabilities = selection.normalized_capabilities
    parameters = prepared.agent.model_parameters
    return ModelConfiguration.model_validate(
        {
            "parameters": parameters.model_dump(mode="json")
            if parameters is not None
            else None,
            "context_window_tokens": settings.context_window_tokens,
            "max_output_tokens": settings.max_output_tokens,
            "default_input_tokens": capabilities.context_window.default_input_tokens,
            "maximum_input_tokens": capabilities.context_window.max_input_tokens,
            "maximum_output_tokens": capabilities.context_window.max_output_tokens,
            "builtin_tools": [
                tool.model_dump(mode="json") for tool in settings.builtin_tools
            ],
            "supported_features": sorted(
                feature.value for feature in capabilities.supported_features()
            ),
            "reasoning_efforts": capabilities.reasoning.effort_levels,
            "known_default_reasoning": capabilities.request_constraints.known_default,
            "feature_conditions": [
                c.model_dump(mode="json")
                for c in capabilities.request_constraints.feature_conditions
            ],
            "supported_execution_options": selection.supported_execution_options,
        }
    )


def project_credential(
    integration: LLMProviderIntegrationWithSecrets,
) -> ProviderCredential:
    """Discard refresh and management secrets; never create arbitrary SDK kwargs."""
    secret = integration.secrets
    config = integration.config
    match integration.provider:
        case (
            LLMProvider.OPENAI
            | LLMProvider.ANTHROPIC
            | LLMProvider.GOOGLE_GEMINI
            | LLMProvider.XAI
            | LLMProvider.OPENROUTER
        ) as provider:
            if isinstance(secret, ApiKeySecrets):
                return ApiKeyCredential(
                    kind="api_key",
                    provider=provider.value,
                    api_key=SecretStr(secret.api_key),
                )
        case LLMProvider.CHATGPT_OAUTH:
            if isinstance(secret, ChatGPTOAuthSecrets) and isinstance(
                config, ChatGPTOAuthConfig
            ):
                return ChatGPTCredential(
                    kind="chatgpt_oauth",
                    access_token=SecretStr(secret.access_token),
                    account_id=config.account_id,
                )
        case LLMProvider.XAI_OAUTH:
            if isinstance(secret, XaiOAuthSecrets) and isinstance(
                config, XaiOAuthConfig
            ):
                return XaiCredential(
                    kind="xai_oauth", access_token=SecretStr(secret.access_token)
                )
        case LLMProvider.KIMI_OAUTH:
            if isinstance(secret, KimiOAuthSecrets) and isinstance(
                config, KimiOAuthConfig
            ):
                return KimiCredential(
                    kind="kimi_oauth",
                    access_token=SecretStr(secret.access_token),
                    device_id=SecretStr(secret.device_id),
                )
        case LLMProvider.AWS_BEDROCK:
            if isinstance(secret, AwsSecrets) and isinstance(config, AwsConfig):
                return BedrockCredential(
                    kind="aws_bedrock",
                    access_key_id=SecretStr(config.access_key_id),
                    secret_access_key=SecretStr(secret.secret_access_key),
                    region=config.region,
                    role_arn=config.role_arn,
                    role_session_name=f"azents-{integration.workspace_id[:8]}"
                    if config.role_arn is not None
                    else None,
                )
        case LLMProvider.GOOGLE_VERTEX_AI:
            if isinstance(secret, GcpSecrets) and isinstance(config, GcpConfig):
                return VertexCredential(
                    kind="google_vertex_ai",
                    service_account_json=SecretStr(secret.service_account_json),
                    project_id=config.project_id,
                    location=config.region,
                )
        case _ as unknown:
            assert_never(unknown)
    raise LLMCredentialUnavailable("Provider credential configuration is unavailable.")


@dataclass
class LLMAuthorityService:
    repository: Annotated[LLMAuthorityRepository, Depends(LLMAuthorityRepository)]
    tokens: Annotated[EngineRuntimeTokenResolver, Depends(EngineRuntimeTokenResolver)]

    async def list_models(self, *, agent_token: str) -> ModelListResponse:
        # No integration secret reads and no refresh on listing.
        return await self.repository.list_models(digest=token_digest(agent_token))

    async def resolve(
        self, *, agent_token: str, model: str, target_id: str
    ) -> TargetBinding:
        digest = token_digest(agent_token)
        prepared = await self.repository.prepare(
            digest=digest, model=model, target_id=target_id
        )
        refreshed = await self.tokens.ensure(prepared.integration)
        if refreshed.failure:
            # Do not expose OAuth errors/raw bodies through logs or HTTP errors.
            raise LLMCredentialUnavailable("Provider credential preparation failed.")
        latest = await self.repository.finalize(
            digest=digest,
            model=model,
            target_id=target_id,
            prepared=prepared,
            refreshed=refreshed.value,
        )
        return TargetBinding(
            identity=latest.identity,
            integration_id=latest.integration.id,
            target_id=target_id,
            public_model=model,
            model_identifier=latest.candidate.model_selection.model_identifier,
            configuration=project_configuration(latest),
            credential=project_credential(latest.integration),
        )
