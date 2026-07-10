"""LLM Provider Integration repository tests."""

import datetime

from azcommon.result import Failure, Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

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
from azents.core.enums import LLMProvider
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


async def _create_workspace(session: AsyncSession) -> str:
    """Create Workspace for tests and return internal ID."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="Test workspace", handle="llm-integ-test-ws"),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, "llm-integ-test-ws")
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
        await repo.delete_by_id(rdb_session, created.id)

        # Then: None when fetching
        integration = await repo.get_by_id(rdb_session, created.id)
        assert integration is None
