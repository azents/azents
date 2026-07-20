"""GitHub Platform Toolkit identity binding tests."""

import json
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import azents.engine.tools.github as github_module
from azents.core.tools import GitHubToolkitConfig, ResolveContext
from azents.engine.tools.github import GitHubToolkitProvider
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)


def _resolved(
    *, app_id: str, private_key: str, generation: str
) -> ResolvedPlatformGitHubApp:
    return ResolvedPlatformGitHubApp(
        app_id=app_id,
        client_id="client-id",
        private_key=private_key,
        client_secret="client-secret",
        effective_generation=generation,
    )


def _context() -> ResolveContext:
    return ResolveContext(
        toolkit_id="toolkit-1",
        toolkit_name="GitHub",
        credentials_json=json.dumps(
            {
                "type": "github_app_platform",
                "app_id": "123",
                "installations": [
                    {
                        "installation_id": "456",
                        "account_login": "azents-test",
                        "account_type": "Organization",
                        "account_avatar_url": None,
                    }
                ],
            }
        ),
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        session=None,
        web_url="",
        oauth_secret_key="",
        workspace_id="workspace-1",
        workspace_handle="workspace",
    )


async def test_platform_credentials_use_server_app_id_for_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Browser-provided App identity is overwritten before validation/storage."""
    calls: list[tuple[str, str, int]] = []

    class InstallationRepository:
        async def has_access(
            self,
            _session: AsyncSession,
            user_id: str,
            platform_app_id: str,
            installation_id: int,
        ) -> bool:
            calls.append((user_id, platform_app_id, installation_id))
            return True

    monkeypatch.setattr(
        github_module,
        "GithubUserInstallationRepository",
        InstallationRepository,
    )
    runtime = cast(Any, Mock())
    runtime.resolve = AsyncMock(
        return_value=_resolved(
            app_id="123",
            private_key="private-key",
            generation="generation-1",
        )
    )
    provider = GitHubToolkitProvider(
        platform_runtime=cast(PlatformGitHubAppRuntimeService, runtime)
    )
    credentials: dict[str, object] = {
        "type": "github_app_platform",
        "app_id": "browser-controlled",
        "installations": [
            {
                "installation_id": "456",
                "account_login": "azents-test",
                "account_type": "Organization",
                "account_avatar_url": None,
            }
        ],
    }

    error = await provider.validate_credentials(
        cast(AsyncSession, object()),
        "user-1",
        credentials,
    )

    assert error is None
    assert credentials["app_id"] == "123"
    assert calls == [("user-1", "123", 456)]


async def test_platform_token_issuance_rechecks_app_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed App ID blocks token exchange for an existing binding."""
    runtime = cast(Any, Mock())
    runtime.resolve = AsyncMock(
        side_effect=[
            _resolved(
                app_id="123",
                private_key="initial-private-key",
                generation="generation-1",
            ),
            _resolved(
                app_id="999",
                private_key="rotated-private-key",
                generation="generation-2",
            ),
        ]
    )
    exchange = AsyncMock(return_value="token")
    monkeypatch.setattr(github_module, "_exchange_app_token", exchange)
    provider = GitHubToolkitProvider(
        platform_runtime=cast(PlatformGitHubAppRuntimeService, runtime)
    )
    toolkit = await provider.resolve(
        GitHubToolkitConfig(
            github_auth_type="github_app_platform",
            inject_runtime_environment=True,
        ),
        _context(),
    )

    with pytest.raises(ValueError, match="reconnect is required"):
        await toolkit.expose_env()

    exchange.assert_not_awaited()


async def test_platform_token_issuance_uses_rotated_key_for_same_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same-App private-key rotation preserves the persisted binding."""
    runtime = cast(Any, Mock())
    runtime.resolve = AsyncMock(
        side_effect=[
            _resolved(
                app_id="123",
                private_key="initial-private-key",
                generation="generation-1",
            ),
            _resolved(
                app_id="123",
                private_key="rotated-private-key",
                generation="generation-2",
            ),
        ]
    )
    exchange = AsyncMock(return_value="token")
    monkeypatch.setattr(github_module, "_exchange_app_token", exchange)
    provider = GitHubToolkitProvider(
        platform_runtime=cast(PlatformGitHubAppRuntimeService, runtime)
    )
    toolkit = await provider.resolve(
        GitHubToolkitConfig(
            github_auth_type="github_app_platform",
            inject_runtime_environment=True,
        ),
        _context(),
    )

    env = await toolkit.expose_env()

    assert env["GITHUB_TOKEN_INSTALLATION_456"] == "token"
    exchange.assert_awaited_once_with("123", "rotated-private-key", "456")
