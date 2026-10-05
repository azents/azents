"""Blocking external security fences retain current authority and one-time writes."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalAccountOAuthAttemptStatus,
    ExternalChannelAppMode,
    ExternalChannelProvider,
)
from azents.core.external_account_oauth import ExternalAccountOAuthIdentity
from azents.core.external_model_settings import (
    ExternalModelApplied,
    ExternalModelBusy,
    ExternalModelEditorReady,
    ExternalModelRejected,
    ExternalModelSettingsRejectionCode,
)
from azents.core.system_setting import (
    SystemSettingEnvironment,
    SystemSettingGenerationHasher,
    SystemSettingSection,
)
from azents.core.system_setting_registry import get_system_setting_registry
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_account_link import RDBExternalAccountLink
from azents.rdb.models.external_account_oauth import RDBExternalAccountOAuthAttempt
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
)
from azents.rdb.models.external_model_settings import (
    RDBExternalModelDraft,
    RDBExternalModelMutation,
)
from azents.rdb.models.session import RDBSession
from azents.rdb.models.user import RDBUser
from azents.rdb.session_capabilities import (
    ReadSession,
    create_read_write_session_manager,
)
from azents.repos.external_account_link import (
    ExternalAccountLinkRepository,
    ExternalAccountOAuthFinalizeResult,
)
from azents.repos.external_account_oauth.configuration_fence_test import (
    _wait_for_blocked,
)
from azents.repos.external_account_oauth.data import ExternalAccountOAuthAttemptCreate
from azents.repos.external_account_oauth.repository import (
    ExternalAccountOAuthAttemptRepository,
)
from azents.repos.external_channel.final_authority_fence_test import (
    _authority,
    _local_option_repository,
)
from azents.repos.external_channel.model_settings_data import ExternalModelApplyCommit
from azents.repos.system_setting.repository import SystemSettingRepository


@pytest.mark.parametrize(
    "held",
    [
        "draft",
        "connection",
        "route",
        "resource",
        "binding",
        "advisory",
        "principal",
        "user",
        "link",
        "agent",
        "session",
        "grant",
    ],
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_apply_waits_on_each_guard_and_cancellation_releases_partial_rows(
    rdb_engine: AsyncEngine, latest_db_schema: None, held: str, cancel: bool
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    repository = _local_option_repository(rdb_engine)
    statements: list[str] = []

    def observe(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        now = datetime.now(UTC)
        opened = await repository.open_editor(
            actor=fixture.actor,
            target=fixture.target,
            owner_interaction_key="wait-open",
            now=now,
            offset=0,
            limit=10,
        )
        assert isinstance(opened, ExternalModelEditorReady)

        async def apply() -> ExternalModelApplyCommit:
            return await repository.apply_draft(
                actor=fixture.actor,
                draft_id=opened.editor.draft.id,
                expected_selection_fingerprint=opened.editor.draft.selection_fingerprint,
                apply_interaction_key="wait-apply",
                now=now,
            )

        async with writes() as holder:
            binding = await holder.read_session.get(
                RDBExternalChannelBinding, fixture.target.binding_id
            )
            assert binding is not None
            rows = {
                "draft": (RDBExternalModelDraft, opened.editor.draft.id),
                "connection": (RDBExternalChannelConnection, fixture.connection_id),
                "route": (RDBExternalChannelAgentRoute, binding.route_id),
                "resource": (RDBExternalChannelResource, binding.resource_id),
                "binding": (RDBExternalChannelBinding, fixture.target.binding_id),
                "principal": (RDBExternalChannelPrincipal, fixture.principal_id),
                "user": (RDBUser, fixture.user_id),
                "link": (RDBExternalAccountLink, fixture.link_id),
                "agent": (RDBAgent, fixture.agent_id),
                "session": (RDBAgentSession, fixture.target.session_id),
                "grant": (RDBExternalChannelAccessGrant, fixture.grant_id),
            }
            if held == "advisory":
                channels = repository.external_channel_repository
                fence = channels.acquire_principal_agent_authorization_fence
                await fence(
                    holder,
                    agent_id=fixture.agent_id,
                    principal_id=fixture.principal_id,
                )
            else:
                model, row_id = rows[held]
                await holder.write_session.scalar(
                    sa.select(model).where(model.id == row_id).with_for_update()
                )
            holder_pid = await holder.write_session.scalar(
                sa.select(sa.func.pg_backend_pid())
            )
            assert isinstance(holder_pid, int)
            event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
            pending = asyncio.create_task(apply())
            try:
                await _wait_for_blocked(rdb_engine, holder_pid)
                if cancel:
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                    # A cancelled operation releases its draft even while a later
                    # holder still owns the original authority guard.
                    if held != "draft":
                        async with writes() as observer:
                            await observer.write_session.execute(
                                sa.text("SET LOCAL lock_timeout = '250ms'")
                            )
                            await observer.write_session.scalar(
                                sa.select(RDBExternalModelDraft)
                                .where(
                                    RDBExternalModelDraft.id == opened.editor.draft.id
                                )
                                .with_for_update()
                            )
                else:
                    await holder.write_session.commit()
                    commit = await asyncio.wait_for(pending, timeout=3)
                    assert isinstance(commit.result, ExternalModelApplied)
                    assert commit.result.created is True
                    assert commit.notice_plan is not None
            finally:
                event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
        assert not any(
            "NOWAIT" in sql or "pg_try_advisory" in sql for sql in statements
        )
        if not cancel:
            locked_tables = [
                sql.split("FROM ", 1)[1].split()[0]
                for sql in statements
                if "FOR UPDATE" in sql
            ]
            order = [
                "external_model_drafts",
                "external_channel_connections",
                "external_channel_agent_routes",
                "external_channel_resources",
                "external_channel_bindings",
                "external_channel_principals",
                "users",
                "external_account_links",
                "agents",
                "agent_sessions",
                "external_channel_access_grants",
            ]
            positions = [locked_tables.index(table) for table in order]
            assert positions == sorted(positions)
            advisory_index = next(
                i for i, sql in enumerate(statements) if "pg_advisory_xact_lock" in sql
            )
            principal_index = next(
                i
                for i, sql in enumerate(statements)
                if "FROM external_channel_principals" in sql and "FOR UPDATE" in sql
            )
            assert advisory_index < principal_index
            replay = await apply()
            assert isinstance(replay.result, ExternalModelApplied)
            assert replay.result.created is False and replay.notice_plan is None
        async with writes() as session:
            count = await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalModelMutation)
                .where(RDBExternalModelMutation.session_id == fixture.target.session_id)
            )
            assert count == (0 if cancel else 1)
            root = await session.read_session.get(
                RDBAgentSession, fixture.target.session_id
            )
            assert root is not None
            assert (
                root.applied_profile_generation
                == opened.editor.current_generation + (0 if cancel else 1)
            )


@pytest.mark.parametrize("operation", ["reopen", "apply"])
@pytest.mark.parametrize(
    "change", ["disable", "unlink", "disconnect", "configuration", "expiry"]
)
async def test_model_wait_revalidates_current_state(
    rdb_engine: AsyncEngine, latest_db_schema: None, operation: str, change: str
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    repository = _local_option_repository(rdb_engine)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        now = datetime.now(UTC)
        opened = await repository.open_editor(
            actor=fixture.actor,
            target=fixture.target,
            owner_interaction_key="current-open",
            now=now,
            offset=0,
            limit=10,
        )
        assert isinstance(opened, ExternalModelEditorReady)
        async with writes() as holder:
            await holder.write_session.scalar(
                sa.select(RDBExternalModelDraft)
                .where(RDBExternalModelDraft.id == opened.editor.draft.id)
                .with_for_update()
            )
            holder_pid = await holder.write_session.scalar(
                sa.select(sa.func.pg_backend_pid())
            )
            assert isinstance(holder_pid, int)

            async def perform() -> object:
                if operation == "reopen":
                    return await repository.open_editor(
                        actor=fixture.actor,
                        target=fixture.target,
                        owner_interaction_key="current-open",
                        now=now - timedelta(minutes=5),
                        offset=0,
                        limit=10,
                    )
                return (
                    await repository.apply_draft(
                        actor=fixture.actor,
                        draft_id=opened.editor.draft.id,
                        expected_selection_fingerprint=opened.editor.draft.selection_fingerprint,
                        apply_interaction_key="current-apply",
                        now=now - timedelta(minutes=5),
                    )
                ).result

            pending = asyncio.create_task(perform())
            try:
                await _wait_for_blocked(rdb_engine, holder_pid)
                changes = {
                    "disable": sa.update(RDBUser)
                    .where(RDBUser.id == fixture.user_id)
                    .values(access_disabled_at=now),
                    "unlink": sa.update(RDBExternalAccountLink)
                    .where(RDBExternalAccountLink.id == fixture.link_id)
                    .values(revoked_at=now),
                    "disconnect": sa.update(RDBExternalChannelBinding)
                    .where(RDBExternalChannelBinding.id == fixture.target.binding_id)
                    .values(disconnected_at=now),
                    "configuration": sa.update(RDBExternalChannelConnection)
                    .where(RDBExternalChannelConnection.id == fixture.connection_id)
                    .values(configuration_generation=2),
                    "expiry": sa.update(RDBExternalModelDraft)
                    .where(RDBExternalModelDraft.id == opened.editor.draft.id)
                    .values(expires_at=now - timedelta(seconds=1)),
                }
                await holder.write_session.execute(changes[change])
                await holder.write_session.commit()
                result = await asyncio.wait_for(pending, timeout=3)
                assert isinstance(result, ExternalModelRejected)
                if change == "expiry":
                    assert (
                        result.code is ExternalModelSettingsRejectionCode.DRAFT_EXPIRED
                    )
            finally:
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
        async with writes() as session:
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBExternalModelMutation)
                    .where(
                        RDBExternalModelMutation.session_id == fixture.target.session_id
                    )
                )
                == 0
            )


async def test_apply_retains_existing_busy_exhaustion(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    repository = _local_option_repository(rdb_engine)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        now = datetime.now(UTC)
        opened = await repository.open_editor(
            actor=fixture.actor,
            target=fixture.target,
            owner_interaction_key="busy-open",
            now=now,
            offset=0,
            limit=10,
        )
        assert isinstance(opened, ExternalModelEditorReady)
        async with writes() as holder:
            await holder.write_session.scalar(
                sa.select(RDBUser)
                .where(RDBUser.id == fixture.user_id)
                .with_for_update()
            )
            result = await asyncio.wait_for(
                repository.apply_draft(
                    actor=fixture.actor,
                    draft_id=opened.editor.draft.id,
                    expected_selection_fingerprint=opened.editor.draft.selection_fingerprint,
                    apply_interaction_key="busy-apply",
                    now=now,
                ),
                timeout=3,
            )
            assert isinstance(result.result, ExternalModelBusy)
            assert result.notice_plan is None


class _FixedAttempts(ExternalAccountOAuthAttemptRepository):
    async def _current_setting_generation(
        self, session: ReadSession, *, section: SystemSettingSection
    ) -> str:
        return "observed-generation"


class _FixedLinks(ExternalAccountLinkRepository):
    async def _current_setting_generation(
        self, session: ReadSession, *, section: SystemSettingSection
    ) -> str:
        return "observed-generation"


@pytest.mark.parametrize("held", ["user", "auth", "attempt", "link"])
@pytest.mark.parametrize("outcome", ["release", "cancel", "expiry"])
async def test_oauth_finalize_wait_preserves_claim_and_live_auth(
    rdb_engine: AsyncEngine, latest_db_schema: None, held: str, outcome: str
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    settings = SystemSettingRepository()
    links = _FixedLinks(writes, settings)
    now = datetime.now(UTC)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        async with writes() as session:
            existing = await session.read_session.get(
                RDBExternalAccountLink, fixture.link_id
            )
            assert existing is not None
            provider_user_id = existing.provider_user_id
            provider, identity_scope = existing.provider, existing.identity_scope
            attempt = RDBExternalAccountOAuthAttempt(
                state_hash=uuid4().hex,
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                provider=provider,
                setting_generation="observed-generation",
                redirect_uri="https://example.test/callback",
                encrypted_pkce_verifier=None,
                status=ExternalAccountOAuthAttemptStatus.CLAIMED,
                # Finalization does not introduce a post-exchange Attempt expiry rule.
                expires_at=now - timedelta(seconds=1),
                claimed_at=now,
                completed_at=None,
                failed_at=None,
                failure_code=None,
            )
            session.write_session.add(attempt)
            await session.write_session.flush()
            attempt_id = attempt.id
            if outcome == "expiry":
                await session.write_session.execute(
                    sa.update(RDBSession)
                    .where(RDBSession.id == fixture.auth_session_id)
                    .values(expires_at=now - timedelta(seconds=1))
                )
        try:
            async with writes() as holder:
                rows = {
                    "user": (RDBUser, fixture.user_id),
                    "auth": (RDBSession, fixture.auth_session_id),
                    "attempt": (RDBExternalAccountOAuthAttempt, attempt_id),
                    "link": (RDBExternalAccountLink, fixture.link_id),
                }
                model, row_id = rows[held]
                await holder.write_session.scalar(
                    sa.select(model).where(model.id == row_id).with_for_update()
                )
                holder_pid = await holder.write_session.scalar(
                    sa.select(sa.func.pg_backend_pid())
                )
                assert isinstance(holder_pid, int)
                pending = asyncio.create_task(
                    links.finalize_oauth_link(
                        attempt_id=attempt_id,
                        user_id=fixture.user_id,
                        auth_session_id=fixture.auth_session_id,
                        provider=provider,
                        setting_generation="observed-generation",
                        redirect_uri="https://example.test/callback",
                        identity=ExternalAccountOAuthIdentity(
                            provider=provider,
                            identity_scope=identity_scope,
                            provider_user_id=provider_user_id,
                            provider_tenant_id=None,
                            provider_tenant_display_label=None,
                            provider_display_label="Refreshed label",
                        ),
                        now=now - timedelta(minutes=5),
                    )
                )
                try:
                    await _wait_for_blocked(rdb_engine, holder_pid)
                    if outcome == "cancel":
                        pending.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await pending
                    else:
                        await holder.write_session.commit()
                        result = await asyncio.wait_for(pending, timeout=3)
                        assert isinstance(result, ExternalAccountOAuthFinalizeResult)
                        if outcome == "expiry":
                            assert (
                                result.link is None
                                and result.failure_code == "auth_session_mismatch"
                            )
                        else:
                            assert (
                                result.link is not None
                                and result.link.id == fixture.link_id
                            )
                    async with writes() as observer:
                        await asyncio.wait_for(
                            settings.acquire_section_lock(
                                observer,
                                section=SystemSettingSection.SLACK_IDENTITY_OAUTH,
                            ),
                            timeout=3,
                        )
                        current = await observer.read_session.get(
                            RDBExternalAccountOAuthAttempt, attempt_id
                        )
                        assert current is not None
                        expected = {
                            "release": ExternalAccountOAuthAttemptStatus.COMPLETED,
                            "cancel": ExternalAccountOAuthAttemptStatus.CLAIMED,
                            "expiry": ExternalAccountOAuthAttemptStatus.FAILED,
                        }[outcome]
                        assert current.status is expected
                        link = await observer.read_session.get(
                            RDBExternalAccountLink, fixture.link_id
                        )
                        assert link is not None
                        assert (link.provider_display_label == "Refreshed label") == (
                            outcome == "release"
                        )
                finally:
                    if not pending.done():
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
        finally:
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExternalAccountOAuthAttempt).where(
                        RDBExternalAccountOAuthAttempt.id == attempt_id
                    )
                )


@pytest.mark.parametrize("expired", ["auth", "attempt"])
async def test_oauth_claim_refreshes_elapsed_expiry_after_attempt_wait(
    rdb_engine: AsyncEngine, latest_db_schema: None, expired: str
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    key = Fernet.generate_key().decode()
    settings = SystemSettingRepository()
    attempts = _FixedAttempts(
        writes,
        settings,
        get_system_setting_registry(),
        CredentialCipher(key),
        SystemSettingEnvironment(values={}),
        SystemSettingGenerationHasher(key),
    )
    now = datetime.now(UTC)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        attempt = await attempts.create(
            create=ExternalAccountOAuthAttemptCreate(
                id=uuid4().hex,
                state_hash=uuid4().hex,
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                provider=ExternalChannelProvider.DISCORD,
                setting_generation="observed-generation",
                redirect_uri="https://example.test/callback",
                encrypted_pkce_verifier=None,
                expires_at=now + timedelta(minutes=10),
            )
        )
        try:
            expiry = datetime.now(UTC) + timedelta(milliseconds=400)
            if expired == "auth":
                async with writes() as session:
                    await session.write_session.execute(
                        sa.update(RDBSession)
                        .where(RDBSession.id == fixture.auth_session_id)
                        .values(expires_at=expiry)
                    )
            async with writes() as holder:
                await holder.write_session.scalar(
                    sa.select(RDBExternalAccountOAuthAttempt)
                    .where(RDBExternalAccountOAuthAttempt.id == attempt.id)
                    .with_for_update()
                )
                holder_pid = await holder.write_session.scalar(
                    sa.select(sa.func.pg_backend_pid())
                )
                assert isinstance(holder_pid, int)
                pending = asyncio.create_task(
                    attempts.claim_open(
                        state_hash=attempt.state_hash,
                        user_id=fixture.user_id,
                        auth_session_id=fixture.auth_session_id,
                        provider=attempt.provider,
                        setting_generation=attempt.setting_generation,
                        redirect_uri=attempt.redirect_uri,
                        now=now - timedelta(minutes=5),
                    )
                )
                try:
                    await _wait_for_blocked(rdb_engine, holder_pid)
                    if expired == "auth":
                        # Wait only for the actual expiry contract, using DB time.
                        # The pending claimant still owns auth while Attempt waits.
                        async with writes() as clock, asyncio.timeout(3):
                            await clock.read_session.scalar(
                                sa.select(
                                    sa.func.pg_sleep(
                                        sa.func.greatest(
                                            0,
                                            sa.extract(
                                                "epoch",
                                                sa.literal(expiry)
                                                - sa.func.clock_timestamp(),
                                            ),
                                        )
                                    )
                                )
                            )
                            assert await clock.read_session.scalar(
                                sa.select(sa.func.clock_timestamp() >= expiry)
                            )
                    if expired == "attempt":
                        await holder.write_session.execute(
                            sa.update(RDBExternalAccountOAuthAttempt)
                            .where(RDBExternalAccountOAuthAttempt.id == attempt.id)
                            .values(expires_at=now - timedelta(seconds=1))
                        )
                    await holder.write_session.commit()
                    assert await asyncio.wait_for(pending, timeout=3) is None
                finally:
                    if not pending.done():
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
            async with writes() as session:
                current = await session.read_session.get(
                    RDBExternalAccountOAuthAttempt, attempt.id
                )
                assert (
                    current is not None
                    and current.status is ExternalAccountOAuthAttemptStatus.OPEN
                )
                assert current.claimed_at is None
        finally:
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExternalAccountOAuthAttempt).where(
                        RDBExternalAccountOAuthAttempt.id == attempt.id
                    )
                )
