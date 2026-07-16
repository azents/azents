"""LLM Provider Integration service tests."""

import datetime

from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import LLMCatalogScope, LLMProvider
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.llm_provider_integration import (
    LLMProviderIntegrationService,
    catalog_sync_required_for_update,
)
from azents.services.llm_provider_integration.data import (
    LLMProviderIntegrationCreateInput,
    LLMProviderIntegrationUpdateInput,
)


def test_catalog_sync_required_for_catalog_affecting_update() -> None:
    assert catalog_sync_required_for_update(
        LLMProviderIntegrationUpdateInput(config=None),
        previously_enabled=True,
    )
    assert catalog_sync_required_for_update(
        LLMProviderIntegrationUpdateInput(
            secrets=ChatGPTOAuthSecrets(
                access_token="updated-access-token",
                refresh_token="updated-refresh-token",
                expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
            )
        ),
        previously_enabled=True,
    )
    assert catalog_sync_required_for_update(
        LLMProviderIntegrationUpdateInput(enabled=True),
        previously_enabled=False,
    )


def test_catalog_sync_not_required_for_non_affecting_update() -> None:
    assert not catalog_sync_required_for_update(
        LLMProviderIntegrationUpdateInput(name="Renamed"),
        previously_enabled=True,
    )
    assert not catalog_sync_required_for_update(
        LLMProviderIntegrationUpdateInput(enabled=False),
        previously_enabled=True,
    )
    assert not catalog_sync_required_for_update(
        LLMProviderIntegrationUpdateInput(enabled=True),
        previously_enabled=True,
    )


async def test_create_chatgpt_oauth_creates_integration_catalog(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Create the account-scoped catalog in the integration transaction."""
    async with rdb_session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="ChatGPT catalog workspace",
                handle="chatgpt-catalog-workspace",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session, "chatgpt-catalog-workspace"
        )
        assert workspace_id is not None

    catalog_repository = LLMCatalogRepository()
    service = LLMProviderIntegrationService(
        repository=LLMProviderIntegrationRepository(
            CredentialCipher(Fernet.generate_key().decode())
        ),
        catalog_repository=catalog_repository,
        session_manager=rdb_session_manager,
    )
    created = await service.create(
        LLMProviderIntegrationCreateInput(
            workspace_id=workspace_id,
            provider=LLMProvider.CHATGPT_OAUTH,
            name="ChatGPT Subscription",
            secrets=ChatGPTOAuthSecrets(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
            ),
            config=ChatGPTOAuthConfig(
                account_id="account-123",
                email="user@example.com",
                plan_type="plus",
                connection_method="callback",
                status="connected",
                connected_at=datetime.datetime(2026, 7, 14, tzinfo=datetime.UTC),
            ),
            enabled=True,
        )
    )

    async with rdb_session_manager() as session:
        catalog = await catalog_repository.get_by_integration(
            session,
            integration_id=created.id,
            workspace_id=workspace_id,
        )

    assert catalog is not None
    assert catalog.scope == LLMCatalogScope.INTEGRATION
    assert catalog.provider == LLMProvider.CHATGPT_OAUTH
    assert catalog.current_snapshot_id is None
