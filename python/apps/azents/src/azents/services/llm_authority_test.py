"""Typed credential projection and completed-operation orchestration."""

import datetime
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from azents_llm_contract.authority import AuthenticatedIdentity
from pydantic import SecretStr

from azents.core.agent import (
    ModelParameters,
    SelectableModelCandidate,
    SelectableModelSettings,
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
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider
from azents.repos.agent.data import Agent
from azents.repos.llm_authority import LLMAuthorityRepository, PreparedLLMAuthority
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.services.chatgpt_oauth.data import ProviderUnavailable
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.llm_authority import (
    LLMAuthorityService,
    LLMCredentialUnavailable,
    project_configuration,
    project_credential,
)
from azents.testing.model_selection import make_test_model_selection

NOW = datetime.datetime(2026, 10, 28, tzinfo=datetime.UTC)
SENTINEL = "provider-access-sentinel"
REFRESH = "refresh-never-in-response"


def integration(provider: LLMProvider) -> LLMProviderIntegrationWithSecrets:
    secret = ApiKeySecrets(api_key=SENTINEL)
    value = LLMProviderIntegrationWithSecrets(
        id="integration",
        workspace_id="workspace",
        provider=provider,
        name="Fixture",
        config=None,
        enabled=True,
        catalog_configuration_version=1,
        created_at=NOW,
        updated_at=NOW,
        secrets=secret,
    )
    match provider:
        case LLMProvider.CHATGPT_OAUTH:
            value.secrets = ChatGPTOAuthSecrets(
                access_token=SENTINEL, refresh_token=REFRESH, expires_at=NOW
            )
            value.config = ChatGPTOAuthConfig(
                connection_method="device", status="connected", account_id="account"
            )
        case LLMProvider.XAI_OAUTH:
            value.secrets = XaiOAuthSecrets(
                access_token=SENTINEL, refresh_token=REFRESH, expires_at=NOW
            )
            value.config = XaiOAuthConfig(
                connection_method="device", status="connected"
            )
        case LLMProvider.KIMI_OAUTH:
            value.secrets = KimiOAuthSecrets(
                access_token=SENTINEL,
                refresh_token=REFRESH,
                expires_at=NOW,
                device_id="device-sentinel",
            )
            value.config = KimiOAuthConfig(
                connection_method="device",
                status="connected",
                connected_at=None,
                last_refreshed_at=None,
                last_failed_at=None,
                last_failure_reason=None,
            )
        case LLMProvider.AWS_BEDROCK:
            value.secrets = AwsSecrets(secret_access_key=SENTINEL)
            value.config = AwsConfig(
                access_key_id="key-id-sentinel",
                region="us-east-1",
                role_arn="arn:aws:iam::123456789012:role/fixture",
            )
        case LLMProvider.GOOGLE_VERTEX_AI:
            value.secrets = GcpSecrets(service_account_json=SENTINEL)
            value.config = GcpConfig(project_id="project", region="region")
    return value


def prepared() -> PreparedLLMAuthority:
    candidate = SelectableModelCandidate(
        model_selection=make_test_model_selection(
            integration_id="integration", model_identifier="model"
        ),
        settings=SelectableModelSettings(
            context_window_tokens=5000, max_output_tokens=1000, builtin_tools=[]
        ),
    )
    agent = Agent.model_construct(
        id="agent",
        workspace_id="workspace",
        model_parameters=ModelParameters(temperature=0.2),
    )
    return PreparedLLMAuthority(
        identity=AuthenticatedIdentity(
            agent_id="agent",
            workspace_id="workspace",
            supply_id="supply",
            token_id="token",
        ),
        candidate=candidate,
        integration=integration(LLMProvider.OPENAI),
        agent=agent,
    )


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_all_provider_projections_exclude_management_credentials(
    provider: LLMProvider,
) -> None:
    result = project_credential(integration(provider))
    assert SENTINEL not in repr(result)
    assert REFRESH not in result.protected_json()
    assert SENTINEL in result.protected_json()
    assert "refresh_token" not in result.model_dump()


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.AWS_BEDROCK,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI_OAUTH,
        LLMProvider.KIMI_OAUTH,
        LLMProvider.GOOGLE_VERTEX_AI,
    ],
)
def test_mismatched_secret_does_not_become_a_different_route(
    provider: LLMProvider,
) -> None:
    value = integration(provider)
    value.secrets = ApiKeySecrets(api_key=SENTINEL)
    with pytest.raises(LLMCredentialUnavailable, match="configuration is unavailable"):
        project_credential(value)


def test_configuration_uses_existing_snapshot_without_new_defaults() -> None:
    value = prepared()
    projected = project_configuration(value)
    assert projected.context_window_tokens == 5000
    assert projected.max_output_tokens == 1000
    assert projected.parameters is not None and projected.parameters.temperature == 0.2
    assert projected.maximum_output_tokens is None
    assert projected.builtin_tools == ()
    assert projected.parameters.reasoning_effort is None


async def test_refresh_then_final_revalidation_order() -> None:
    value = prepared()
    repository = AsyncMock(spec=LLMAuthorityRepository)
    tokens = AsyncMock(spec=EngineRuntimeTokenResolver)
    sequence: list[str] = []

    async def prepare(**kwargs: object) -> PreparedLLMAuthority:
        sequence.append("prepare-completed")
        return value

    async def refresh(
        integration: LLMProviderIntegrationWithSecrets,
    ) -> Success[LLMProviderIntegrationWithSecrets]:
        assert sequence == ["prepare-completed"]
        sequence.append("refresh-completed")
        return Success(integration)

    async def finalize(**kwargs: object) -> PreparedLLMAuthority:
        assert sequence == ["prepare-completed", "refresh-completed"]
        sequence.append("admitted")
        return value

    repository.prepare.side_effect = prepare
    tokens.ensure.side_effect = refresh
    repository.finalize.side_effect = finalize
    result = await LLMAuthorityService(repository, tokens).resolve(
        agent_token="agent-secret", model="model", target_id="a" * 64
    )
    assert result.identity.agent_id == "agent"
    assert SENTINEL not in repr(result)
    assert "agent-secret" not in str(repository.prepare.call_args)
    assert sequence == ["prepare-completed", "refresh-completed", "admitted"]


async def test_refresh_failure_is_not_agent_auth_failure_or_secret_diagnostic() -> None:
    repository = AsyncMock(spec=LLMAuthorityRepository)
    repository.prepare.return_value = prepared()
    tokens = AsyncMock(spec=EngineRuntimeTokenResolver)
    tokens.ensure.return_value = Failure(ProviderUnavailable(reason=REFRESH))
    with pytest.raises(LLMCredentialUnavailable) as caught:
        await LLMAuthorityService(repository, tokens).resolve(
            agent_token="agent-secret", model="model", target_id="a" * 64
        )
    assert REFRESH not in str(caught.value)
    repository.finalize.assert_not_called()


async def test_listing_never_refreshes_or_prepares_secrets() -> None:
    repository = AsyncMock(spec=LLMAuthorityRepository)
    tokens = AsyncMock(spec=EngineRuntimeTokenResolver)
    await LLMAuthorityService(repository, tokens).list_models(
        agent_token=SecretStr("agent-secret").get_secret_value()
    )
    repository.list_models.assert_awaited_once()
    repository.prepare.assert_not_called()
    tokens.ensure.assert_not_called()
