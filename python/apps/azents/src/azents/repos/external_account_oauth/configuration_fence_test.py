"""Identity OAuth configuration publication orders exact claim/finalization."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from psycopg.errors import LockNotAvailable
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_oauth import ExternalAccountOAuthIdentity
from azents.core.system_setting import (
    SystemSettingEnvironment,
    SystemSettingGenerationHasher,
    SystemSettingSection,
)
from azents.core.system_setting_data import SystemSettingCurrentWrite
from azents.core.system_setting_registry import get_system_setting_registry
from azents.rdb.models.external_account_oauth import RDBExternalAccountOAuthAttempt
from azents.rdb.models.session import RDBSession
from azents.rdb.models.system_setting import RDBSystemSetting
from azents.rdb.models.user import RDBUser
from azents.rdb.session_capabilities import (
    ReadSession,
    create_read_write_session_manager,
)
from azents.repos.external_account_link import (
    ExternalAccountLinkRepository,
    ExternalAccountOAuthFinalizeResult,
)
from azents.repos.external_account_oauth.data import ExternalAccountOAuthAttemptCreate
from azents.repos.external_account_oauth.repository import (
    ExternalAccountOAuthAttemptRepository,
)
from azents.repos.runtime_web.nonblocking_management_test import _committed_authority
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.user import UserRepository


@pytest.mark.parametrize("held", ["user", "auth", "attempt"])
async def test_oauth_claim_contention_refuses_before_consumption_and_releases_guards(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    held: str,
) -> None:
    """Each partial security-lock collision rolls back without admitting exchange."""
    writes = create_read_write_session_manager(rdb_engine)
    key = Fernet.generate_key().decode()
    settings = SystemSettingRepository()
    section = SystemSettingSection.DISCORD_IDENTITY_OAUTH

    class FixedGenerationAttempts(ExternalAccountOAuthAttemptRepository):
        async def _current_setting_generation(
            self, session: ReadSession, *, section: SystemSettingSection
        ) -> str:
            return "observed-generation"

    attempts = FixedGenerationAttempts(
        writes,
        settings,
        get_system_setting_registry(),
        CredentialCipher(key),
        SystemSettingEnvironment(values={}),
        SystemSettingGenerationHasher(key),
    )
    now = datetime.now(UTC)
    async with _committed_authority(rdb_engine) as fixture:
        async with writes() as session:
            auth = await SessionRepository().create(
                session,
                SessionCreate(
                    user_id=fixture.user_id,
                    refresh_token=uuid4().hex,
                    expires_at=now + timedelta(hours=1),
                    max_expires_at=None,
                    user_agent=None,
                    ip_address=None,
                ),
            )
        attempt = await attempts.create(
            create=ExternalAccountOAuthAttemptCreate(
                id=uuid4().hex,
                state_hash=uuid4().hex,
                user_id=fixture.user_id,
                auth_session_id=auth.id,
                provider=ExternalChannelProvider.DISCORD,
                setting_generation="observed-generation",
                redirect_uri="https://example.test/callback",
                encrypted_pkce_verifier=None,
                expires_at=now + timedelta(minutes=10),
            )
        )
        try:
            async with writes() as holder:
                if held == "user":
                    await holder.write_session.scalar(
                        sa.select(RDBUser)
                        .where(RDBUser.id == fixture.user_id)
                        .with_for_update()
                    )
                elif held == "auth":
                    await holder.write_session.scalar(
                        sa.select(RDBSession)
                        .where(RDBSession.id == auth.id)
                        .with_for_update()
                    )
                else:
                    await holder.write_session.scalar(
                        sa.select(RDBExternalAccountOAuthAttempt)
                        .where(RDBExternalAccountOAuthAttempt.id == attempt.id)
                        .with_for_update()
                    )
                with pytest.raises(DBAPIError) as failure:
                    await asyncio.wait_for(
                        attempts.claim_open(
                            state_hash=attempt.state_hash,
                            user_id=fixture.user_id,
                            auth_session_id=auth.id,
                            provider=attempt.provider,
                            setting_generation=attempt.setting_generation,
                            redirect_uri=attempt.redirect_uri,
                            now=now,
                        ),
                        timeout=2,
                    )
                assert isinstance(failure.value.orig, LockNotAvailable)
                # A separate section writer may proceed while the original holder
                # still owns its row: the failed claim retained no partial guard.
                async with writes() as observer:
                    await asyncio.wait_for(
                        settings.acquire_section_lock(observer, section=section),
                        timeout=2,
                    )
                    untouched = await observer.read_session.get(
                        RDBExternalAccountOAuthAttempt, attempt.id
                    )
                    assert untouched is not None
                    assert untouched.status.value == "open"
                    assert untouched.claimed_at is None
        finally:
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExternalAccountOAuthAttempt).where(
                        RDBExternalAccountOAuthAttempt.id == attempt.id
                    )
                )


async def test_cleanup_deletes_only_bounded_expired_rows_without_read_locks(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Expired deletion is conditional SQL, not a capability claim or read gate."""
    writes = create_read_write_session_manager(rdb_engine)
    key = Fernet.generate_key().decode()
    attempts = ExternalAccountOAuthAttemptRepository(
        writes,
        SystemSettingRepository(),
        get_system_setting_registry(),
        CredentialCipher(key),
        SystemSettingEnvironment(values={}),
        SystemSettingGenerationHasher(key),
    )
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=30)
    async with _committed_authority(rdb_engine) as fixture:
        async with writes() as session:
            auth = await SessionRepository().create(
                session,
                SessionCreate(
                    user_id=fixture.user_id,
                    refresh_token=uuid4().hex,
                    expires_at=now + timedelta(hours=1),
                    max_expires_at=None,
                    user_agent=None,
                    ip_address=None,
                ),
            )
        ids = []
        for expired in [True, True, True, False]:
            created = await attempts.create(
                create=ExternalAccountOAuthAttemptCreate(
                    id=uuid4().hex,
                    state_hash=uuid4().hex,
                    user_id=fixture.user_id,
                    auth_session_id=auth.id,
                    provider=ExternalChannelProvider.DISCORD,
                    setting_generation="synthetic",
                    redirect_uri="https://example.test/callback",
                    encrypted_pkce_verifier=None,
                    expires_at=(
                        cutoff - timedelta(minutes=1)
                        if expired
                        else now + timedelta(minutes=10)
                    ),
                )
            )
            ids.append(created.id)
        observed = []

        def capture(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            observed.append(statement)

        try:
            async with AsyncSession(rdb_engine) as holder:
                assert (
                    await holder.scalar(
                        sa.select(RDBExternalAccountOAuthAttempt)
                        .where(RDBExternalAccountOAuthAttempt.id == ids[-1])
                        .with_for_update()
                    )
                    is not None
                )
                event.listen(rdb_engine.sync_engine, "before_cursor_execute", capture)
                try:
                    first = await asyncio.wait_for(
                        attempts.cleanup(cutoff=cutoff, limit=2), timeout=2
                    )
                    assert first.deleted_count == 2
                    second = await asyncio.wait_for(
                        attempts.cleanup(cutoff=cutoff, limit=2), timeout=2
                    )
                    assert second.deleted_count == 1
                finally:
                    event.remove(
                        rdb_engine.sync_engine, "before_cursor_execute", capture
                    )
                assert all("FOR UPDATE" not in sql for sql in observed)
                async with writes() as session:
                    retained = (
                        await session.read_session.scalars(
                            sa.select(RDBExternalAccountOAuthAttempt.id).where(
                                RDBExternalAccountOAuthAttempt.id.in_(ids)
                            )
                        )
                    ).all()
                    assert retained == [ids[-1]]
        finally:
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExternalAccountOAuthAttempt).where(
                        RDBExternalAccountOAuthAttempt.id.in_(ids)
                    )
                )


@pytest.mark.parametrize(
    ("boundary", "change"),
    [
        ("claim", "configuration"),
        ("finalize", "configuration"),
        ("finalize", "disable"),
        ("finalize", "revoke"),
    ],
)
async def test_auth_configuration_write_waits_for_exact_oauth_boundary(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    boundary: str,
    change: str,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher(key)
    hasher = SystemSettingGenerationHasher(key)
    registry = get_system_setting_registry()
    environment = SystemSettingEnvironment(values={})
    settings = SystemSettingRepository()
    now = datetime.now(UTC)
    section = SystemSettingSection.DISCORD_IDENTITY_OAUTH
    gate = asyncio.Event()
    release = asyncio.Event()

    class PausedAttempts(ExternalAccountOAuthAttemptRepository):
        async def _current_setting_generation(
            self, session: ReadSession, *, section: SystemSettingSection
        ) -> str:
            gate.set()
            await release.wait()
            return "observed-generation"

    class PausedLinks(ExternalAccountLinkRepository):
        async def _current_setting_generation(
            self, session: ReadSession, *, section: SystemSettingSection
        ) -> str:
            gate.set()
            await release.wait()
            return "observed-generation"

    async with _committed_authority(rdb_engine) as fixture:
        async with writes() as session:
            auth = await SessionRepository().create(
                session,
                SessionCreate(
                    user_id=fixture.user_id,
                    refresh_token=uuid4().hex,
                    expires_at=now + timedelta(hours=1),
                    max_expires_at=None,
                    user_agent=None,
                    ip_address=None,
                ),
            )
        attempts = PausedAttempts(
            writes, settings, registry, cipher, environment, hasher
        )
        attempt = await attempts.create(
            create=ExternalAccountOAuthAttemptCreate(
                id=uuid4().hex,
                state_hash=uuid4().hex,
                user_id=fixture.user_id,
                auth_session_id=auth.id,
                provider=ExternalChannelProvider.DISCORD,
                setting_generation="observed-generation",
                redirect_uri="https://example.test/callback",
                encrypted_pkce_verifier=None,
                expires_at=now + timedelta(minutes=10),
            )
        )
        links = PausedLinks(writes, settings, registry, cipher, environment, hasher)
        if boundary == "finalize":
            release.set()
            assert (
                await attempts.claim_open(
                    state_hash=attempt.state_hash,
                    user_id=fixture.user_id,
                    auth_session_id=auth.id,
                    provider=attempt.provider,
                    setting_generation=attempt.setting_generation,
                    redirect_uri=attempt.redirect_uri,
                    now=now,
                )
                is not None
            )
            release.clear()
            gate.clear()

        async def perform_boundary() -> object:
            if boundary == "claim":
                return await attempts.claim_open(
                    state_hash=attempt.state_hash,
                    user_id=fixture.user_id,
                    auth_session_id=auth.id,
                    provider=attempt.provider,
                    setting_generation=attempt.setting_generation,
                    redirect_uri=attempt.redirect_uri,
                    now=now,
                )
            return await links.finalize_oauth_link(
                attempt_id=attempt.id,
                user_id=fixture.user_id,
                auth_session_id=auth.id,
                provider=attempt.provider,
                setting_generation=attempt.setting_generation,
                redirect_uri=attempt.redirect_uri,
                identity=ExternalAccountOAuthIdentity(
                    provider=attempt.provider,
                    identity_scope="global",
                    provider_user_id=uuid4().hex,
                    provider_tenant_id=None,
                    provider_tenant_display_label=None,
                    provider_display_label="Synthetic",
                ),
                now=now,
            )

        attempted_write = asyncio.Event()

        def observe(
            _connection: object,
            _cursor: object,
            statement: str,
            parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            expected = {
                "configuration": "pg_advisory_xact_lock",
                "disable": "UPDATE users",
                "revoke": "UPDATE sessions",
            }[change]
            if expected in statement:
                attempted_write.set()

        async def change_configuration() -> None:
            async with writes() as session:
                if change == "disable":
                    await UserRepository().disable_access(
                        session, fixture.user_id, disabled_at=now
                    )
                    return
                if change == "revoke":
                    await SessionRepository().revoke(session, auth.id)
                    return
                current = await settings.get_current(session, section=section)
                await settings.write_current(
                    session,
                    write=SystemSettingCurrentWrite(
                        section=section,
                        schema_version=1,
                        version=1 if current is None else current.version + 1,
                        config={},
                        encrypted_secrets=None,
                        secret_metadata={},
                        validation_status=None,
                        validated_generation=None,
                        validation_metadata=None,
                        validated_at=None,
                        updated_by_user_id=None,
                    ),
                )

        task = asyncio.create_task(perform_boundary())
        changed = None
        try:
            await asyncio.wait_for(gate.wait(), timeout=2)
            event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
            changed = asyncio.create_task(change_configuration())
            await asyncio.wait_for(attempted_write.wait(), timeout=2)
            assert not changed.done()
            release.set()
            result = await asyncio.wait_for(task, timeout=3)
            assert result is not None
            if boundary == "finalize":
                assert isinstance(result, ExternalAccountOAuthFinalizeResult)
                assert result.link is not None
            await asyncio.wait_for(changed, timeout=3)
        finally:
            release.set()
            event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
            for pending in [task, changed]:
                if pending is not None and not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExternalAccountOAuthAttempt).where(
                        RDBExternalAccountOAuthAttempt.id == attempt.id
                    )
                )
                # Restore only the synthetic identity-section row in the disposable DB.
                await session.write_session.execute(
                    sa.delete(RDBSystemSetting).where(
                        RDBSystemSetting.section == section
                    )
                )
