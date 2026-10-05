"""OAuth failure-write authority and provider once-only boundary under contention."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

import azents.services.external_account_oauth.link_service as link_service_module
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalAccountOAuthAttemptStatus,
    ExternalChannelAppMode,
    ExternalChannelProvider,
)
from azents.core.external_account_link import (
    ExternalAccountLinkView,
    ExternalAccountOAuthAlreadyConsumed,
)
from azents.core.external_account_oauth import (
    ExternalAccountOAuthCallbackContext,
    ExternalAccountOAuthClientConfiguration,
    ExternalAccountOAuthIdentity,
    ExternalAccountOAuthRuntimeConfiguration,
)
from azents.core.system_setting import (
    SystemSettingEnvironment,
    SystemSettingGenerationHasher,
)
from azents.core.system_setting_registry import get_system_setting_registry
from azents.rdb.models.external_account_link import RDBExternalAccountLink
from azents.rdb.models.external_account_oauth import RDBExternalAccountOAuthAttempt
from azents.rdb.models.user import RDBUser
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.external_account_oauth.configuration_fence_test import (
    _wait_for_blocked,
)
from azents.repos.external_channel.contention_wait_test import (
    _FixedAttempts,
    _FixedLinks,
)
from azents.repos.external_channel.final_authority_fence_test import _authority
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.services.external_account_oauth.link_service import (
    ExternalAccountOAuthService,
)
from azents.services.external_account_oauth.service import (
    ExternalAccountOAuthAttemptService,
)
from azents.services.external_account_oauth_system_setting.service import (
    ExternalAccountOAuthSystemSettingService,
)


@pytest.mark.parametrize("mismatch", ["user", "auth", "provider", "generation", "uri"])
async def test_mismatched_unavailable_actor_cannot_terminalize_claimed_attempt(
    rdb_engine: AsyncEngine, latest_db_schema: None, mismatch: str
) -> None:
    """Acquisition cannot grant failure-write authority over another exact context."""
    writes = create_read_write_session_manager(rdb_engine)
    links = _FixedLinks(writes, SystemSettingRepository())
    now = datetime.now(UTC)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        async with writes() as session:
            attempt = RDBExternalAccountOAuthAttempt(
                state_hash=uuid4().hex,
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                provider=fixture.actor.provider,
                setting_generation="observed-generation",
                redirect_uri="https://example.test/callback",
                encrypted_pkce_verifier=None,
                status=ExternalAccountOAuthAttemptStatus.CLAIMED,
                expires_at=now + timedelta(minutes=10),
                claimed_at=now,
                completed_at=None,
                failed_at=None,
                failure_code=None,
            )
            session.write_session.add(attempt)
            await session.write_session.flush()
            attempt_id = attempt.id
            await session.write_session.execute(
                sa.update(RDBUser)
                .where(RDBUser.id == fixture.user_id)
                .values(access_disabled_at=now)
            )
        try:
            result = await links.finalize_oauth_link(
                attempt_id=attempt_id,
                user_id=uuid4().hex if mismatch == "user" else fixture.user_id,
                auth_session_id=uuid4().hex
                if mismatch == "auth"
                else fixture.auth_session_id,
                provider=ExternalChannelProvider.DISCORD
                if mismatch == "provider"
                else fixture.actor.provider,
                setting_generation="other-generation"
                if mismatch == "generation"
                else "observed-generation",
                redirect_uri="https://other.test/callback"
                if mismatch == "uri"
                else "https://example.test/callback",
                identity=ExternalAccountOAuthIdentity(
                    provider=fixture.actor.provider,
                    identity_scope=fixture.actor.provider_tenant_id,
                    provider_user_id=fixture.actor.provider_user_id,
                    provider_tenant_id=None,
                    provider_tenant_display_label=None,
                    provider_display_label="Must not change",
                ),
                now=now,
            )
            assert result.link is None and result.failure_code == "invalid_attempt"
            async with writes() as session:
                untouched = await session.read_session.get(
                    RDBExternalAccountOAuthAttempt, attempt_id
                )
                assert untouched is not None
                assert untouched.status is ExternalAccountOAuthAttemptStatus.CLAIMED
                assert untouched.failed_at is None and untouched.failure_code is None
                link = await session.read_session.get(
                    RDBExternalAccountLink, fixture.link_id
                )
                assert link is not None and link.provider_display_label == "Synthetic"
        finally:
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExternalAccountOAuthAttempt).where(
                        RDBExternalAccountOAuthAttempt.id == attempt_id
                    )
                )


async def test_exchange_is_once_while_finalization_waits_and_duplicate_claim_loses(
    rdb_engine: AsyncEngine, latest_db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One claimant exchanges once; waiting never replays the provider code."""
    writes = create_read_write_session_manager(rdb_engine)
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher(key)
    settings_repository = SystemSettingRepository()
    attempts_repository = _FixedAttempts(
        writes,
        settings_repository,
        get_system_setting_registry(),
        cipher,
        SystemSettingEnvironment(values={}),
        SystemSettingGenerationHasher(key),
    )
    attempts = ExternalAccountOAuthAttemptService(attempts_repository, cipher)
    links = _FixedLinks(writes, settings_repository)
    settings = AsyncMock(spec=ExternalAccountOAuthSystemSettingService)
    settings.config = None
    callback = ExternalAccountOAuthCallbackContext(
        setting_generation="observed-generation",
        redirect_uri="https://example.test/callback",
    )
    settings.resolve_callback_context.return_value = callback
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        settings.resolve_runtime.return_value = (
            ExternalAccountOAuthRuntimeConfiguration(
                client=ExternalAccountOAuthClientConfiguration(
                    provider=fixture.actor.provider,
                    client_id="test-client",
                    client_secret="test-only",
                ),
                setting_generation=callback.setting_generation,
                redirect_uri=callback.redirect_uri,
            )
        )
        adapter = AsyncMock()
        adapter.exchange_identity.return_value = ExternalAccountOAuthIdentity(
            provider=fixture.actor.provider,
            identity_scope=fixture.actor.provider_tenant_id,
            provider_user_id=fixture.actor.provider_user_id,
            provider_tenant_id=None,
            provider_tenant_display_label=None,
            provider_display_label="Once only",
        )
        monkeypatch.setattr(link_service_module, "_adapter", lambda *_: adapter)
        service = ExternalAccountOAuthService(attempts, links, settings)
        started = await attempts.create(
            user_id=fixture.user_id,
            auth_session_id=fixture.auth_session_id,
            provider=fixture.actor.provider,
            setting_generation=callback.setting_generation,
            redirect_uri=callback.redirect_uri,
            use_pkce=False,
        )

        async def exchange() -> ExternalAccountLinkView:
            return await service.exchange(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                provider=fixture.actor.provider,
                code="test-once-code",
                state=started.state,
            )

        pending = duplicate = None
        try:
            async with writes() as holder:
                await holder.write_session.scalar(
                    sa.select(RDBExternalAccountLink)
                    .where(RDBExternalAccountLink.id == fixture.link_id)
                    .with_for_update()
                )
                holder_pid = await holder.write_session.scalar(
                    sa.select(sa.func.pg_backend_pid())
                )
                assert isinstance(holder_pid, int)
                pending = asyncio.create_task(exchange())
                await _wait_for_blocked(rdb_engine, holder_pid)
                adapter.exchange_identity.assert_awaited_once()
                duplicate = asyncio.create_task(exchange())
                await holder.write_session.commit()
                result = await asyncio.wait_for(pending, timeout=3)
                assert result.id == fixture.link_id
                with pytest.raises(ExternalAccountOAuthAlreadyConsumed):
                    await asyncio.wait_for(duplicate, timeout=3)
                adapter.exchange_identity.assert_awaited_once()
            async with writes() as observer:
                current = await observer.read_session.get(
                    RDBExternalAccountOAuthAttempt, started.attempt.id
                )
                assert (
                    current is not None
                    and current.status is ExternalAccountOAuthAttemptStatus.COMPLETED
                )
        finally:
            for task in (pending, duplicate):
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExternalAccountOAuthAttempt).where(
                        RDBExternalAccountOAuthAttempt.id == started.attempt.id
                    )
                )
