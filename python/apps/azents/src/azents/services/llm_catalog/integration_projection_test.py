"""Integration model catalog projection tests."""

import datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

import azents.services.llm_catalog as llm_catalog_service
from azents.core.credentials import (
    ApiKeySecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    LLMCatalogPurpose,
    LLMModelDeveloper,
    LLMProvider,
)
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModalities,
    ModelModality,
)
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.core.workspace import WorkspaceCreate
from azents.rdb.session import SessionManager
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.llm_catalog import (
    LLMCatalogRepository,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationWithSecrets,
)
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.llm_catalog import (
    IntegrationCatalogProjectionService,
)
from azents.services.model_listing.data import (
    ModelListingOutput,
    ModelListingSummary,
    NormalizedModelCandidate,
)
from azents.services.model_metadata_source import (
    CatalogSourceAdapter,
    ModelMetadataSourceSyncService,
)


async def test_deterministic_integration_sync_does_not_require_source_authority(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Sync direct integration projections without remote metadata access."""
    async with rdb_session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="Direct catalog workspace",
                handle="direct-catalog-workspace",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session,
            "direct-catalog-workspace",
        )
        assert workspace_id is not None

        integration_repository = LLMProviderIntegrationRepository(
            CredentialCipher(Fernet.generate_key().decode())
        )
        integration = await integration_repository.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace_id,
                provider=LLMProvider.OPENROUTER,
                name="__testenv_model_listing:deterministic-openrouter",
                secrets=ApiKeySecrets(api_key="fixture"),
                config=None,
                enabled=True,
            ),
        )

    def unexpected_source_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected metadata source request: {request.url}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unexpected_source_request)
    ) as _client:
        result = await IntegrationCatalogProjectionService(
            provider_listing=llm_catalog_service.get_integration_model_listing(),
            session_manager=rdb_session_manager,
            catalog_repository=LLMCatalogRepository(),
            integration_repository=integration_repository,
            chatgpt_oauth_runtime_repository=ChatGPTOAuthRuntimeRepository(
                integration_repository=integration_repository,
                session_manager=rdb_session_manager,
            ),
            xai_oauth_runtime_repository=XaiOAuthRuntimeRepository(
                integration_repository=integration_repository,
                session_manager=rdb_session_manager,
            ),
            source_sync_service=ModelMetadataSourceSyncService(
                session_manager=rdb_session_manager,
                repository=ModelMetadataSourceRepository(),
                source_adapter=AsyncMock(spec=CatalogSourceAdapter),
            ),
        ).sync_integration_catalog(
            integration_id=integration.id,
            workspace_id=workspace_id,
        )

    assert isinstance(result, Success)
    assert result.value.snapshot_id is not None
    assert result.value.visible_count == 2


@pytest.mark.parametrize("provider", [LLMProvider.XAI_OAUTH, LLMProvider.CHATGPT_OAUTH])
@pytest.mark.parametrize("user_change_during_listing", [False, True])
async def test_oauth_sync_refresh_preserves_generation_and_user_update_fence(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    provider: LLMProvider,
    user_change_during_listing: bool,
) -> None:
    """Real token persistence permits publication but genuine user edits do not."""
    now = datetime.datetime.now(datetime.UTC)
    secrets_type = (
        XaiOAuthSecrets if provider is LLMProvider.XAI_OAUTH else ChatGPTOAuthSecrets
    )
    config_type = (
        XaiOAuthConfig if provider is LLMProvider.XAI_OAUTH else ChatGPTOAuthConfig
    )
    handle = f"oauth-catalog-{provider.value}-{user_change_during_listing}".lower()
    async with rdb_session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="OAuth catalog workspace",
                handle=handle,
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session,
            handle,
        )
        assert workspace_id is not None
        integration_repository = LLMProviderIntegrationRepository(
            CredentialCipher(Fernet.generate_key().decode())
        )
        created_integration = await integration_repository.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace_id,
                provider=provider,
                name="OAuth catalog",
                secrets=secrets_type(
                    access_token="expired-token",
                    refresh_token="refresh-token",
                    expires_at=now - datetime.timedelta(minutes=1),
                ),
                config=config_type(
                    account_id="account-id",
                    email=None,
                    connection_method="device",
                    status="connected",
                    connected_at=now,
                    last_refreshed_at=now,
                ),
                enabled=True,
            ),
        )
        integration = await integration_repository.get_by_id_with_secrets(
            session,
            created_integration.id,
        )
        assert integration is not None

    call_order: list[str] = []

    async def ensure_tokens(**kwargs: object) -> Success:
        call_order.append("refresh")
        persistence = kwargs["persistence_repository"]
        fresh_secrets = secrets_type(
            access_token="fresh-token",
            refresh_token="rotated-refresh-token",
            expires_at=now + datetime.timedelta(hours=1),
        )
        fresh_config = config_type(
            account_id="account-id",
            email=None,
            connection_method="device",
            status="connected",
            connected_at=now,
            last_refreshed_at=now + datetime.timedelta(seconds=1),
        )
        if isinstance(persistence, XaiOAuthRuntimeRepository):
            assert isinstance(fresh_secrets, XaiOAuthSecrets)
            assert isinstance(fresh_config, XaiOAuthConfig)
            refreshed = await persistence.update_and_reload(
                original_integration=integration,
                secrets=fresh_secrets,
                config=fresh_config,
            )
        else:
            assert isinstance(persistence, ChatGPTOAuthRuntimeRepository)
            assert isinstance(fresh_secrets, ChatGPTOAuthSecrets)
            assert isinstance(fresh_config, ChatGPTOAuthConfig)
            refreshed = await persistence.update_and_reload(
                original_integration=integration,
                secrets=fresh_secrets,
                config=fresh_config,
            )
        assert refreshed is not None
        assert (
            refreshed.catalog_configuration_version
            == integration.catalog_configuration_version
        )
        return Success(refreshed)

    async def list_models(
        listed_integration: LLMProviderIntegrationWithSecrets,
    ) -> ModelListingOutput:
        call_order.append("list")
        assert isinstance(
            listed_integration.secrets, (XaiOAuthSecrets, ChatGPTOAuthSecrets)
        )
        assert listed_integration.secrets.access_token == "fresh-token"
        if user_change_during_listing:
            async with rdb_session_manager() as session:
                update = await integration_repository.update_by_id(
                    session,
                    integration.id,
                    {
                        "secrets": secrets_type(
                            access_token="user-replaced-token",
                            refresh_token="user-replaced-refresh",
                            expires_at=now + datetime.timedelta(hours=2),
                        )
                    },
                )
                assert isinstance(update, Success)
                assert (
                    update.value.catalog_configuration_version
                    == integration.catalog_configuration_version + 1
                )
        return ModelListingOutput(
            models=[
                NormalizedModelCandidate(
                    provider=provider,
                    model_identifier="grok-4.6"
                    if provider is LLMProvider.XAI_OAUTH
                    else "gpt-5.4",
                    model_display_name="OAuth model",
                    model_developer=LLMModelDeveloper.XAI
                    if provider is LLMProvider.XAI_OAUTH
                    else LLMModelDeveloper.OPENAI,
                    model_family=None,
                    normalized_capabilities=ModelCapabilities(
                        modalities=ModelModalities(
                            input=[ModelModality.TEXT],
                            output=[ModelModality.TEXT],
                        )
                    ),
                    supported_execution_options=[],
                    model_snapshot={},
                    source_metadata={"context_window": 500000},
                    last_refreshed_at=now,
                )
            ],
            summary=ModelListingSummary(
                source="xai_oauth:grok_models",
                fetched_at=now,
                returned_count=1,
                skipped_count=0,
            ),
            skips=[],
        )

    monkeypatch.setattr(llm_catalog_service, "ensure_xai_runtime_tokens", ensure_tokens)
    monkeypatch.setattr(llm_catalog_service, "ensure_runtime_tokens", ensure_tokens)
    monkeypatch.setattr(
        llm_catalog_service,
        "_list_provider_visible_models",
        list_models,
    )

    async with httpx.AsyncClient() as _client:
        service = IntegrationCatalogProjectionService(
            provider_listing=llm_catalog_service.get_integration_model_listing(),
            session_manager=rdb_session_manager,
            catalog_repository=LLMCatalogRepository(),
            integration_repository=integration_repository,
            chatgpt_oauth_runtime_repository=ChatGPTOAuthRuntimeRepository(
                integration_repository=integration_repository,
                session_manager=rdb_session_manager,
            ),
            xai_oauth_runtime_repository=XaiOAuthRuntimeRepository(
                integration_repository=integration_repository,
                session_manager=rdb_session_manager,
            ),
            source_sync_service=ModelMetadataSourceSyncService(
                session_manager=rdb_session_manager,
                repository=ModelMetadataSourceRepository(),
                source_adapter=AsyncMock(spec=CatalogSourceAdapter),
            ),
        )
        if user_change_during_listing:
            with pytest.raises(
                RuntimeError,
                match="The integration catalog configuration generation changed",
            ):
                await service.sync_integration_catalog(
                    integration_id=integration.id,
                    workspace_id=workspace_id,
                    trigger=IntegrationCatalogSyncTrigger.CREATE,
                )
        else:
            result = await service.sync_integration_catalog(
                integration_id=integration.id,
                workspace_id=workspace_id,
                trigger=IntegrationCatalogSyncTrigger.CREATE,
            )
            assert isinstance(result, Success)
            assert result.value.visible_count == 1

    if user_change_during_listing:
        async with rdb_session_manager() as session:
            catalog = await LLMCatalogRepository().get_by_integration(
                session,
                integration_id=integration.id,
                workspace_id=workspace_id,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
            assert catalog is not None
            assert catalog.current_snapshot_id is None
            attempt = await LLMCatalogRepository().get_latest_attempt(
                session, catalog=catalog
            )
            assert attempt is not None
            assert attempt.failure_message == (
                "The integration catalog configuration generation changed."
            )
    assert call_order == ["refresh", "list"]


async def test_xai_failure_preserves_last_successful_snapshot(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the published xAI catalog when a later provider refresh fails."""
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="xAI failure workspace",
                handle="xai-failure-workspace",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session,
            "xai-failure-workspace",
        )
        assert workspace_id is not None
        integration_repository = LLMProviderIntegrationRepository(
            CredentialCipher(Fernet.generate_key().decode())
        )
        integration = await integration_repository.create(
            session,
            LLMProviderIntegrationCreate(
                workspace_id=workspace_id,
                provider=LLMProvider.XAI,
                name="xAI API key",
                secrets=ApiKeySecrets(api_key="secret-api-key"),
                config=None,
                enabled=True,
            ),
        )

    listing = ModelListingOutput(
        models=[
            NormalizedModelCandidate(
                provider=LLMProvider.XAI,
                model_identifier="grok-4.7",
                model_display_name="grok-4.7",
                model_developer=LLMModelDeveloper.XAI,
                model_family="grok-4",
                normalized_capabilities=ModelCapabilities(
                    modalities=ModelModalities(
                        input=[ModelModality.TEXT],
                        output=[ModelModality.TEXT],
                    )
                ),
                supported_execution_options=[],
                model_snapshot={},
                source_metadata={"created": 1, "owned_by": "xai"},
                last_refreshed_at=now,
            )
        ],
        summary=ModelListingSummary(
            source="xai:developer_models",
            fetched_at=now,
            returned_count=1,
            skipped_count=0,
        ),
        skips=[],
    )
    calls = 0

    async def list_models(integration_value: object) -> ModelListingOutput:
        nonlocal calls
        del integration_value
        calls += 1
        if calls == 1:
            return listing
        raise llm_catalog_service.XaiListingProviderError(
            failure_code="XaiEntitlementDenied",
            automatic_retry_blocked=True,
        )

    monkeypatch.setattr(
        llm_catalog_service,
        "_list_provider_visible_models",
        list_models,
    )
    catalog_repository = LLMCatalogRepository()
    async with httpx.AsyncClient() as _client:
        service = IntegrationCatalogProjectionService(
            provider_listing=llm_catalog_service.get_integration_model_listing(),
            session_manager=rdb_session_manager,
            catalog_repository=catalog_repository,
            integration_repository=integration_repository,
            chatgpt_oauth_runtime_repository=ChatGPTOAuthRuntimeRepository(
                integration_repository=integration_repository,
                session_manager=rdb_session_manager,
            ),
            xai_oauth_runtime_repository=XaiOAuthRuntimeRepository(
                integration_repository=integration_repository,
                session_manager=rdb_session_manager,
            ),
            source_sync_service=ModelMetadataSourceSyncService(
                session_manager=rdb_session_manager,
                repository=ModelMetadataSourceRepository(),
                source_adapter=AsyncMock(spec=CatalogSourceAdapter),
            ),
        )
        first = await service.sync_integration_catalog(
            integration_id=integration.id,
            workspace_id=workspace_id,
            trigger=IntegrationCatalogSyncTrigger.CREATE,
        )
        assert isinstance(first, Success)
        first_snapshot_id = first.value.snapshot_id
        failed = await service.sync_integration_catalog(
            integration_id=integration.id,
            workspace_id=workspace_id,
            trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
        )

    assert isinstance(failed, Success)
    assert failed.value.status == "failed"
    assert failed.value.snapshot_id == first_snapshot_id
    assert failed.value.failure_code == "XaiEntitlementDenied"
    assert failed.value.failure_message == "xAI model listing failed."
    async with rdb_session_manager() as session:
        catalog = await catalog_repository.get_by_integration(
            session,
            integration_id=integration.id,
            workspace_id=workspace_id,
            purpose=LLMCatalogPurpose.CONVERSATION,
        )
        assert catalog is not None
        assert catalog.current_snapshot_id == first_snapshot_id
        latest_attempt = await catalog_repository.get_latest_attempt(
            session,
            catalog=catalog,
        )
    assert latest_attempt is not None
    assert latest_attempt.diagnostics is not None
    assert latest_attempt.diagnostics["automatic_retry_blocked"] is True
    assert "secret-api-key" not in str(latest_attempt.diagnostics)
