"""Platform GitHub OAuth operation-boundary tests."""

from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import HTTPException

import azents.services.toolkit_oauth.service as service_module
from azents.api.public.toolkit.v1.oauth import (
    GitHubPlatformInstallationsRequest,
    get_github_platform_installations,
)
from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.roles import get_permissions_for_role
from azents.core.config import Config, CredentialEncryptionConfig
from azents.core.enums import WorkspaceUserRole
from azents.core.oauth2 import create_platform_oauth_state
from azents.core.system_setting import SystemSettingFieldSource
from azents.repos.toolkit_oauth_operations import ToolkitOAuthOperationRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.toolkit_oauth.service import ToolkitOAuthService


async def test_changed_generation_rejects_callback_before_code_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed effective setting stops OAuth before any GitHub token call."""
    member = WorkspaceMember(
        user_id="user-1",
        session_id="session-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions=get_permissions_for_role(WorkspaceUserRole.OWNER),
    )
    config = Config.model_construct(
        credential_encryption=CredentialEncryptionConfig(key="oauth-state-key")
    )
    state = create_platform_oauth_state(
        config.credential_encryption.key,
        effective_generation="generation-before",
    )
    runtime = create_autospec(PlatformGitHubAppRuntimeService, instance=True)
    runtime.resolve = AsyncMock(
        return_value=ResolvedPlatformGitHubApp(
            app_id="123",
            client_id="client-id",
            private_key="private-key",
            client_secret="client-secret",
            app_id_source=SystemSettingFieldSource.ADMIN,
            effective_generation="generation-after",
        )
    )
    exchange = AsyncMock()
    monkeypatch.setattr(service_module, "exchange_oauth_code", exchange)
    repository = create_autospec(ToolkitOAuthOperationRepository, instance=True)
    service = ToolkitOAuthService(
        repository=repository,
        config=config,
        registry={},
        platform_runtime=runtime,
    )

    with pytest.raises(HTTPException) as raised:
        await get_github_platform_installations(
            member,
            service,
            GitHubPlatformInstallationsRequest(code="code", state=state),
            handle="workspace",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail == {
        "code": "system_setting_changed",
        "message": "Platform GitHub App settings changed. Restart OAuth.",
    }
    exchange.assert_not_awaited()
    repository.sync_installations.assert_not_awaited()
