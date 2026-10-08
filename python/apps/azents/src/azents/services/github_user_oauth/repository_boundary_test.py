"""Actual PostgreSQL/service witnesses for cancellation after token receipt."""

import asyncio
import json
from unittest.mock import create_autospec
from urllib.parse import parse_qs, urlsplit

import pytest
import sqlalchemy as sa

from azents.core.config import Config
from azents.core.github_user_auth import (
    GitHubUserAppIdentity,
    GitHubUserIdentity,
    GitHubUserToken,
)
from azents.core.github_user_oauth import GitHubUserOAuthError
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_oauth.operations_test import _harness
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth import service as service_module
from azents.services.github_user_oauth.exchange_owner import GitHubUserExchangeOwner
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService


@pytest.mark.parametrize("cancel_task", [False, True])
async def test_received_token_cancel_is_complete_without_late_duplicate_revocation(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    cancel_task: bool,
) -> None:
    """A received code result is durable, not an indefinitely unknown exchange."""
    harness = await _harness(rdb_session_manager)
    async with rdb_session_manager() as session:
        toolkit = await session.read_session.scalar(
            sa.select(RDBToolkitConfig).where(
                RDBToolkitConfig.id == harness.requester.toolkit_id
            )
        )
        assert toolkit is not None
        toolkit.encrypted_credentials = harness.cipher.encrypt(
            json.dumps(
                {
                    "type": "github_app_user",
                    "app_id": "123",
                    "private_key": "private-key",
                    "client_id": "Iv1.client",
                    "client_secret": "client-secret",
                }
            )
        )
    entered = asyncio.Event()
    release = asyncio.Event()
    captured: list[str] = []
    provider = create_autospec(GitHubUserProvider, instance=True)
    provider.app.return_value = GitHubUserAppIdentity(
        app_id=123, slug="selected-app", client_id="Iv1.client"
    )
    provider.exchange.return_value = GitHubUserToken(access_token="issued-token")

    async def identity(token: str) -> GitHubUserIdentity:
        assert token == "issued-token"
        entered.set()
        await release.wait()
        return GitHubUserIdentity(
            account_id=42, login="connected-user", avatar_url=None
        )

    async def revoke(*, client_id: str, client_secret: str, token: str) -> None:
        assert client_id == "Iv1.client" and client_secret == "client-secret"
        captured.append(token)

    provider.identity.side_effect = identity
    provider.revoke.side_effect = revoke
    monkeypatch.setattr(service_module, "create_github_app_jwt", lambda *args: "jwt")
    service = GitHubUserOAuthService(
        repository=harness.repository,
        config=Config.model_construct(web_url="https://azents.test"),
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
        provider=provider,
        exchange_owner=GitHubUserExchangeOwner(),
    )
    output = await service.connect(harness.requester)
    state = parse_qs(urlsplit(output.authorization_url).query)["state"][0]
    task = asyncio.create_task(
        service.exchange(harness.requester, code="code", state=state)
    )
    await entered.wait()
    if cancel_task:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await service.cancel(harness.requester, attempt_id=output.attempt_id)
    await harness.repository.ensure_cleanup_complete(requester=harness.requester)
    assert (
        await harness.repository.read_context(requester=harness.requester)
    ).connection is None
    assert captured == ["issued-token"]
    release.set()
    if not cancel_task:
        with pytest.raises(GitHubUserOAuthError):
            await task
    await service.exchange_owner.drain()
    assert captured == ["issued-token"]
    assert await harness.repository.list_cleanup(requester=harness.requester) == ()
