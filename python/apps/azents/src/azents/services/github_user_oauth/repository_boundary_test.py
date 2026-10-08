"""PostgreSQL witnesses for fail-open removal and stale late results."""

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
    GitHubUserProviderError,
    GitHubUserToken,
)
from azents.core.github_user_oauth import GitHubUserOAuthError
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_oauth.operations_test import _harness
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth import service as service_module
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService


@pytest.mark.parametrize("remove_parent", [False, True])
async def test_late_received_token_cannot_activate_after_local_removal(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    remove_parent: bool,
) -> None:
    h = await _harness(rdb_session_manager)
    async with rdb_session_manager() as session:
        toolkit = await session.read_session.get(
            RDBToolkitConfig, h.requester.toolkit_id
        )
        assert toolkit is not None
        toolkit.encrypted_credentials = h.cipher.encrypt(
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
    entered, release = asyncio.Event(), asyncio.Event()
    captured: list[str] = []
    provider = create_autospec(GitHubUserProvider, instance=True)
    provider.app.return_value = GitHubUserAppIdentity(
        app_id=123, slug="selected", client_id="Iv1.client"
    )
    provider.exchange.return_value = GitHubUserToken(access_token="issued-token")

    async def identity(token: str) -> GitHubUserIdentity:
        entered.set()
        await release.wait()
        return GitHubUserIdentity(account_id=42, login="user", avatar_url=None)

    async def revoke(*, client_id: str, client_secret: str, token: str) -> None:
        assert client_id == "Iv1.client" and client_secret == "client-secret"
        captured.append(token)
        raise GitHubUserProviderError(reason="provider_unavailable", status_code=503)

    provider.identity.side_effect = identity
    provider.revoke.side_effect = revoke
    monkeypatch.setattr(service_module, "create_github_app_jwt", lambda *args: "jwt")
    service = GitHubUserOAuthService(
        repository=h.repository,
        config=Config.model_construct(web_url="https://azents.test"),
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
        provider=provider,
    )
    output = await service.connect(h.requester)
    state = parse_qs(urlsplit(output.authorization_url).query)["state"][0]
    task = asyncio.create_task(service.exchange(h.requester, code="code", state=state))
    await entered.wait()
    if remove_parent:
        async with rdb_session_manager() as session:
            await session.write_session.execute(
                sa.delete(RDBToolkitConfig).where(
                    RDBToolkitConfig.id == h.requester.toolkit_id
                )
            )
    else:
        await service.cancel(h.requester, attempt_id=output.attempt_id)
    release.set()
    with pytest.raises(GitHubUserOAuthError):
        await task
    assert captured == ["issued-token"]
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBGitHubUserConnection.id).where(
                    RDBGitHubUserConnection.toolkit_id == h.requester.toolkit_id
                )
            )
            is None
        )
        assert (
            await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt.id).where(
                    RDBGitHubUserAttempt.toolkit_id == h.requester.toolkit_id
                )
            )
            is None
        )


async def test_failed_revocation_does_not_leave_local_rows_or_block_parent_delete(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = await _harness(rdb_session_manager)
    async with rdb_session_manager() as session:
        toolkit = await session.read_session.get(
            RDBToolkitConfig, h.requester.toolkit_id
        )
        assert toolkit is not None
        toolkit.encrypted_credentials = h.cipher.encrypt(
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
    provider = create_autospec(GitHubUserProvider, instance=True)
    provider.app.return_value = GitHubUserAppIdentity(
        app_id=123, slug="selected", client_id="Iv1.client"
    )
    provider.exchange.return_value = GitHubUserToken(access_token="user-token")
    provider.identity.return_value = GitHubUserIdentity(
        account_id=42, login="user", avatar_url=None
    )
    provider.revoke.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=503
    )
    monkeypatch.setattr(service_module, "create_github_app_jwt", lambda *args: "jwt")
    service = GitHubUserOAuthService(
        repository=h.repository,
        config=Config.model_construct(web_url="https://azents.test"),
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
        provider=provider,
    )
    output = await service.connect(h.requester)
    state = parse_qs(urlsplit(output.authorization_url).query)["state"][0]
    await service.exchange(h.requester, code="code", state=state)
    await service.confirm(h.requester, attempt_id=output.attempt_id)
    await service.disconnect(h.requester)
    assert (await h.repository.read_context(requester=h.requester)).connection is None
    provider.revoke.assert_awaited_once_with(
        client_id="Iv1.client", client_secret="client-secret", token="user-token"
    )
    assert provider.identity.await_count == 1
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.delete(RDBToolkitConfig).where(
                RDBToolkitConfig.id == h.requester.toolkit_id
            )
        )
        assert (
            await session.read_session.get(RDBToolkitConfig, h.requester.toolkit_id)
            is None
        )
