"""PostgreSQL witnesses for cancellation before and after known token receipt."""

import asyncio
import datetime
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
from azents.core.github_user_oauth import (
    GitHubUserCleanup,
    GitHubUserCleanupStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
)
from azents.rdb.models.github_user_oauth import RDBGitHubUserAttempt
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_oauth.guards import assert_mutation_allowed
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.github_user_oauth.operations_test import _harness
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth import service as service_module
from azents.services.github_user_oauth.exchange_owner import GitHubUserExchangeOwner
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService


@pytest.mark.parametrize("pause_at", ["provider", "capture"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_cancelled_caller_never_drops_admitted_or_received_token(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    pause_at: str,
    cleanup_fails: bool,
) -> None:
    h = await _harness(rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == h.requester.toolkit_id)
            .values(
                encrypted_credentials=h.cipher.encrypt(
                    json.dumps(
                        {
                            "type": "github_app_user",
                            "app_id": "123",
                            "private_key": "app-key",
                            "client_id": "Iv1.client",
                            "client_secret": "client-secret",
                        }
                    )
                )
            )
        )
    entered = asyncio.Event()
    release = asyncio.Event()
    provider = create_autospec(GitHubUserProvider, instance=True)
    provider.app.return_value = GitHubUserAppIdentity(
        app_id=123, slug="selected", client_id="Iv1.client"
    )
    provider.identity.return_value = GitHubUserIdentity(
        account_id=42, login="user", avatar_url=None
    )

    async def exchange(**kwargs: str) -> GitHubUserToken:
        if pause_at == "provider":
            entered.set()
            await release.wait()
        return GitHubUserToken(access_token="captured-issued-token")

    provider.exchange.side_effect = exchange
    provider.revoke.return_value = None
    if cleanup_fails:
        provider.revoke.side_effect = GitHubUserProviderError(
            reason="provider_unavailable", status_code=503
        )
    original_capture = GitHubUserOAuthOperationRepository.record_exchange_token

    async def capture(
        repository: GitHubUserOAuthOperationRepository,
        *,
        attempt_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
    ) -> GitHubUserCleanup | None:
        if pause_at == "capture":
            entered.set()
            await release.wait()
        return await original_capture(
            repository,
            attempt_id=attempt_id,
            registration=registration,
            access_token=access_token,
        )

    monkeypatch.setattr(
        GitHubUserOAuthOperationRepository, "record_exchange_token", capture
    )
    monkeypatch.setattr(service_module, "create_github_app_jwt", lambda *args: "jwt")
    service = GitHubUserOAuthService(
        repository=h.repository,
        config=Config.model_construct(web_url="https://azents.test"),
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
        provider=provider,
        exchange_owner=GitHubUserExchangeOwner(),
    )
    output = await service.connect(h.requester)
    state = parse_qs(urlsplit(output.authorization_url).query)["state"][0]
    caller = asyncio.create_task(
        service.exchange(h.requester, code="code", state=state)
    )
    await entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert service.exchange_owner.operations
    # Expiry is not proof that the still-owned receipt/capture has finished.
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBGitHubUserAttempt)
            .where(RDBGitHubUserAttempt.id == output.attempt_id)
            .values(expires_at=datetime.datetime.now(datetime.UTC))
        )
    with pytest.raises(GitHubUserOAuthError) as caught:
        await service.cancel(h.requester, attempt_id=output.attempt_id)
    assert caught.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    with pytest.raises(GitHubUserOAuthError):
        async with rdb_session_manager() as session:
            await assert_mutation_allowed(
                session,
                h.requester.toolkit_id,
                registration_changed=False,
                deleting=True,
            )
    release.set()
    await service.exchange_owner.drain()
    provider.exchange.assert_awaited_once()
    provider.revoke.assert_awaited_once_with(
        client_id="Iv1.client",
        client_secret="client-secret",
        token="captured-issued-token",
    )
    assert (await h.repository.read_context(requester=h.requester)).connection is None
    retired = await h.repository.list_cleanup(requester=h.requester)
    if cleanup_fails:
        assert len(retired) == 1
        assert retired[0].access_token == "captured-issued-token"
        assert retired[0].status is GitHubUserCleanupStatus.FAILED
        provider.revoke.side_effect = None
        await service.cleanup_retry(h.requester)
    else:
        assert retired == ()
    await h.repository.ensure_cleanup_complete(requester=h.requester)
    async with rdb_session_manager() as session:
        await assert_mutation_allowed(
            session, h.requester.toolkit_id, registration_changed=False, deleting=True
        )
    assert service.exchange_owner.operations == set()
