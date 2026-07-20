"""GitHub Platform Toolkit identity binding tests."""

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import azents.engine.tools.github as github_module
from azents.engine.tools.github import GitHubToolkitProvider


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
    provider = GitHubToolkitProvider(platform_app_id="123")
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
