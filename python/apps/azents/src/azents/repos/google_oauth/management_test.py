"""Real PostgreSQL candidate, publication, reconnect and secret-cleanup evidence."""

import asyncio
import dataclasses
import datetime
from typing import NamedTuple
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.google_oauth import (
    GoogleAttempt,
    GoogleAttemptStatus,
    GoogleCandidate,
    GoogleFinalSettings,
    GoogleIdentity,
    GoogleOAuthError,
    GoogleReconnectSettings,
    GoogleSetup,
    GoogleSubject,
    GoogleTokens,
)
from azents.core.google_policy import GoogleTask
from azents.core.google_system_setting import (
    GoogleApplicationConfig,
    GoogleApplicationRegistration,
    GoogleApplicationSecrets,
)
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingFieldSource,
    SystemSettingSection,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.system_setting_registry import get_system_setting_registry
from azents.rdb.models.google_oauth import RDBGoogleAttempt, RDBGoogleConnection
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.github_user_oauth.operations_test import _harness
from azents.repos.google_oauth.management import GoogleOAuthRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit.personal import PersonalToolkitRepository
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository


class Harness(NamedTuple):
    """Real SQL with detached authority collaborators and current registration."""

    repo: GoogleOAuthRepository
    subject: GoogleSubject
    registration: GoogleApplicationRegistration
    setup: GoogleSetup


async def _google(manager: SessionManager[WriteSession]) -> Harness:
    seed = await _harness(manager)
    payloads = Mock(spec=SystemSettingPayloadResolver)
    payloads.registry = get_system_setting_registry()
    payloads.resolve_current.return_value = ResolvedSystemSetting(
        section=SystemSettingSection.GOOGLE_OAUTH,
        schema_version=1,
        admin_version=0,
        config=GoogleApplicationConfig(client_id="client"),
        secrets=GoogleApplicationSecrets(client_secret="OPERATOR-SECRET"),
        field_sources={
            "client_id": SystemSettingFieldSource.ADMIN,
            "client_secret": SystemSettingFieldSource.ADMIN,
        },
        effective_generation="generation",
    )
    old = seed.repository
    repo = GoogleOAuthRepository(
        manager,
        seed.cipher,
        old.user_repository,
        old.session_repository,
        old.workspace_repository,
        old.workspace_user_repository,
        old.agent_repository,
        old.agent_admin_repository,
        SystemSettingRepository(),
        payloads,
        old.toolkit_repository,
        ToolkitNamespaceRepository(),
        PersonalToolkitRepository(seed.cipher),
    )
    subject = GoogleSubject(
        seed.requester.user_id,
        seed.requester.session_id,
        seed.requester.workspace_id,
        None,
    )
    registration = GoogleApplicationRegistration(
        "client",
        "OPERATOR-SECRET",
        "generation",
        "https://app.invalid/oauth/google/callback",
    )
    setup = GoogleSetup(
        client_id=registration.client_id,
        effective_generation=registration.effective_generation,
        redirect_uri=registration.redirect_uri,
        state_nonce="state-nonce",
        oidc_nonce="identity-nonce",
        code_verifier="x" * 43,
        tasks=(GoogleTask.CALENDAR_READ, GoogleTask.GMAIL_READ),
        timeout=30.0,
        target=None,
    )
    return Harness(repo, subject, registration, setup)


def _candidate(token: str) -> GoogleCandidate:
    return GoogleCandidate(
        identity=GoogleIdentity(
            issuer="https://accounts.google.com",
            subject="verified-google-subject",
            email="test@example.invalid",
        ),
        tokens=GoogleTokens(
            access_token=token,
            refresh_token="renew-" + token,
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(hours=1),
            granted_scopes=(
                "https://www.googleapis.com/auth/calendar.events.readonly",
            ),
        ),
        requested_scopes=("https://www.googleapis.com/auth/calendar.events.readonly",),
    )


def _settings() -> GoogleFinalSettings:
    return GoogleFinalSettings(
        name="Google reviewed",
        slug="google-reviewed",
        description=None,
        prompt=None,
        enabled=True,
        always_expose_tools=False,
        tasks=(GoogleTask.CALENDAR_READ,),
        timeout=30.0,
        security_risk_acknowledged=True,
    )


async def _review(h: Harness, target: str | None) -> GoogleAttempt:
    attempt = await h.repo.start(
        h.subject,
        registration=h.registration,
        setup=h.setup,
        target_toolkit_id=target,
    )
    await h.repo.claim(
        h.subject,
        attempt_id=attempt.id,
        nonce="state-nonce",
        registration=h.registration,
    )
    return await h.repo.stage(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        candidate=_candidate("candidate-access"),
    )


async def test_reconnect_missing_renewal_cannot_borrow_saved_token(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    first = await _review(h, None)
    saved = await h.repo.confirm(
        h.subject,
        attempt_id=first.id,
        registration=h.registration,
        settings=_settings(),
    )
    replacement = await h.repo.start(
        h.subject,
        registration=h.registration,
        setup=h.setup,
        target_toolkit_id=saved.toolkit_id,
    )
    await h.repo.claim(
        h.subject,
        attempt_id=replacement.id,
        nonce="state-nonce",
        registration=h.registration,
    )
    candidate = _candidate("nonrenewable-access")
    await h.repo.stage(
        h.subject,
        attempt_id=replacement.id,
        registration=h.registration,
        candidate=candidate.model_copy(
            update={
                "tokens": candidate.tokens.model_copy(update={"refresh_token": None})
            }
        ),
    )
    with pytest.raises(GoogleOAuthError) as caught:
        await h.repo.confirm(
            h.subject,
            attempt_id=replacement.id,
            registration=h.registration,
            settings=GoogleReconnectSettings(
                tasks=(GoogleTask.CALENDAR_READ,),
                timeout=30.0,
                security_risk_acknowledged=True,
            ),
        )
    assert caught.value.code == "no_usable_capability"
    current = await h.repo.saved(h.subject, saved.toolkit_id)
    assert current.connection is not None
    assert current.connection.id == saved.connection_id


async def test_only_confirm_publishes_and_exact_replay_has_one_outcome(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await _review(h, None)
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(sa.select(RDBGoogleConnection.id)) is None
        )
        row = await session.read_session.get(RDBGoogleAttempt, attempt.id)
        assert row is not None and row.encrypted_setup is not None
        assert "OPERATOR-SECRET" not in h.repo.cipher.decrypt(row.encrypted_setup)
    first = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    second = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    assert first == second and first.current
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count()).select_from(RDBGoogleConnection)
            )
            == 1
        )
        row = await session.read_session.get(RDBGoogleAttempt, attempt.id)
        assert row is not None and row.encrypted_setup is None
        assert row.encrypted_candidate is None
        toolkit = await session.read_session.get(RDBToolkitConfig, first.toolkit_id)
        assert toolkit is not None and toolkit.encrypted_credentials is None


async def test_cancel_and_late_callback_cannot_publish(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await h.repo.start(
        h.subject,
        registration=h.registration,
        setup=h.setup,
        target_toolkit_id=None,
    )
    assert await h.repo.cancel(h.subject, attempt.id) is None
    with pytest.raises(GoogleOAuthError):
        await h.repo.claim(
            h.subject,
            attempt_id=attempt.id,
            nonce="state-nonce",
            registration=h.registration,
        )
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBGoogleAttempt, attempt.id)
        assert row is not None and row.encrypted_setup is None
        assert (
            await session.read_session.scalar(sa.select(RDBGoogleConnection.id)) is None
        )


async def test_expiry_cleanup_commits_before_error(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await _review(h, None)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBGoogleAttempt)
            .where(
                RDBGoogleAttempt.id == attempt.id,
            )
            .values(
                expires_at=datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(seconds=1)
            )
        )
    with pytest.raises(GoogleOAuthError) as caught:
        await h.repo.load(h.subject, attempt.id)
    assert caught.value.code == "expired"
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBGoogleAttempt, attempt.id)
        assert row is not None and row.status is GoogleAttemptStatus.FAILED
        assert row.encrypted_candidate is None and row.encrypted_setup is None


async def test_reconnect_cancel_preserves_saved_grant_and_metadata(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    first = await _review(h, None)
    published = await h.repo.confirm(
        h.subject,
        attempt_id=first.id,
        registration=h.registration,
        settings=_settings(),
    )
    replacement = await _review(h, published.toolkit_id)
    await h.repo.cancel(h.subject, replacement.id)
    async with rdb_session_manager() as session:
        current = await session.read_session.scalar(sa.select(RDBGoogleConnection))
        assert current is not None and current.id == published.connection_id
        toolkit = await session.read_session.get(RDBToolkitConfig, published.toolkit_id)
        assert toolkit is not None and toolkit.name == "Google reviewed"


async def test_reconnect_replaces_identity_but_preserves_concurrent_metadata(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    first = await _review(h, None)
    published = await h.repo.confirm(
        h.subject,
        attempt_id=first.id,
        registration=h.registration,
        settings=_settings(),
    )
    replacement = await _review(h, published.toolkit_id)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(
                RDBToolkitConfig.id == published.toolkit_id,
            )
            .values(name="Concurrent rename", enabled=False)
        )
    changed = await h.repo.confirm(
        h.subject,
        attempt_id=replacement.id,
        registration=h.registration,
        settings=GoogleReconnectSettings(
            tasks=(GoogleTask.CALENDAR_READ,),
            timeout=12.0,
            security_risk_acknowledged=True,
        ),
    )
    assert changed.connection_id != published.connection_id
    async with rdb_session_manager() as session:
        toolkit = await session.read_session.get(RDBToolkitConfig, changed.toolkit_id)
        assert toolkit is not None and toolkit.name == "Concurrent rename"
        assert not toolkit.enabled
    outcome = await h.repo.cancel(h.subject, first.id)
    assert outcome is not None and not outcome.current


async def test_disconnect_defeats_pending_reconnect(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    first = await _review(h, None)
    published = await h.repo.confirm(
        h.subject,
        attempt_id=first.id,
        registration=h.registration,
        settings=_settings(),
    )
    replacement = await _review(h, published.toolkit_id)
    await h.repo.disconnect(h.subject, published.toolkit_id)
    with pytest.raises(GoogleOAuthError):
        await h.repo.confirm(
            h.subject,
            attempt_id=replacement.id,
            registration=h.registration,
            settings=GoogleReconnectSettings(
                tasks=(GoogleTask.CALENDAR_READ,),
                timeout=30.0,
                security_risk_acknowledged=True,
            ),
        )
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(sa.select(RDBGoogleConnection.id)) is None
        )


async def test_exact_initiating_login_context_is_required(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await _review(h, None)
    wrong = dataclasses.replace(h.subject, session_id="x" * 32)
    with pytest.raises(GoogleOAuthError):
        await h.repo.load(wrong, attempt.id)


async def test_published_outcome_does_not_depend_on_operator_registration(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await _review(h, None)
    published = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    assert (
        await h.repo.confirm(
            h.subject,
            attempt_id=attempt.id,
            registration=None,
            settings=_settings(),
        )
        == published
    )
    await h.repo.disconnect(h.subject, published.toolkit_id)
    assert not (await h.repo.outcome(h.subject, attempt.id)).current
    with pytest.raises(GoogleOAuthError):
        await h.repo.confirm(
            h.subject,
            attempt_id=attempt.id,
            registration=None,
            settings=_settings().model_copy(update={"name": "different"}),
        )


async def test_explicit_new_reconnect_after_disconnect_is_allowed(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await _review(h, None)
    old = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    await h.repo.disconnect(h.subject, old.toolkit_id)
    saved = await h.repo.saved(h.subject, old.toolkit_id)
    assert saved.connection is None
    replacement = await _review(h, old.toolkit_id)
    assert replacement.setup is not None and replacement.setup.target is not None
    assert replacement.setup.target.connection_id is None
    published = await h.repo.confirm(
        h.subject,
        attempt_id=replacement.id,
        registration=h.registration,
        settings=GoogleReconnectSettings(
            tasks=(GoogleTask.CALENDAR_READ,),
            timeout=30.0,
            security_risk_acknowledged=True,
        ),
    )
    assert published.current and published.toolkit_id == old.toolkit_id
    assert published.connection_id != old.connection_id


async def test_sibling_reconnect_cannot_replace_new_publication(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    first = await _review(h, None)
    published = await h.repo.confirm(
        h.subject,
        attempt_id=first.id,
        registration=h.registration,
        settings=_settings(),
    )
    sibling_a = await _review(h, published.toolkit_id)
    sibling_b = await _review(h, published.toolkit_id)
    final = GoogleReconnectSettings(
        tasks=(GoogleTask.CALENDAR_READ,),
        timeout=30.0,
        security_risk_acknowledged=True,
    )
    await h.repo.confirm(
        h.subject, attempt_id=sibling_a.id, registration=h.registration, settings=final
    )
    with pytest.raises(GoogleOAuthError) as caught:
        await h.repo.confirm(
            h.subject,
            attempt_id=sibling_b.id,
            registration=h.registration,
            settings=final,
        )
    assert caught.value.code == "stale"


@pytest.mark.parametrize("confirm_wins", [False, True])
async def test_confirm_cancel_serializes_independent_postgres_transactions(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    confirm_wins: bool,
) -> None:
    """Explicit barriers control ordering; no wall-clock sleeps establish the race."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    h = await _google(manager)
    try:
        attempt = await _review(h, None)
        locked = asyncio.Event()
        competitor = asyncio.Event()
        release = asyncio.Event()
        original = GoogleOAuthRepository._row

        async def gated(
            repo: GoogleOAuthRepository,
            session: WriteSession,
            subject: GoogleSubject,
            attempt_id: str,
        ) -> RDBGoogleAttempt:
            task = asyncio.current_task()
            if task is not None and task.get_name() == "google-winner":
                row = await original(repo, session, subject, attempt_id)
                locked.set()
                await release.wait()
                return row
            competitor.set()
            return await original(repo, session, subject, attempt_id)

        monkeypatch.setattr(GoogleOAuthRepository, "_row", gated)

        async def confirm() -> object:
            return await h.repo.confirm(
                h.subject,
                attempt_id=attempt.id,
                registration=h.registration,
                settings=_settings(),
            )

        async def cancel() -> object:
            return await h.repo.cancel(h.subject, attempt.id)

        async with asyncio.timeout(10):
            winner = asyncio.create_task(
                confirm() if confirm_wins else cancel(),
                name="google-winner",
            )
            await locked.wait()
            loser = asyncio.create_task(
                cancel() if confirm_wins else confirm(),
                name="google-competitor",
            )
            await competitor.wait()
            release.set()
            won = await winner
            if confirm_wins:
                assert await loser == won
            else:
                with pytest.raises(GoogleOAuthError):
                    await loser
        async with manager() as session:
            count = await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBGoogleConnection)
                .join(RDBToolkitConfig)
                .where(
                    RDBToolkitConfig.workspace_id == h.subject.workspace_id,
                )
            )
            assert count == int(confirm_wins)
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(
                    RDBWorkspace.id == h.subject.workspace_id,
                )
            )
