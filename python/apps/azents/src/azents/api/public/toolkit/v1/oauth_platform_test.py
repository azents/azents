"""Platform GitHub OAuth operation-boundary tests."""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

import azents.api.public.toolkit.v1.oauth as oauth_module
from azents.api.public.toolkit.v1.oauth import (
    GitHubPlatformInstallationsRequest,
    get_github_platform_installations,
)
from azents.core.auth.deps import WorkspaceMember
from azents.core.config import Config
from azents.core.oauth2 import create_platform_oauth_state
from azents.rdb.session import SessionManager
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)


async def test_changed_generation_rejects_callback_before_code_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed effective setting stops OAuth before any GitHub token call."""
    member = cast(Any, Mock())
    member.has_permission.return_value = True
    config = cast(Any, Mock())
    config.credential_encryption.key = "oauth-state-key"
    state = create_platform_oauth_state(
        config.credential_encryption.key,
        effective_generation="generation-before",
    )
    runtime = cast(Any, Mock())
    runtime.resolve = AsyncMock(
        return_value=ResolvedPlatformGitHubApp(
            app_id="123",
            client_id="client-id",
            private_key="private-key",
            client_secret="client-secret",
            effective_generation="generation-after",
        )
    )
    exchange = AsyncMock()
    monkeypatch.setattr(oauth_module, "exchange_oauth_code", exchange)

    with pytest.raises(HTTPException) as raised:
        await get_github_platform_installations(
            cast(WorkspaceMember, member),
            cast(Config, config),
            cast(PlatformGitHubAppRuntimeService, runtime),
            cast(SessionManager[Any], object()),
            GitHubPlatformInstallationsRequest(code="code", state=state),
            handle="workspace",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail == {
        "code": "system_setting_changed",
        "message": "Platform GitHub App settings changed. Restart OAuth.",
    }
    exchange.assert_not_awaited()
