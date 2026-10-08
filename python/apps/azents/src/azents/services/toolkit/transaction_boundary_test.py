"""Toolkit service unit tests."""

import datetime
import json
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from azcommon.result import Failure, Success
from pydantic import BaseModel, ConfigDict

from azents.core.config import Config
from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_auth import GitHubUserProviderError
from azents.core.github_user_oauth import GitHubUserRegistration, GitHubUserRevocation
from azents.core.system_setting import SystemSettingFieldSource
from azents.core.tools import McpToolkitConfig, ResolveContext, Toolkit, ToolkitProvider
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.toolkit.data import ToolkitConfig
from azents.repos.toolkit_operations.data import (
    PlatformAuthorityRejected,
    ToolkitWithOAuth,
)
from azents.repos.toolkit_operations.owned import AgentToolkitOperationsRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.services.toolkit import ToolkitService, merge_envvar_credentials
from azents.services.toolkit.data import (
    InvalidConfig,
    InvalidCredentials,
    ToolkitCreateInput,
    ToolkitUpdateInput,
)


def _platform() -> ResolvedPlatformGitHubApp:
    """Build one resolved Platform App snapshot."""
    return ResolvedPlatformGitHubApp(
        app_id="123",
        client_id="client-id",
        private_key="private-key",
        client_secret="client-secret",
        app_id_source=SystemSettingFieldSource.ADMIN,
        effective_generation="generation-1",
    )


def _github_toolkit() -> ToolkitConfig:
    """Build one persisted Platform GitHub Toolkit."""
    now = datetime.datetime.now(datetime.UTC)
    return ToolkitConfig(
        owner_agent_id=None,
        id="toolkit-1",
        workspace_id="workspace-1",
        toolkit_type="github",
        slug="github",
        name="GitHub",
        config={},
        credentials=json.dumps(
            {
                "type": "github_app_platform",
                "app_id": "123",
                "installations": [
                    {
                        "installation_id": "456",
                        "account_login": "azents",
                        "account_type": "Organization",
                        "account_avatar_url": None,
                    }
                ],
            }
        ),
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=now,
        updated_at=now,
    )


class _DatabaseFreeConfig(BaseModel):
    """Typed provider configuration retaining irrelevant test metadata."""

    model_config = ConfigDict(extra="allow")


class _DatabaseFreeProvider(ToolkitProvider[_DatabaseFreeConfig]):
    """Provider double that observes the transaction boundary."""

    name = "GitHub"
    config_model = _DatabaseFreeConfig

    async def resolve(
        self, config: _DatabaseFreeConfig, context: ResolveContext
    ) -> Toolkit[_DatabaseFreeConfig]:
        """Fail if boundary tests accidentally execute a runtime Toolkit."""
        raise AssertionError(
            "Runtime Toolkit resolution is not part of credential validation"
        )

    def __init__(self, active: list[bool], events: list[str]) -> None:
        self.active = active
        self.events = events

    @classmethod
    def validate_config(cls, data: dict[str, object]) -> _DatabaseFreeConfig:
        """Accept the test configuration."""
        return _DatabaseFreeConfig.model_validate(data)

    def to_mcp_config(self, config: _DatabaseFreeConfig) -> McpToolkitConfig:
        """Return a non-OAuth projection for the boundary test."""
        del config
        return McpToolkitConfig(
            server_url="https://example.test",
            auth_type="none",
        )

    async def validate_credentials(
        self,
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Assert provider validation runs before repository mutation."""
        assert self.active == [False]
        assert credentials is not None
        assert credentials["app_id"] == "123"
        self.events.append("provider")
        return None


def test_envvar_merge_retains_historical_malformed_entry_skip_policy() -> None:
    """Decode only valid name identities without rejecting irrelevant metadata."""
    merged = merge_envvar_credentials(
        None,
        {"values": {"VALID": "secret", "REMOVED": "discard"}},
        {
            "entries": [{"name": "VALID", "masked": "historic"}, {"name": 1}, {}, None],
            "unknown_historical_metadata": {"unchanged": True},
        },
    )
    assert merged == {"values": {"VALID": "secret"}}


class TestMergeEnvVarCredentials:
    """EnvVar credential update behavior."""

    def test_preserves_existing_value_for_blank_edit(self) -> None:
        """Keep a stored value when its edit field is empty."""
        merged = merge_envvar_credentials(
            '{"values":{"AZENTS_POSTGRES_USER":"old-user","AZENTS_POSTGRES_PASSWORD":"old-password","AZENTS_POSTGRES_HOST":"old-host"}}',
            {
                "values": {
                    "AZENTS_POSTGRES_USER": "new-user",
                    "AZENTS_POSTGRES_PASSWORD": "new-password",
                    "AZENTS_POSTGRES_HOST": "",
                }
            },
            {
                "entries": [
                    {"name": "AZENTS_POSTGRES_USER"},
                    {"name": "AZENTS_POSTGRES_PASSWORD"},
                    {"name": "AZENTS_POSTGRES_HOST"},
                ]
            },
        )

        assert merged == {
            "values": {
                "AZENTS_POSTGRES_USER": "new-user",
                "AZENTS_POSTGRES_PASSWORD": "new-password",
                "AZENTS_POSTGRES_HOST": "old-host",
            }
        }

    def test_removes_value_when_its_entry_is_removed(self) -> None:
        """Discard stored values that no longer have a configured entry."""
        merged = merge_envvar_credentials(
            '{"values":{"AZENTS_POSTGRES_USER":"user","AZENTS_POSTGRES_HOST":"host"}}',
            {"values": {}},
            {"entries": [{"name": "AZENTS_POSTGRES_USER"}]},
        )

        assert merged == {"values": {"AZENTS_POSTGRES_USER": "user"}}

    async def test_config_only_update_removes_deleted_value(self) -> None:
        """Prune removed entry credentials without requiring a credentials payload."""
        old_config = {
            "entries": [
                {"name": "AZENTS_POSTGRES_USER"},
                {"name": "AZENTS_POSTGRES_HOST"},
            ]
        }
        new_config = {"entries": [{"name": "AZENTS_POSTGRES_USER"}]}
        existing = ToolkitConfig(
            owner_agent_id=None,
            id="toolkit-1",
            workspace_id="workspace-1",
            toolkit_type="envvar",
            slug="database",
            name="Database",
            config=old_config,
            credentials='{"values":{"AZENTS_POSTGRES_USER":"user","AZENTS_POSTGRES_HOST":"host"}}',
            enabled=True,
            always_expose_tools=False,
            revision=1,
            created_at=datetime.datetime.now(datetime.UTC),
            updated_at=datetime.datetime.now(datetime.UTC),
        )
        operations_repository = MagicMock()
        operations_repository.load_update_context = AsyncMock(
            return_value=Success(existing)
        )
        operations_repository.update = AsyncMock(return_value=Success(existing))
        operations_repository.get_oauth_summary = AsyncMock(return_value=None)
        service = ToolkitService(
            owned_operations=AsyncMock(spec=AgentToolkitOperationsRepository),
            operations_repository=operations_repository,
            toolkit_registry={},
            github_runtime=MagicMock(),
            github_user_oauth=AsyncMock(spec=GitHubUserOAuthService),
        )
        update: ToolkitUpdateInput = {"config": new_config}

        await service.update_by_id(
            "toolkit-1",
            update,
            workspace_id="workspace-1",
            user_id="user-1",
        )

        await_args = operations_repository.update.await_args
        assert await_args is not None
        repo_update = await_args.args[1]
        assert (
            repo_update["credentials"] == '{"values": {"AZENTS_POSTGRES_USER": "user"}}'
        )


async def test_create_external_validation_sees_no_repository_transaction() -> None:
    """Settings and provider validation finish before the DB mutation starts."""
    active = [False]
    events: list[str] = []
    provider = _DatabaseFreeProvider(active, events)
    runtime = MagicMock()

    async def resolve_platform() -> ResolvedPlatformGitHubApp:
        assert active == [False]
        events.append("settings")
        return _platform()

    runtime.resolve = AsyncMock(side_effect=resolve_platform)
    operations = MagicMock()

    async def create_toolkit(
        create: object,
        *,
        platform_authority: object,
    ) -> Success[ToolkitWithOAuth]:
        del create
        assert active == [False]
        active[0] = True
        try:
            events.append("repository")
            assert platform_authority is not None
            return Success(
                ToolkitWithOAuth(
                    toolkit=_github_toolkit(),
                    oauth_connection=None,
                )
            )
        finally:
            active[0] = False

    operations.create = AsyncMock(side_effect=create_toolkit)
    service = ToolkitService(
        owned_operations=AsyncMock(spec=AgentToolkitOperationsRepository),
        operations_repository=operations,
        toolkit_registry={"github": provider},
        github_runtime=runtime,
        github_user_oauth=AsyncMock(spec=GitHubUserOAuthService),
    )

    result = await service.create(
        ToolkitCreateInput(
            workspace_id="workspace-1",
            toolkit_type="github",
            name="GitHub",
            config={},
            credentials={
                "type": "github_app_platform",
                "installations": [
                    {
                        "installation_id": "456",
                        "account_login": "azents",
                        "account_type": "Organization",
                        "account_avatar_url": None,
                    }
                ],
            },
            always_expose_tools=False,
        ),
        user_id="user-1",
    )

    assert isinstance(result, Success)
    assert events == ["settings", "provider", "repository"]
    assert active == [False]


async def test_update_maps_final_platform_revalidation_failure() -> None:
    """A reconnect race after external validation cannot mutate the Toolkit."""
    provider = _DatabaseFreeProvider([False], [])
    runtime = MagicMock()
    runtime.resolve = AsyncMock(return_value=_platform())
    operations = MagicMock()
    operations.load_update_context = AsyncMock(return_value=Success(_github_toolkit()))
    operations.update = AsyncMock(
        return_value=Failure(
            PlatformAuthorityRejected("GitHub Platform App reconnect is required.")
        )
    )
    operations.get_oauth_summary = AsyncMock()
    service = ToolkitService(
        owned_operations=AsyncMock(spec=AgentToolkitOperationsRepository),
        operations_repository=operations,
        toolkit_registry={"github": provider},
        github_runtime=runtime,
        github_user_oauth=AsyncMock(spec=GitHubUserOAuthService),
    )

    result = await service.update_by_id(
        "toolkit-1",
        {
            "credentials": {
                "type": "github_app_platform",
                "installations": [
                    {
                        "installation_id": "456",
                        "account_login": "azents",
                        "account_type": "Organization",
                        "account_avatar_url": None,
                    }
                ],
            }
        },
        workspace_id="workspace-1",
        user_id="user-1",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, InvalidCredentials)
    assert result.error.detail == "GitHub Platform App reconnect is required."
    operations.get_oauth_summary.assert_not_awaited()


async def test_kubernetes_config_update_rejects_missing_replacement_credentials() -> (
    None
):
    """Reject Kubernetes config changes that would persist incomplete credentials."""
    existing = ToolkitConfig(
        owner_agent_id=None,
        id="toolkit-1",
        workspace_id="workspace-1",
        toolkit_type="kubernetes",
        slug="kubernetes",
        name="Kubernetes",
        config={
            "clusters": [
                {"name": "production", "auth_type": "token"},
            ]
        },
        credentials=json.dumps(
            {
                "clusters": {
                    "production": {
                        "type": "token",
                        "token": "stored-token",
                    }
                }
            }
        ),
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=datetime.datetime.now(datetime.UTC),
        updated_at=datetime.datetime.now(datetime.UTC),
    )
    operations = MagicMock()
    operations.load_update_context = AsyncMock(return_value=Success(existing))
    operations.update = AsyncMock(return_value=Success(existing))
    operations.get_oauth_summary = AsyncMock()
    service = ToolkitService(
        owned_operations=AsyncMock(spec=AgentToolkitOperationsRepository),
        operations_repository=operations,
        toolkit_registry={},
        github_runtime=MagicMock(),
        github_user_oauth=AsyncMock(spec=GitHubUserOAuthService),
    )

    result = await service.update_by_id(
        "toolkit-1",
        {
            "config": {
                "clusters": [
                    {"name": "production", "auth_type": "token"},
                    {"name": "staging", "auth_type": "token"},
                ]
            }
        },
        workspace_id="workspace-1",
        user_id="user-1",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, InvalidConfig)

    result = await service.update_by_id(
        "toolkit-1",
        {
            "config": {
                "clusters": [
                    {"name": "production", "auth_type": "kubeconfig"},
                ]
            }
        },
        workspace_id="workspace-1",
        user_id="user-1",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, InvalidConfig)
    operations.update.assert_not_awaited()


@pytest.mark.parametrize("owned", [False, True])
async def test_delete_finishes_locally_before_failed_revocation(
    owned: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Provider cleanup failure cannot reject shared or owned local deletion."""
    active = [False]
    committed = [False]
    target = GitHubUserRevocation(
        registration=GitHubUserRegistration(
            source="byoa_user",
            app_id="123",
            client_id="client-123",
            client_secret="private-client-secret",
            toolkit_revision=1,
            platform_generation=None,
        ),
        access_token="private-retired-token",
    )

    async def delete(
        *args: object, **kwargs: object
    ) -> Success[tuple[GitHubUserRevocation, ...]]:
        del args, kwargs
        active[0] = True
        committed[0] = True
        active[0] = False
        return Success((target,))

    async def revoke(*, client_id: str, client_secret: str, token: str) -> None:
        assert not active[0] and committed[0]
        assert client_id == "client-123"
        assert client_secret == "private-client-secret"
        assert token == "private-retired-token"
        raise GitHubUserProviderError(reason="provider_unavailable", status_code=503)

    provider = create_autospec(GitHubUserProvider, instance=True)
    provider.revoke.side_effect = revoke
    cleanup = GitHubUserOAuthService(
        repository=create_autospec(GitHubUserOAuthOperationRepository, instance=True),
        config=create_autospec(Config, instance=True),
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
        provider=provider,
    )
    operations, owned_operations = MagicMock(), MagicMock()
    operations.delete = AsyncMock(side_effect=delete)
    owned_operations.delete_agent_owned = AsyncMock(side_effect=delete)
    service = ToolkitService(
        operations_repository=operations,
        owned_operations=owned_operations,
        toolkit_registry={},
        github_runtime=MagicMock(),
        github_user_oauth=cleanup,
    )
    if owned:
        result = await service.delete_agent_owned(
            "agent-1",
            "toolkit-1",
            workspace_id="workspace-1",
            workspace_user_id="member-1",
            role=WorkspaceUserRole.OWNER,
        )
    else:
        result = await service.delete_by_id("toolkit-1", workspace_id="workspace-1")
    assert result == Success(None)
    assert committed == [True]
    provider.revoke.assert_awaited_once()
    assert "local completion is unchanged" in caplog.text
    assert "private-retired-token" not in caplog.text
    assert "private-client-secret" not in caplog.text
