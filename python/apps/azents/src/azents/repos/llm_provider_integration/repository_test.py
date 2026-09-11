"""LLM Provider Integration repository tests."""

import asyncio
import datetime
from uuid import uuid4

import sqlalchemy as sa
from azcommon.result import Failure, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.credentials import (
    ApiKeySecrets,
    AwsConfig,
    AwsSecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    GcpConfig,
    GcpSecrets,
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    LLMCatalogLowererTarget,
    LLMCatalogPurpose,
    LLMProvider,
)
from azents.rdb.models.llm_catalog import RDBLLMCatalog
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from . import LLMProviderIntegrationRepository
from .data import (
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationUpdate,
    NotFound,
)

_TEST_KEY = Fernet.generate_key().decode()


def _make_repo() -> LLMProviderIntegrationRepository:
    """Create repository for tests."""
    return LLMProviderIntegrationRepository(CredentialCipher(_TEST_KEY))


async def _create_workspace(
    session: AsyncSession,
    *,
    handle: str = "llm-integ-test-ws",
) -> str:
    """Create Workspace for tests and return internal ID."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="Test workspace", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


class TestLLMProviderIntegrationRepository:
    """LLMProviderIntegrationRepository tests."""

    async def test_create(self, rdb_session: AsyncSession) -> None:
        """Create LLM Provider Integration (API key provider)."""
        # Given: Workspace + prepare create data
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        create = LLMProviderIntegrationCreate(
            workspace_id=ws_id,
            provider=LLMProvider.OPENAI,
            name="Production API Key",
            secrets=ApiKeySecrets(api_key="sk-test-key"),
        )

        # When: create
        integration = await repo.create(rdb_session, create)

        # Then: check success
        assert integration.workspace_id == ws_id
        assert integration.provider == LLMProvider.OPENAI
        assert integration.name == "Production API Key"
        assert integration.config is None
        assert integration.enabled is True
        assert integration.created_at
        assert integration.updated_at

    async def test_create_xai_api_key_encrypts_and_redacts_secrets(
        self, rdb_session: AsyncSession
    ) -> None:
        """Encrypt xAI API keys at rest and omit them from normal reads."""
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        api_key = "xai-test-api-key"

        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.XAI,
                name="xAI API key",
                secrets=ApiKeySecrets(api_key=api_key),
            ),
        )

        stored = await rdb_session.get(RDBLLMProviderIntegration, created.id)
        redacted = await repo.get_by_id(rdb_session, created.id)
        with_secrets = await repo.get_by_id_with_secrets(rdb_session, created.id)

        assert stored is not None
        assert api_key not in stored.encrypted_credentials
        assert redacted is not None
        assert not hasattr(redacted, "secrets")
        assert with_secrets is not None
        assert with_secrets.secrets == ApiKeySecrets(api_key=api_key)
        assert with_secrets.config is None

    async def test_create_with_config(self, rdb_session: AsyncSession) -> None:
        """Create LLM Provider Integration (provider with config)."""
        # Given: Workspace + prepare AWS Bedrock create data
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        create = LLMProviderIntegrationCreate(
            workspace_id=ws_id,
            provider=LLMProvider.AWS_BEDROCK,
            name="Bedrock Access Key",
            secrets=AwsSecrets(secret_access_key="secret-test"),
            config=AwsConfig(
                access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID", region="us-east-1"
            ),
        )

        # When: create
        integration = await repo.create(rdb_session, create)

        # Then: check config included
        assert integration.workspace_id == ws_id
        assert integration.provider == LLMProvider.AWS_BEDROCK
        assert integration.config == AwsConfig(
            access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID", region="us-east-1"
        )

    async def test_get_by_id(self, rdb_session: AsyncSession) -> None:
        """Fetch LLM Provider Integration by ID, excluding secrets."""
        # Given: create Integration
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.ANTHROPIC,
                name="Anthropic Key",
                secrets=ApiKeySecrets(api_key="example-anthropic-api-key"),
            ),
        )

        # When: fetch by ID
        integration = await repo.get_by_id(rdb_session, created.id)

        # Then: fetch success
        assert integration is not None
        assert integration.id == created.id
        assert integration.provider == LLMProvider.ANTHROPIC
        assert integration.name == "Anthropic Key"

    async def test_get_by_id_not_found(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching by nonexistent ID."""
        repo = _make_repo()
        integration = await repo.get_by_id(rdb_session, "nonexistent-id")
        assert integration is None

    async def test_get_by_id_with_secrets(self, rdb_session: AsyncSession) -> None:
        """Fetch LLM Provider Integration by ID, including secrets."""
        # Given: create Integration
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.AWS_BEDROCK,
                name="Bedrock Access Key",
                secrets=AwsSecrets(secret_access_key="secret-test"),
                config=AwsConfig(
                    access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID", region="us-east-1"
                ),
            ),
        )

        # When: fetch including secrets
        integration = await repo.get_by_id_with_secrets(rdb_session, created.id)

        # Then: secrets decrypted and included, config also included
        assert integration is not None
        assert integration.id == created.id
        assert integration.secrets == AwsSecrets(secret_access_key="secret-test")
        assert integration.config == AwsConfig(
            access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID", region="us-east-1"
        )

    async def test_get_by_id_with_secrets_gcp(self, rdb_session: AsyncSession) -> None:
        """Fetch GCP provider including secrets."""
        # Given: create GCP Integration
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.GOOGLE_VERTEX_AI,
                name="Vertex AI",
                secrets=GcpSecrets(service_account_json='{"key": "value"}'),
                config=GcpConfig(project_id="my-project", region="us-central1"),
            ),
        )

        # When: fetch including secrets
        integration = await repo.get_by_id_with_secrets(rdb_session, created.id)

        # Then: both secrets/config decrypted and included
        assert integration is not None
        assert integration.secrets == GcpSecrets(
            service_account_json='{"key": "value"}'
        )
        assert integration.config == GcpConfig(
            project_id="my-project", region="us-central1"
        )

    async def test_get_by_id_with_secrets_chatgpt_oauth(
        self, rdb_session: AsyncSession
    ) -> None:
        """Fetch ChatGPT OAuth secrets and config decrypted."""
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        expires_at = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
        connected_at = datetime.datetime(2026, 5, 2, tzinfo=datetime.UTC)
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.CHATGPT_OAUTH,
                name="ChatGPT Subscription",
                secrets=ChatGPTOAuthSecrets(
                    access_token="access-token",
                    refresh_token="refresh-token",
                    expires_at=expires_at,
                ),
                config=ChatGPTOAuthConfig(
                    account_id="account-123",
                    email="user@example.com",
                    plan_type="plus",
                    connection_method="callback",
                    status="connected",
                    connected_at=connected_at,
                ),
            ),
        )

        integration = await repo.get_by_id_with_secrets(rdb_session, created.id)

        assert integration is not None
        assert integration.provider == LLMProvider.CHATGPT_OAUTH
        assert integration.secrets == ChatGPTOAuthSecrets(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=expires_at,
        )
        assert integration.config == ChatGPTOAuthConfig(
            account_id="account-123",
            email="user@example.com",
            plan_type="plus",
            connection_method="callback",
            status="connected",
            connected_at=connected_at,
        )

    async def test_get_by_id_with_secrets_xai_oauth(
        self, rdb_session: AsyncSession
    ) -> None:
        """Fetch xAI OAuth secrets and config decrypted."""
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        expires_at = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
        connected_at = datetime.datetime(2026, 7, 10, tzinfo=datetime.UTC)
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.XAI_OAUTH,
                name="xAI Grok OAuth",
                secrets=XaiOAuthSecrets(
                    access_token="access-token",
                    refresh_token="refresh-token",
                    expires_at=expires_at,
                ),
                config=XaiOAuthConfig(
                    account_id="account-123",
                    email="user@example.com",
                    connection_method="device",
                    status="connected",
                    connected_at=connected_at,
                ),
            ),
        )

        integration = await repo.get_by_id_with_secrets(rdb_session, created.id)

        assert integration is not None
        assert integration.provider == LLMProvider.XAI_OAUTH
        assert integration.secrets == XaiOAuthSecrets(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=expires_at,
        )
        assert integration.config == XaiOAuthConfig(
            account_id="account-123",
            email="user@example.com",
            connection_method="device",
            status="connected",
            connected_at=connected_at,
        )

    async def test_list_by_workspace(self, rdb_session: AsyncSession) -> None:
        """Fetch integrations by workspace."""
        # Given: create multiple integrations in one workspace
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.OPENAI,
                name="OpenAI Key",
                secrets=ApiKeySecrets(api_key="sk-1"),
            ),
        )
        await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.ANTHROPIC,
                name="Anthropic Key",
                secrets=ApiKeySecrets(api_key="example-anthropic-api-key-1"),
            ),
        )

        # When: fetch list by workspace
        integration_list = await repo.list_by_workspace(rdb_session, ws_id)

        # Then: return two items
        assert len(integration_list.items) == 2

    async def test_update_by_id(self, rdb_session: AsyncSession) -> None:
        """Update LLM Provider Integration."""
        # Given: create Integration
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.GOOGLE_GEMINI,
                name="Before update",
                secrets=ApiKeySecrets(api_key="AIza-test"),
            ),
        )

        # When: update name + enabled
        result = await repo.update_by_id(
            rdb_session,
            created.id,
            LLMProviderIntegrationUpdate(name="After update", enabled=False),
        )

        # Then: update success
        assert isinstance(result, Success)
        assert result.value.name == "After update"
        assert result.value.enabled is False
        assert result.value.catalog_configuration_version == 2

    async def test_name_only_update_preserves_catalog_configuration_version(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Display-name changes do not invalidate credential-visible catalogs."""
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.OPENAI,
                name="Before rename",
                secrets=ApiKeySecrets(api_key="sk-test"),
            ),
        )

        result = await repo.update_by_id(
            rdb_session,
            created.id,
            LLMProviderIntegrationUpdate(name="After rename"),
        )

        assert isinstance(result, Success)
        assert result.value.catalog_configuration_version == 1

    async def test_update_secrets(self, rdb_session: AsyncSession) -> None:
        """Check decryption after secrets update."""
        # Given: create Integration
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.OPENAI,
                name="Secrets Update Test",
                secrets=ApiKeySecrets(api_key="old-key"),
            ),
        )

        # When: update secrets
        await repo.update_by_id(
            rdb_session,
            created.id,
            LLMProviderIntegrationUpdate(secrets=ApiKeySecrets(api_key="new-key")),
        )

        # Then: decrypt with new secrets
        integration = await repo.get_by_id_with_secrets(rdb_session, created.id)
        assert integration is not None
        assert integration.secrets == ApiKeySecrets(api_key="new-key")

    async def test_update_config(self, rdb_session: AsyncSession) -> None:
        """Check config update."""
        # Given: create AWS Integration
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.AWS_BEDROCK,
                name="Config Update Test",
                secrets=AwsSecrets(secret_access_key="secret"),
                config=AwsConfig(
                    access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID_OLD", region="us-east-1"
                ),
            ),
        )

        # When: update config
        result = await repo.update_by_id(
            rdb_session,
            created.id,
            LLMProviderIntegrationUpdate(
                config=AwsConfig(
                    access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID_NEW",
                    region="ap-northeast-2",
                )
            ),
        )

        # Then: check new config
        assert isinstance(result, Success)
        assert result.value.config == AwsConfig(
            access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID_NEW", region="ap-northeast-2"
        )

    async def test_update_not_found(self, rdb_session: AsyncSession) -> None:
        """Return NotFound when updating nonexistent ID."""
        repo = _make_repo()
        result = await repo.update_by_id(
            rdb_session,
            "nonexistent-id",
            LLMProviderIntegrationUpdate(name="Update"),
        )
        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_delete_by_id(self, rdb_session: AsyncSession) -> None:
        """Delete LLM Provider Integration."""
        # Given: create Integration
        ws_id = await _create_workspace(rdb_session)
        repo = _make_repo()
        created = await repo.create(
            rdb_session,
            LLMProviderIntegrationCreate(
                workspace_id=ws_id,
                provider=LLMProvider.ANTHROPIC,
                name="Delete target",
                secrets=ApiKeySecrets(api_key="example-anthropic-api-key-delete"),
            ),
        )

        # When: delete
        await repo.delete_by_id(
            rdb_session,
            created.id,
            workspace_id=ws_id,
        )

        # Then: None when fetching
        integration = await repo.get_by_id(rdb_session, created.id)
        assert integration is None

    async def test_delete_locks_catalog_before_integration(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Catalog synchronization cannot deadlock with integration deletion."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        application_name = f"integration-delete-lock-order-{suffix}"
        repo = _make_repo()
        catalog_repo = LLMCatalogRepository()
        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as setup_session:
            workspace_id = await _create_workspace(
                setup_session,
                handle=f"llm-integration-delete-lock-order-{suffix}",
            )
            integration = await repo.create(
                setup_session,
                LLMProviderIntegrationCreate(
                    workspace_id=workspace_id,
                    provider=LLMProvider.OPENAI,
                    name="Concurrent deletion target",
                    secrets=ApiKeySecrets(api_key="sk-concurrent-delete"),
                ),
            )
            catalog = await catalog_repo.ensure_integration_catalog(
                setup_session,
                integration_id=integration.id,
                provider=integration.provider,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                purpose=LLMCatalogPurpose.CONVERSATION,
            )
            await setup_session.commit()

        async def delete_integration() -> None:
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as delete_session:
                await delete_session.execute(
                    sa.text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
                await repo.delete_by_id(
                    delete_session,
                    integration.id,
                    workspace_id=workspace_id,
                )
                await delete_session.commit()

        async def wait_for_workspace_lock() -> None:
            deadline = asyncio.get_running_loop().time() + 5
            while asyncio.get_running_loop().time() < deadline:
                async with AsyncSession(rdb_engine) as observer:
                    waiting = await observer.scalar(
                        sa.text(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM pg_stat_activity
                                WHERE application_name = :application_name
                                  AND wait_event_type = 'Lock'
                                  AND query LIKE '%FROM workspaces%'
                                  AND query LIKE '%FOR UPDATE%'
                            )
                            """
                        ),
                        {"application_name": application_name},
                    )
                if waiting:
                    return
                await asyncio.sleep(0.01)
            raise TimeoutError("Integration deletion did not wait for the Workspace")

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as sync_session:
            locked_workspace_id = await sync_session.scalar(
                sa.select(RDBWorkspace.id)
                .where(RDBWorkspace.id == workspace_id)
                .with_for_update()
            )
            assert locked_workspace_id == workspace_id
            locked_catalog_id = await sync_session.scalar(
                sa.select(RDBLLMCatalog.id)
                .where(RDBLLMCatalog.id == catalog.id)
                .with_for_update()
            )
            assert locked_catalog_id == catalog.id

            deletion_task = asyncio.create_task(delete_integration())
            await wait_for_workspace_lock()
            locked_integration_id = await asyncio.wait_for(
                sync_session.scalar(
                    sa.select(RDBLLMProviderIntegration.id)
                    .where(RDBLLMProviderIntegration.id == integration.id)
                    .with_for_update()
                ),
                timeout=5,
            )
            assert locked_integration_id == integration.id
            await sync_session.commit()

        await asyncio.wait_for(deletion_task, timeout=5)

        async with AsyncSession(rdb_engine) as verification_session:
            assert (
                await verification_session.get(
                    RDBLLMProviderIntegration,
                    integration.id,
                )
                is None
            )
            assert (
                await verification_session.get(
                    RDBLLMCatalog,
                    catalog.id,
                )
                is None
            )
