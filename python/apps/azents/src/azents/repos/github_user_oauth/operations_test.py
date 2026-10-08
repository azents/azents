"""PostgreSQL evidence for one-use setup, activation and retirement boundaries."""

import dataclasses
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet

from azents.core.crypto import CredentialCipher
from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_oauth import (
    GitHubUserAttempt,
    GitHubUserCandidate,
    GitHubUserConnectionStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRequester,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserCleanup,
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_oauth.guards import assert_mutation_allowed, read_summary
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.session import SessionRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass(frozen=True)
class _Harness:
    repository: GitHubUserOAuthOperationRepository
    requester: GitHubUserRequester
    registration: GitHubUserRegistration
    cipher: CredentialCipher
    auth_session: AsyncMock


async def _harness(manager: SessionManager[WriteSession]) -> _Harness:
    """Use real SQL state with detached subject collaborators for focused tests."""
    cipher = CredentialCipher(Fernet.generate_key().decode())
    async with manager() as session:
        workspace = RDBWorkspace(name="OAuth test", handle="github-oauth-test")
        session.write_session.add(workspace)
        await session.write_session.flush()
        toolkit = RDBToolkitConfig(
            workspace_id=workspace.id,
            owner_agent_id=None,
            toolkit_type="github",
            slug="github",
            name="GitHub",
            config={"github_auth_type": "github_app_user"},
        )
        session.write_session.add(toolkit)
        await session.write_session.flush()
        requester = GitHubUserRequester(
            user_id="u" * 32,
            session_id="s" * 32,
            workspace_id=workspace.id,
            agent_id=None,
            toolkit_id=toolkit.id,
        )
    users = AsyncMock(spec=UserRepository)
    users.get.return_value = SimpleNamespace(access_disabled_at=None)
    auth_session = AsyncMock(spec=SessionRepository)
    auth_session.get.return_value = SimpleNamespace(
        user_id=requester.user_id, is_revoked=False, is_expired=False
    )
    members = AsyncMock(spec=WorkspaceUserRepository)
    members.get_by_workspace_and_user.return_value = SimpleNamespace(
        id="m" * 32, role=WorkspaceUserRole.OWNER
    )
    repo = GitHubUserOAuthOperationRepository(
        session_manager=manager,
        toolkit_repository=ToolkitRepository(cipher),
        cipher=cipher,
        user_repository=users,
        session_repository=auth_session,
        workspace_repository=WorkspaceRepository(),
        workspace_user_repository=members,
        agent_repository=AsyncMock(spec=AgentRepository),
        agent_admin_repository=AsyncMock(spec=AgentAdminRepository),
        system_setting_repository=AsyncMock(spec=SystemSettingRepository),
        setting_payloads=Mock(spec=SystemSettingPayloadResolver),
    )
    return _Harness(
        repo,
        requester,
        GitHubUserRegistration(
            source="byoa_user",
            app_id="123",
            client_id="Iv1.client",
            client_secret="client-secret",
            toolkit_revision=1,
            platform_generation=None,
        ),
        cipher,
        auth_session,
    )


async def _review(harness: _Harness, token: str) -> GitHubUserAttempt:
    repo, requester, registration = (
        harness.repository,
        harness.requester,
        harness.registration,
    )
    attempt = await repo.start(
        requester=requester,
        registration=registration,
        redirect_uri="https://azents.test/oauth/github/callback",
        nonce="nonce-" + token,
        code_verifier="verifier-" + token,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    await repo.claim_exchange(
        requester=requester,
        attempt_id=attempt.id,
        nonce="nonce-" + token,
        redirect_uri=attempt.redirect_uri,
    )
    assert (
        await repo.record_exchange_token(
            attempt_id=attempt.id, registration=registration, access_token=token
        )
        is None
    )
    return await repo.store_review(
        requester=requester,
        attempt_id=attempt.id,
        registration=registration,
        candidate=GitHubUserCandidate(
            access_token=token,
            account_id=42,
            account_login="connected-user",
            account_avatar_url=None,
        ),
    )


async def test_transfer_encrypts_token_and_claim_is_one_use(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    attempt = await _review(harness, "token-a")
    with pytest.raises(GitHubUserOAuthError) as error:
        await harness.repository.claim_exchange(
            requester=harness.requester,
            attempt_id=attempt.id,
            nonce="nonce-token-a",
            redirect_uri=attempt.redirect_uri,
        )
    assert error.value.code is GitHubUserErrorCode.STALE
    review = await harness.repository.read_review(
        requester=harness.requester, attempt_id=attempt.id
    )
    assert review.candidate is not None and review.candidate.account_id == 42
    connection = await harness.repository.confirm(
        requester=harness.requester,
        attempt_id=attempt.id,
        registration=harness.registration,
    )
    assert connection.access_token == "token-a"
    assert connection.registration.client_secret is None
    assert "token-a" not in repr(connection)
    assert await harness.repository.list_cleanup(requester=harness.requester) == ()
    async with rdb_session_manager() as session:
        stored = await session.read_session.scalar(
            sa.select(RDBGitHubUserConnection).where(
                RDBGitHubUserConnection.id == connection.id
            )
        )
        assert stored is not None and stored.encrypted_access_token != "token-a"
        assert harness.cipher.decrypt(stored.encrypted_access_token) == "token-a"
        setup = await session.read_session.scalar(
            sa.select(RDBGitHubUserAttempt).where(RDBGitHubUserAttempt.id == attempt.id)
        )
        assert setup is None
        summary = await read_summary(session, harness.requester.toolkit_id)
        assert summary is not None and summary.account_id == 42
        assert "token-a" not in repr(summary) and "client-secret" not in repr(summary)


async def test_replacement_retains_only_old_token_and_late_failure_is_conditional(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    first = await _review(h, "old-token")
    before = await h.repository.confirm(
        requester=h.requester, attempt_id=first.id, registration=h.registration
    )
    second = await _review(h, "new-token")
    after = await h.repository.confirm(
        requester=h.requester, attempt_id=second.id, registration=h.registration
    )
    assert after.id != before.id
    cleanups = await h.repository.list_cleanup(requester=h.requester)
    assert len(cleanups) == 1 and cleanups[0].access_token == "old-token"
    assert cleanups[0].registration.client_secret == "client-secret"
    await h.repository.mark_reconnect_required(
        requester=h.requester, connection_id=before.id, reason="invalid_token"
    )
    context = await h.repository.read_context(requester=h.requester)
    assert context.connection is not None and context.connection.id == after.id
    assert context.connection.status is GitHubUserConnectionStatus.CONNECTED
    await h.repository.mark_retired_failure(
        cleanup_id=cleanups[0].id, reason="provider_unavailable"
    )
    assert (await h.repository.list_cleanup(requester=h.requester))[
        0
    ].failure_reason == "provider_unavailable"
    async with rdb_session_manager() as session:
        with pytest.raises(GitHubUserOAuthError):
            await assert_mutation_allowed(
                session,
                h.requester.toolkit_id,
                registration_changed=True,
                deleting=False,
            )
    await h.repository.finish_retired(cleanup_id=cleanups[0].id)
    assert await h.repository.list_cleanup(requester=h.requester) == ()
    assert (
        await h.repository.read_context(requester=h.requester)
    ).connection is not None


async def test_cancel_during_exchange_accounts_for_late_issued_token(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    attempt = await h.repository.start(
        requester=h.requester,
        registration=h.registration,
        redirect_uri="https://azents.test/callback",
        nonce="nonce",
        code_verifier="verifier",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )
    await h.repository.claim_exchange(
        requester=h.requester,
        attempt_id=attempt.id,
        nonce="nonce",
        redirect_uri=attempt.redirect_uri,
    )
    await h.repository.cancel(requester=h.requester, attempt_id=attempt.id)
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.repository.disconnect(requester=h.requester, registration=None)
    assert error.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    assert (await h.repository.read_context(requester=h.requester)).cleanup_pending
    with pytest.raises(GitHubUserOAuthError):
        await h.repository.ensure_cleanup_complete(requester=h.requester)
    cleanup = await h.repository.record_exchange_token(
        attempt_id=attempt.id, registration=h.registration, access_token="late-token"
    )
    assert cleanup is not None and cleanup.access_token == "late-token"
    assert (await h.repository.read_context(requester=h.requester)).connection is None
    await h.repository.finish_retired(cleanup_id=cleanup.id)
    async with rdb_session_manager() as session:
        await assert_mutation_allowed(
            session, h.requester.toolkit_id, registration_changed=True, deleting=True
        )
        assert (
            await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt.id).where(
                    RDBGitHubUserAttempt.toolkit_id == h.requester.toolkit_id
                )
            )
            is None
        )


async def test_lost_authority_blocks_publication_but_not_issued_token_retirement(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    attempt = await _review(h, "candidate-token")
    h.auth_session.get.return_value = SimpleNamespace(
        user_id=h.requester.user_id, is_revoked=True, is_expired=False
    )
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.repository.confirm(
            requester=h.requester, attempt_id=attempt.id, registration=h.registration
        )
    assert error.value.code is GitHubUserErrorCode.AUTHORITY
    cleanup = await h.repository.retire_exchange_result(
        attempt_id=attempt.id,
        registration=h.registration,
        access_token="candidate-token",
        reason="lost_authority",
    )
    assert cleanup is not None
    await h.repository.finish_retired(cleanup_id=cleanup.id)
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
                sa.select(RDBGitHubUserCleanup.id).where(
                    RDBGitHubUserCleanup.toolkit_id == h.requester.toolkit_id
                )
            )
            is None
        )


async def test_same_toolkit_actual_token_transfer_is_not_revoked_until_disconnect(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    first = await _review(h, "same-token")
    await h.repository.confirm(
        requester=h.requester, attempt_id=first.id, registration=h.registration
    )
    candidate = await _review(h, "same-token")
    await h.repository.cancel(requester=h.requester, attempt_id=candidate.id)
    assert await h.repository.list_cleanup(requester=h.requester) == ()
    second = await _review(h, "same-token")
    await h.repository.confirm(
        requester=h.requester, attempt_id=second.id, registration=h.registration
    )
    assert await h.repository.list_cleanup(requester=h.requester) == ()
    await h.repository.disconnect(requester=h.requester, registration=None)
    assert (await h.repository.read_context(requester=h.requester)).connection is None
    cleanup = await h.repository.list_cleanup(requester=h.requester)
    assert len(cleanup) == 1 and cleanup[0].access_token == "same-token"
    assert cleanup[0].registration.client_secret is None


async def test_wrong_session_and_registration_revision_cannot_claim(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    attempt = await h.repository.start(
        requester=h.requester,
        registration=h.registration,
        redirect_uri="https://azents.test/callback",
        nonce="nonce",
        code_verifier="verifier",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )
    other = dataclasses.replace(h.requester, session_id="x" * 32)
    with pytest.raises(GitHubUserOAuthError):
        await h.repository.claim_exchange(
            requester=other,
            attempt_id=attempt.id,
            nonce="nonce",
            redirect_uri=attempt.redirect_uri,
        )
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == h.requester.toolkit_id)
            .values(revision=2)
        )
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.repository.claim_exchange(
            requester=h.requester,
            attempt_id=attempt.id,
            nonce="nonce",
            redirect_uri=attempt.redirect_uri,
        )
    assert error.value.code is GitHubUserErrorCode.STALE


async def test_known_token_cancel_prunes_setup_and_late_identity_cannot_republish(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    attempt = await h.repository.start(
        requester=h.requester,
        registration=h.registration,
        redirect_uri="https://azents.test/callback",
        nonce="nonce",
        code_verifier="verifier",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )
    await h.repository.claim_exchange(
        requester=h.requester,
        attempt_id=attempt.id,
        nonce="nonce",
        redirect_uri=attempt.redirect_uri,
    )
    assert (
        await h.repository.record_exchange_token(
            attempt_id=attempt.id,
            registration=h.registration,
            access_token="received",
        )
        is None
    )
    async with rdb_session_manager() as session:
        saved = await session.read_session.scalar(
            sa.select(RDBGitHubUserAttempt).where(RDBGitHubUserAttempt.id == attempt.id)
        )
        assert saved is not None and not saved.exchange_in_flight
        assert saved.encrypted_issued_token is not None
    await h.repository.cancel(requester=h.requester, attempt_id=attempt.id)
    cleanup = await h.repository.list_cleanup(requester=h.requester)
    assert len(cleanup) == 1 and cleanup[0].access_token == "received"
    await h.repository.finish_retired(cleanup_id=cleanup[0].id)
    with pytest.raises(GitHubUserOAuthError):
        await h.repository.store_review(
            requester=h.requester,
            attempt_id=attempt.id,
            registration=h.registration,
            candidate=GitHubUserCandidate(
                access_token="received",
                account_id=42,
                account_login="late-identity",
                account_avatar_url=None,
            ),
        )
    assert (
        await h.repository.retire_exchange_result(
            attempt_id=attempt.id,
            registration=h.registration,
            access_token="received",
            reason="late_identity",
        )
        is None
    )
    assert await h.repository.list_cleanup(requester=h.requester) == ()
    assert (await h.repository.read_context(requester=h.requester)).connection is None
    await h.repository.ensure_cleanup_complete(requester=h.requester)
