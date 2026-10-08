"""PostgreSQL lifecycle evidence for staged authorization and fail-open removal."""

import dataclasses
import datetime
import json
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
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_oauth.guards import (
    assert_registration_change_allowed,
    capture_and_clear_user_tokens,
    read_summary,
)
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
    """Real SQL state with detached current-subject collaborators."""
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


async def _start(h: _Harness, label: str) -> GitHubUserAttempt:
    result = await h.repository.start(
        requester=h.requester,
        registration=h.registration,
        redirect_uri="https://azents.test/callback",
        nonce="nonce-" + label,
        code_verifier="verifier-" + label,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    assert result.revocations == ()
    return result.attempt


async def _review(h: _Harness, token: str) -> GitHubUserAttempt:
    attempt = await _start(h, token)
    await h.repository.claim_exchange(
        requester=h.requester,
        attempt_id=attempt.id,
        nonce="nonce-" + token,
        redirect_uri=attempt.redirect_uri,
    )
    return await h.repository.store_review(
        requester=h.requester,
        attempt_id=attempt.id,
        registration=h.registration,
        candidate=GitHubUserCandidate(
            access_token=token,
            account_id=42,
            account_login="connected-user",
            account_avatar_url=None,
        ),
    )


async def _save_credentials(
    manager: SessionManager[WriteSession],
    h: _Harness,
    *,
    app_id: str = "123",
    client_id: str = "Iv1.client",
) -> None:
    credentials = {
        "type": "github_app_user",
        "app_id": app_id,
        "private_key": "private-key",
        "client_id": client_id,
        "client_secret": "current-secret",
    }
    async with manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == h.requester.toolkit_id)
            .values(encrypted_credentials=h.cipher.encrypt(json.dumps(credentials)))
        )


async def test_one_use_review_and_transfer_are_encrypted_and_redacted(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    attempt = await _review(h, "token-a")
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.repository.claim_exchange(
            requester=h.requester,
            attempt_id=attempt.id,
            nonce="nonce-token-a",
            redirect_uri=attempt.redirect_uri,
        )
    assert error.value.code is GitHubUserErrorCode.STALE
    assert (
        await h.repository.read_review(requester=h.requester, attempt_id=attempt.id)
    ).candidate is not None
    result = await h.repository.confirm(
        requester=h.requester, attempt_id=attempt.id, registration=h.registration
    )
    assert result.revocations == ()
    connection = result.connection
    assert (
        connection.access_token == "token-a"
        and connection.registration.client_secret is None
    )
    assert "token-a" not in repr(result) and "client-secret" not in repr(result)
    async with rdb_session_manager() as session:
        stored = await session.read_session.scalar(
            sa.select(RDBGitHubUserConnection).where(
                RDBGitHubUserConnection.id == connection.id
            )
        )
        assert stored is not None and stored.encrypted_access_token != "token-a"
        assert h.cipher.decrypt(stored.encrypted_access_token) == "token-a"
        assert (
            await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt.id).where(
                    RDBGitHubUserAttempt.id == attempt.id
                )
            )
            is None
        )
        summary = await read_summary(session, h.requester.toolkit_id)
        assert summary is not None and summary.account_id == 42
        assert "token-a" not in repr(summary) and "client-secret" not in repr(summary)
        assert not hasattr(summary, "cleanup_pending")


async def test_confirm_returns_old_token_transiently_and_late_failure_is_conditional(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    first = await _review(h, "old-token")
    before = (
        await h.repository.confirm(
            requester=h.requester, attempt_id=first.id, registration=h.registration
        )
    ).connection
    second = await _review(h, "new-token")
    result = await h.repository.confirm(
        requester=h.requester, attempt_id=second.id, registration=h.registration
    )
    after = result.connection
    assert after.id != before.id
    assert len(result.revocations) == 1
    assert result.revocations[0].access_token == "old-token"
    assert result.revocations[0].registration.client_secret == "client-secret"
    await h.repository.mark_reconnect_required(
        requester=h.requester, connection_id=before.id, reason="authentication_failed"
    )
    current = (await h.repository.read_context(requester=h.requester)).connection
    assert current is not None and current.id == after.id
    assert current.status is GitHubUserConnectionStatus.CONNECTED
    async with rdb_session_manager() as session:
        rows = (
            await session.read_session.scalars(
                sa.select(RDBGitHubUserConnection).where(
                    RDBGitHubUserConnection.toolkit_id == h.requester.toolkit_id
                )
            )
        ).all()
        assert (
            len(rows) == 1
            and h.cipher.decrypt(rows[0].encrypted_access_token) == "new-token"
        )


async def test_cancel_returns_review_token_and_preserves_working_connection(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    first = await _review(h, "working")
    active = (
        await h.repository.confirm(
            requester=h.requester, attempt_id=first.id, registration=h.registration
        )
    ).connection
    reviewed = await _review(h, "discarded")
    targets = await h.repository.cancel(requester=h.requester, attempt_id=reviewed.id)
    assert len(targets) == 1 and targets[0].access_token == "discarded"
    assert (await h.repository.read_context(requester=h.requester)).connection == active
    assert (
        await h.repository.cancel(requester=h.requester, attempt_id=reviewed.id) == ()
    )
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBGitHubUserAttempt.id).where(
                    RDBGitHubUserAttempt.toolkit_id == h.requester.toolkit_id
                )
            )
            is None
        )


async def test_supersession_returns_known_candidate_without_blocking_new_setup(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    old = await _review(h, "discarded")
    result = await h.repository.start(
        requester=h.requester,
        registration=h.registration,
        redirect_uri="https://azents.test/callback",
        nonce="new-nonce",
        code_verifier="new-verifier",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )
    assert result.attempt.id != old.id
    assert (
        len(result.revocations) == 1
        and result.revocations[0].access_token == "discarded"
    )
    with pytest.raises(GitHubUserOAuthError):
        await h.repository.confirm(
            requester=h.requester, attempt_id=old.id, registration=h.registration
        )


async def test_exchanging_cancel_and_parent_delete_cannot_block_or_activate_late_result(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    attempt = await _start(h, "late")
    await h.repository.claim_exchange(
        requester=h.requester,
        attempt_id=attempt.id,
        nonce="nonce-late",
        redirect_uri=attempt.redirect_uri,
    )
    assert await h.repository.cancel(requester=h.requester, attempt_id=attempt.id) == ()
    assert await h.repository.disconnect(requester=h.requester, registration=None) == ()
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.delete(RDBToolkitConfig).where(
                RDBToolkitConfig.id == h.requester.toolkit_id
            )
        )
    with pytest.raises(GitHubUserOAuthError):
        await h.repository.store_review(
            requester=h.requester,
            attempt_id=attempt.id,
            registration=h.registration,
            candidate=GitHubUserCandidate(
                access_token="late-known",
                account_id=42,
                account_login="late",
                account_avatar_url=None,
            ),
        )
    target = await h.repository.received_revocation(
        toolkit_id=h.requester.toolkit_id,
        registration=h.registration,
        access_token="late-known",
    )
    assert target is not None and target.access_token == "late-known"
    assert target.registration == h.registration
    await h.repository.complete_failed_exchange(attempt_id=attempt.id)


async def test_atomic_delete_captures_active_candidate_and_same_app_secret(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    first = await _review(h, "active")
    await h.repository.confirm(
        requester=h.requester, attempt_id=first.id, registration=h.registration
    )
    await _review(h, "candidate")
    await _save_credentials(rdb_session_manager, h)
    async with rdb_session_manager() as session:
        targets = await capture_and_clear_user_tokens(
            session, h.requester.toolkit_id, None, cipher=h.cipher
        )
        assert {target.access_token for target in targets} == {"active", "candidate"}
        active = next(target for target in targets if target.access_token == "active")
        assert active.registration.client_secret == "current-secret"
        await session.write_session.execute(
            sa.delete(RDBToolkitConfig).where(
                RDBToolkitConfig.id == h.requester.toolkit_id
            )
        )
    # The returned facts survive parent removal, without a persistent retry row.
    assert {target.registration.app_id for target in targets} == {"123"}
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


async def test_current_different_app_secret_never_changes_captured_revocation_identity(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    reviewed = await _review(h, "original")
    await h.repository.confirm(
        requester=h.requester, attempt_id=reviewed.id, registration=h.registration
    )
    await _save_credentials(
        rdb_session_manager, h, app_id="456", client_id="other-client"
    )
    targets = await h.repository.disconnect(
        requester=h.requester,
        registration=dataclasses.replace(
            h.registration,
            app_id="456",
            client_id="other-client",
            client_secret="other-secret",
        ),
    )
    assert len(targets) == 1 and targets[0].access_token == "original"
    assert targets[0].registration.app_id == "123"
    assert targets[0].registration.client_id == "Iv1.client"
    assert targets[0].registration.client_secret is None
    assert (await h.repository.read_context(requester=h.requester)).connection is None


async def test_actual_same_toolkit_token_transfer_is_not_revoked_until_disconnect(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    first = await _review(h, "same")
    await h.repository.confirm(
        requester=h.requester, attempt_id=first.id, registration=h.registration
    )
    second = await _review(h, "same")
    assert await h.repository.cancel(requester=h.requester, attempt_id=second.id) == ()
    assert (
        await h.repository.received_revocation(
            toolkit_id=h.requester.toolkit_id,
            registration=h.registration,
            access_token="same",
        )
        is None
    )
    third = await _review(h, "same")
    assert (
        await h.repository.confirm(
            requester=h.requester, attempt_id=third.id, registration=h.registration
        )
    ).revocations == ()
    targets = await h.repository.disconnect(
        requester=h.requester, registration=h.registration
    )
    assert len(targets) == 1 and targets[0].access_token == "same"
    assert (await h.repository.read_context(requester=h.requester)).connection is None


async def test_context_session_revision_and_active_provider_identity_remain_fail_closed(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    attempt = await _start(h, "context")
    with pytest.raises(GitHubUserOAuthError):
        await h.repository.claim_exchange(
            requester=dataclasses.replace(h.requester, session_id="x" * 32),
            attempt_id=attempt.id,
            nonce="nonce-context",
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
            nonce="nonce-context",
            redirect_uri=attempt.redirect_uri,
        )
    assert error.value.code is GitHubUserErrorCode.STALE
    await h.repository.cancel(requester=h.requester, attempt_id=attempt.id)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == h.requester.toolkit_id)
            .values(revision=1)
        )
    active = await _review(h, "active")
    async with rdb_session_manager() as session:
        with pytest.raises(GitHubUserOAuthError) as error:
            await assert_registration_change_allowed(session, h.requester.toolkit_id)
        assert error.value.code is GitHubUserErrorCode.STALE
    await h.repository.confirm(
        requester=h.requester, attempt_id=active.id, registration=h.registration
    )
    h.auth_session.get.return_value = SimpleNamespace(
        user_id=h.requester.user_id, is_revoked=True, is_expired=False
    )
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.repository.disconnect(requester=h.requester, registration=None)
    assert error.value.code is GitHubUserErrorCode.AUTHORITY


async def test_schema_has_no_cleanup_state_and_plain_pat_removal_returns_no_targets(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _harness(rdb_session_manager)
    async with rdb_session_manager() as session:
        assert (
            await capture_and_clear_user_tokens(
                session, h.requester.toolkit_id, None, cipher=h.cipher
            )
            == ()
        )
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == h.requester.toolkit_id)
            .values(config={"github_auth_type": "pat"})
        )
        assert (
            await capture_and_clear_user_tokens(
                session, h.requester.toolkit_id, None, cipher=h.cipher
            )
            == ()
        )
        assert (
            await session.read_session.scalar(
                sa.text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name = 'github_user_oauth_cleanup'"
                )
            )
            == 0
        )
        columns = (
            await session.read_session.scalars(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'github_user_oauth_attempts'"
                )
            )
        ).all()
        assert (
            "encrypted_issued_token" not in columns
            and "exchange_in_flight" not in columns
        )
        foreign_key = next(
            iter(RDBGitHubUserConnection.__table__.c.toolkit_id.foreign_keys)
        )
        assert foreign_key.ondelete == "CASCADE"
        foreign_key = next(
            iter(RDBGitHubUserAttempt.__table__.c.toolkit_id.foreign_keys)
        )
        assert foreign_key.ondelete == "CASCADE"
