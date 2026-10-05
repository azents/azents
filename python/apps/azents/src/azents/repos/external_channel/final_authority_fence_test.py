"""Final model application and connection transitions retain exact authority."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    ExternalChannelAccessGrantScope,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    WorkspaceUserRole,
)
from azents.core.external_channel_management import (
    ManagedConnection,
    ManagedMultiConnection,
)
from azents.core.external_model_settings import (
    ExternalModelActorContext,
    ExternalModelApplied,
    ExternalModelBusy,
    ExternalModelEditorReady,
    ExternalModelNoticeOutcome,
    ExternalModelRejected,
    ExternalModelTargetContext,
)
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_account_link import RDBExternalAccountLink
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelConnection,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
)
from azents.rdb.models.external_model_settings import (
    RDBExternalModelDraft,
    RDBExternalModelMutation,
)
from azents.rdb.models.session import RDBSession
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_profile_admission import ActiveProfileAdmissionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.external_account_link import (
    ExternalAccountLinkBusy,
    ExternalAccountLinkNotFound,
    ExternalAccountLinkRepository,
    ExternalAccountLinkUnavailable,
)
from azents.repos.external_channel.data import (
    ExternalChannelAccessGrantCreate,
    ExternalChannelAgentRouteCreate,
    ExternalChannelBindingCreate,
    ExternalChannelBlockCreate,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel.management import ExternalChannelManagementRepository
from azents.repos.external_channel.model_settings import (
    ExternalModelSettingsRepository,
    _AuthorizationResult,
    _AuthorizedModelTarget,
)
from azents.repos.external_channel.model_settings_data import ExternalModelApplyCommit
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.repository_test import _connection_create
from azents.repos.runtime_web.nonblocking_management_test import _committed_authority
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.session_model_profile.repository import SessionModelProfileRepository
from azents.repos.user import UserRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate


@dataclass(frozen=True)
class _Authority:
    workspace_id: str
    agent_id: str
    user_id: str
    connection_id: str
    principal_id: str
    link_id: str
    auth_session_id: str
    grant_id: str
    actor: ExternalModelActorContext
    target: ExternalModelTargetContext


@asynccontextmanager
async def _authority(
    engine: AsyncEngine, *, app_mode: ExternalChannelAppMode
) -> AsyncIterator[_Authority]:
    writes = create_read_write_session_manager(engine)
    channel = ExternalChannelRepository()
    now = datetime.now(UTC)
    async with _committed_authority(engine) as base:
        async with writes() as session:
            await WorkspaceUserRepository().create(
                session,
                WorkspaceUserCreate(
                    workspace_id=base.workspace_id,
                    user_id=base.user_id,
                    name="Synthetic member",
                    role=WorkspaceUserRole.MEMBER,
                ),
            )
            connection = await channel.create_connection(
                session,
                _connection_create(base.workspace_id).model_copy(
                    update={"provider_app_id": uuid4().hex, "app_mode": app_mode}
                ),
            )
            route = await channel.create_agent_route(
                session,
                ExternalChannelAgentRouteCreate(
                    connection_id=connection.id,
                    agent_id=base.agent_id,
                    agent_id_snapshot=base.agent_id,
                    route_mode=ExternalChannelRouteMode.DEDICATED,
                    connection_app_mode=app_mode,
                    catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                    catalog_removed_at=None,
                    catalog_removed_by_user_id=None,
                    open_access_enabled=False,
                ),
            )
            principal = RDBExternalChannelPrincipal(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_user_id=uuid4().hex,
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name="Synthetic",
                avatar_url=None,
                profile=None,
            )
            session.write_session.add(principal)
            await session.write_session.flush()
            root = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=base.workspace_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    agent_id=base.agent_id,
                    title=None,
                ),
            )
            resource = await channel.create_resource_idempotent(
                session,
                ExternalChannelResourceCreate(
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.THREAD,
                    provider_resource_key=uuid4().hex,
                    labels={"channel_id": "synthetic-channel", "thread_ts": "1.0"},
                    status=ExternalChannelResourceStatus.ACTIVE,
                    latest_activity_at=None,
                    unavailable_at=None,
                    deleted_at=None,
                ),
            )
            binding = await channel.create_binding_idempotent(
                session,
                ExternalChannelBindingCreate(
                    resource_id=resource.id,
                    route_id=route.id,
                    agent_session_id=root.id,
                    response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                    disconnected_at=None,
                    disconnect_reason=None,
                ),
                expected_access_request_id=None,
            )
            link = RDBExternalAccountLink(
                workspace_id=base.workspace_id,
                user_id=base.user_id,
                provider=ExternalChannelProvider.SLACK,
                identity_scope="tenant-1",
                provider_user_id=principal.provider_user_id,
                provider_tenant_display_label=None,
                provider_display_label="Synthetic",
                linked_at=now,
                revoked_at=None,
            )
            session.write_session.add(link)
            await session.write_session.flush()
            grant = await channel.ensure_access_grant(
                session,
                ExternalChannelAccessGrantCreate(
                    agent_id=base.agent_id,
                    principal_id=principal.id,
                    scope=ExternalChannelAccessGrantScope.AGENT,
                    agent_session_id=None,
                    granted_by_user_id=base.user_id,
                    source_access_request_id=None,
                    revoked_by_user_id=None,
                    revoked_at=None,
                ),
            )
            auth = await SessionRepository().create(
                session,
                SessionCreate(
                    user_id=base.user_id,
                    refresh_token=uuid4().hex,
                    expires_at=now + timedelta(hours=1),
                    max_expires_at=None,
                    user_agent=None,
                    ip_address=None,
                ),
            )
            authority = _Authority(
                base.workspace_id,
                base.agent_id,
                base.user_id,
                connection.id,
                principal.id,
                link.id,
                auth.id,
                grant.id,
                ExternalModelActorContext(
                    provider=connection.provider,
                    connection_id=connection.id,
                    configuration_generation=connection.configuration_generation,
                    principal_id=principal.id,
                    provider_tenant_id="tenant-1",
                    provider_user_id=principal.provider_user_id,
                    provider_display_name="Synthetic",
                ),
                ExternalModelTargetContext(
                    binding_id=binding.id, session_id=root.id, agent_id=base.agent_id
                ),
            )
        try:
            yield authority
        finally:
            async with writes() as session:
                await session.write_session.execute(
                    sa.update(RDBSessionAgentContext)
                    .where(RDBSessionAgentContext.agent_id == base.agent_id)
                    .values(root_session_agent_id=None)
                )
                for model, predicate in [
                    (
                        RDBExternalModelMutation,
                        RDBExternalModelMutation.agent_id == base.agent_id,
                    ),
                    (
                        RDBExternalModelDraft,
                        RDBExternalModelDraft.agent_id == base.agent_id,
                    ),
                    (
                        RDBExternalChannelBlock,
                        RDBExternalChannelBlock.agent_id == base.agent_id,
                    ),
                    (
                        RDBExternalChannelAccessGrant,
                        RDBExternalChannelAccessGrant.agent_id == base.agent_id,
                    ),
                    (
                        RDBExternalChannelBinding,
                        RDBExternalChannelBinding.agent_session_id == root.id,
                    ),
                    (
                        RDBExternalChannelResource,
                        RDBExternalChannelResource.connection_id == connection.id,
                    ),
                    (
                        RDBExternalChannelAgentRoute,
                        RDBExternalChannelAgentRoute.connection_id == connection.id,
                    ),
                    (
                        RDBExternalChannelConnection,
                        RDBExternalChannelConnection.id == connection.id,
                    ),
                    (RDBExternalAccountLink, RDBExternalAccountLink.id == link.id),
                    (
                        RDBExternalChannelPrincipal,
                        RDBExternalChannelPrincipal.id == principal.id,
                    ),
                    (RDBSessionAgent, RDBSessionAgent.agent_session_id == root.id),
                    (RDBAgentSession, RDBAgentSession.id == root.id),
                    (
                        RDBSessionAgentContext,
                        RDBSessionAgentContext.agent_id == base.agent_id,
                    ),
                    (RDBAgentRuntime, RDBAgentRuntime.agent_id == base.agent_id),
                ]:
                    await session.write_session.execute(
                        sa.delete(model).where(predicate)
                    )


@pytest.mark.parametrize("change", ["disable", "link", "block", "grant"])
async def test_final_model_apply_orders_actual_authority_mutators(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    change: str,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    gate, release, attempted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    channel = ExternalChannelRepository()
    agent, roots = AgentRepository(), AgentSessionRepository()
    links = ExternalAccountLinkRepository(writes)

    class PausedApply(ExternalModelSettingsRepository):
        async def _authorize_for_apply(
            self,
            session: WriteSession,
            *,
            actor: ExternalModelActorContext,
            target: ExternalModelTargetContext,
        ) -> _AuthorizationResult:
            result = await super()._authorize_for_apply(
                session, actor=actor, target=target
            )
            gate.set()
            await release.wait()
            return result

        async def _project_authorized_options(
            self, session: WriteSession, authorized: _AuthorizedModelTarget
        ) -> _AuthorizedModelTarget:
            # This test exercises DB authority and application; metadata admission has
            # separate integration coverage and is not under test here.
            return authorized

    repository = PausedApply(
        session_manager=writes,
        external_channel_repository=channel,
        external_account_link_repository=links,
        session_model_profile_repository=SessionModelProfileRepository(
            agent,
            roots,
            WorkspaceUserRepository(),
            ChatWriteRequestRepository(),
            AsyncMock(spec=ActiveProfileAdmissionRepository),
            writes,
        ),
        agent_repository=agent,
        agent_session_repository=roots,
        active_model_capabilities_repository=AsyncMock(
            spec=ActiveModelCapabilitiesRepository
        ),
    )
    now = datetime.now(UTC)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        opened = await repository.open_editor(
            actor=fixture.actor,
            target=fixture.target,
            owner_interaction_key="open-fence",
            now=now,
            offset=0,
            limit=10,
        )
        assert isinstance(opened, ExternalModelEditorReady)

        async def change_authority() -> None:
            if change == "link":
                await links.unlink(
                    user_id=fixture.user_id,
                    auth_session_id=fixture.auth_session_id,
                    link_id=fixture.link_id,
                    now=now,
                )
                return
            async with writes() as session:
                if change == "disable":
                    await UserRepository().disable_access(
                        session, fixture.user_id, disabled_at=now
                    )
                elif change == "block":
                    await channel.create_block_idempotent(
                        session,
                        ExternalChannelBlockCreate(
                            agent_id=fixture.agent_id,
                            principal_id=fixture.principal_id,
                            blocked_by_user_id=fixture.user_id,
                            reason="Synthetic block",
                            removed_by_user_id=None,
                            removed_at=None,
                        ),
                    )
                else:
                    await channel.delete_access_grant(
                        session, grant_id=fixture.grant_id
                    )

        def observe(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            if (
                (change == "disable" and "UPDATE users" in statement)
                or (
                    change in {"block", "grant"}
                    and "pg_advisory_xact_lock" in statement
                )
                or (change == "link" and "UPDATE external_account_links" in statement)
            ):
                attempted.set()

        event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
        pending = asyncio.create_task(
            repository.apply_draft(
                actor=fixture.actor,
                draft_id=opened.editor.draft.id,
                expected_selection_fingerprint=opened.editor.draft.selection_fingerprint,
                apply_interaction_key="apply-fence",
                now=now,
            )
        )
        changed = None
        try:
            await asyncio.wait_for(gate.wait(), timeout=2)
            changed = asyncio.create_task(change_authority())
            await asyncio.wait_for(attempted.wait(), timeout=2)
            assert not changed.done()
            release.set()
            result = await asyncio.wait_for(pending, timeout=3)
            assert isinstance(result.result, ExternalModelApplied)
            await asyncio.wait_for(changed, timeout=3)
            denied = await repository.open_editor(
                actor=fixture.actor,
                target=fixture.target,
                owner_interaction_key="open-after-revoke",
                now=now,
                offset=0,
                limit=10,
            )
            assert isinstance(denied, ExternalModelRejected)
        finally:
            release.set()
            event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
            for task in [pending, changed]:
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("change", ["disable", "revoke", "expire"])
async def test_unlink_revalidates_authority_after_wait_and_rolls_back(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    change: str,
) -> None:
    """A blocked unlink cannot publish after its earlier auth read becomes stale."""
    writes = create_read_write_session_manager(rdb_engine)
    attempted = asyncio.Event()

    def observe(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if statement.startswith("UPDATE external_account_links"):
            attempted.set()

    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        async with writes() as holder:
            await holder.write_session.scalar(
                sa.select(RDBExternalAccountLink)
                .where(RDBExternalAccountLink.id == fixture.link_id)
                .with_for_update()
            )
            event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
            pending = asyncio.create_task(
                ExternalAccountLinkRepository(writes).unlink(
                    user_id=fixture.user_id,
                    auth_session_id=fixture.auth_session_id,
                    link_id=fixture.link_id,
                    now=datetime.now(UTC) - timedelta(minutes=5),
                )
            )
            try:
                await asyncio.wait_for(attempted.wait(), timeout=2)
                assert not pending.done()
                async with writes() as security:
                    if change == "disable":
                        await UserRepository().disable_access(
                            security,
                            fixture.user_id,
                            disabled_at=datetime.now(UTC),
                        )
                    elif change == "revoke":
                        await SessionRepository().revoke(
                            security, fixture.auth_session_id
                        )
                    else:
                        await security.write_session.execute(
                            sa.update(RDBSession)
                            .where(RDBSession.id == fixture.auth_session_id)
                            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
                        )
                await holder.write_session.commit()
                with pytest.raises(ExternalAccountLinkUnavailable):
                    await asyncio.wait_for(pending, timeout=3)
            finally:
                event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
        async with writes() as session:
            link = await session.read_session.get(
                RDBExternalAccountLink, fixture.link_id
            )
            assert link is not None
            assert link.revoked_at is None
            assert link.revocation_reason is None


async def test_unlink_concurrent_replay_preserves_first_terminal_record(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Concurrent conditional revokes converge and subsequent replay keeps history."""
    writes = create_read_write_session_manager(rdb_engine)
    links = ExternalAccountLinkRepository(writes)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        now = datetime.now(UTC)
        first, second = await asyncio.gather(
            links.unlink(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                link_id=fixture.link_id,
                now=now,
            ),
            links.unlink(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                link_id=fixture.link_id,
                now=now + timedelta(seconds=1),
            ),
        )
        assert first == second
        assert first.revocation_reason == second.revocation_reason
        async with writes() as session:
            revoked_at = await session.read_session.scalar(
                sa.select(RDBExternalAccountLink.revoked_at).where(
                    RDBExternalAccountLink.id == fixture.link_id
                )
            )
        assert revoked_at is not None
        replay = await links.unlink(
            user_id=fixture.user_id,
            auth_session_id=fixture.auth_session_id,
            link_id=fixture.link_id,
            now=now + timedelta(seconds=2),
        )
        assert replay == first
        assert replay.revocation_reason == first.revocation_reason
        async with writes() as session:
            assert (
                await session.read_session.scalar(
                    sa.select(RDBExternalAccountLink.revoked_at).where(
                        RDBExternalAccountLink.id == fixture.link_id
                    )
                )
                == revoked_at
            )
        with pytest.raises(ExternalAccountLinkNotFound):
            await links.unlink(
                user_id=fixture.user_id,
                auth_session_id=fixture.auth_session_id,
                link_id=uuid4().hex,
                now=now,
            )
        async with _committed_authority(rdb_engine) as other:
            async with writes() as session:
                other_auth = await SessionRepository().create(
                    session,
                    SessionCreate(
                        user_id=other.user_id,
                        refresh_token=uuid4().hex,
                        expires_at=now + timedelta(hours=1),
                        max_expires_at=None,
                        user_agent=None,
                        ip_address=None,
                    ),
                )
            with pytest.raises(ExternalAccountLinkNotFound):
                await links.unlink(
                    user_id=other.user_id,
                    auth_session_id=other_auth.id,
                    link_id=fixture.link_id,
                    now=now,
                )


async def test_unlink_retains_existing_busy_exhaustion(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A write that remains locked still exhausts the existing two-second policy."""
    writes = create_read_write_session_manager(rdb_engine)
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
        async with writes() as holder:
            await holder.write_session.scalar(
                sa.select(RDBExternalAccountLink)
                .where(RDBExternalAccountLink.id == fixture.link_id)
                .with_for_update()
            )
            event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
            try:
                with pytest.raises(ExternalAccountLinkBusy):
                    await asyncio.wait_for(
                        ExternalAccountLinkRepository(writes).unlink(
                            user_id=fixture.user_id,
                            auth_session_id=fixture.auth_session_id,
                            link_id=fixture.link_id,
                            now=datetime.now(UTC),
                        ),
                        timeout=10,
                    )
            finally:
                event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
        assert (
            sum(sql.startswith("UPDATE external_account_links") for sql in statements)
            == 3
        )
        assert sum("SET LOCAL lock_timeout = '2s'" in sql for sql in statements) == 3
        assert all("NOWAIT" not in sql for sql in statements)


class _LocalOptionRepository(ExternalModelSettingsRepository):
    """Use fixture-local options while testing database mutation concurrency."""

    async def _project_authorized_options(
        self, session: WriteSession, authorized: _AuthorizedModelTarget
    ) -> _AuthorizedModelTarget:
        return authorized


def _local_option_repository(engine: AsyncEngine) -> ExternalModelSettingsRepository:
    writes = create_read_write_session_manager(engine)
    agents, roots = AgentRepository(), AgentSessionRepository()
    return _LocalOptionRepository(
        session_manager=writes,
        external_channel_repository=ExternalChannelRepository(),
        external_account_link_repository=ExternalAccountLinkRepository(writes),
        session_model_profile_repository=SessionModelProfileRepository(
            agents,
            roots,
            WorkspaceUserRepository(),
            ChatWriteRequestRepository(),
            AsyncMock(spec=ActiveProfileAdmissionRepository),
            writes,
        ),
        agent_repository=agents,
        agent_session_repository=roots,
        active_model_capabilities_repository=AsyncMock(
            spec=ActiveModelCapabilitiesRepository
        ),
    )


async def test_model_apply_replay_reads_committed_audit_without_notice_row_lock(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A notice-only writer cannot make immutable replay busy or repeat effects."""
    writes = create_read_write_session_manager(rdb_engine)
    repository = _local_option_repository(rdb_engine)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        now = datetime.now(UTC)
        opened = await repository.open_editor(
            actor=fixture.actor,
            target=fixture.target,
            owner_interaction_key="immutable-open",
            now=now,
            offset=0,
            limit=10,
        )
        assert isinstance(opened, ExternalModelEditorReady)
        first = await repository.apply_draft(
            actor=fixture.actor,
            draft_id=opened.editor.draft.id,
            expected_selection_fingerprint=opened.editor.draft.selection_fingerprint,
            apply_interaction_key="immutable-apply",
            now=now,
        )
        assert isinstance(first.result, ExternalModelApplied)
        assert first.result.created is True
        assert first.notice_plan is not None
        async with writes() as holder:
            await holder.write_session.execute(
                sa.update(RDBExternalModelMutation)
                .where(RDBExternalModelMutation.id == first.result.mutation_id)
                .values(notice_outcome=ExternalModelNoticeOutcome.DELIVERED)
            )
            replay = await asyncio.wait_for(
                repository.apply_draft(
                    actor=fixture.actor,
                    draft_id=opened.editor.draft.id,
                    expected_selection_fingerprint=(
                        opened.editor.draft.selection_fingerprint
                    ),
                    apply_interaction_key="immutable-apply",
                    now=now,
                ),
                timeout=2,
            )
            assert isinstance(replay.result, ExternalModelApplied)
            assert replay.result.created is False
            assert replay.result.mutation_id == first.result.mutation_id
            assert replay.result.notice_outcome is ExternalModelNoticeOutcome.UNKNOWN
            assert replay.notice_plan is None
            assert replay.result.editor.current_generation == (
                first.result.editor.current_generation
            )
        async with writes() as session:
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBExternalModelMutation)
                    .where(
                        RDBExternalModelMutation.session_id == fixture.target.session_id
                    )
                )
                == 1
            )


async def test_concurrent_model_apply_has_one_profile_audit_and_notice_plan(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Removing the replay lock retains draft/authority once-only Apply fences."""
    repository = _local_option_repository(rdb_engine)
    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        now = datetime.now(UTC)
        opened = await repository.open_editor(
            actor=fixture.actor,
            target=fixture.target,
            owner_interaction_key="concurrent-open",
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
                apply_interaction_key="concurrent-apply",
                now=now,
            )

        results = await asyncio.gather(apply(), apply())
        assert all(
            isinstance(commit.result, ExternalModelApplied | ExternalModelBusy)
            for commit in results
        )
        assert (
            sum(
                isinstance(commit.result, ExternalModelApplied)
                and commit.result.created
                for commit in results
            )
            == 1
        )
        assert sum(commit.notice_plan is not None for commit in results) == 1
        replay = await apply()
        assert isinstance(replay.result, ExternalModelApplied)
        assert replay.result.created is False
        assert replay.notice_plan is None
        assert replay.result.editor.current_generation == (
            opened.editor.current_generation + 1
        )


@pytest.mark.parametrize("first", ["replace", "disconnect"])
@pytest.mark.parametrize("app_mode", list(ExternalChannelAppMode))
async def test_connection_transitions_serialize_generations_and_disconnect(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    first: str,
    app_mode: ExternalChannelAppMode,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    management = ExternalChannelManagementRepository()
    lifecycle = ExternalChannelLifecycleRepository()
    attempted = asyncio.Event()
    async with _authority(rdb_engine, app_mode=app_mode) as fixture:

        async def replace_in_session(
            session: WriteSession, key: str
        ) -> ManagedConnection | ManagedMultiConnection | None:
            if app_mode is ExternalChannelAppMode.SINGLE:
                return await management.replace_slack_configuration(
                    session,
                    workspace_id=fixture.workspace_id,
                    agent_id=fixture.agent_id,
                    connection_id=fixture.connection_id,
                    provider_app_id=key,
                    transport=ExternalChannelTransport.HTTP,
                    encrypted_credentials=key,
                )
            return await management.replace_multi_slack_configuration(
                session,
                workspace_id=fixture.workspace_id,
                connection_id=fixture.connection_id,
                provider_app_id=key,
                transport=ExternalChannelTransport.HTTP,
                encrypted_credentials=key,
            )

        async def replace(
            key: str,
        ) -> ManagedConnection | ManagedMultiConnection | None:
            async with writes() as session:
                return await replace_in_session(session, key)

        def observe(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            if (
                "external_channel_connections" in statement
                and "FOR UPDATE" in statement
            ):
                attempted.set()

        task = None
        event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
        try:
            async with writes() as session:
                if first == "replace":
                    initial = await replace_in_session(session, "first")
                    assert initial is not None
                elif app_mode is ExternalChannelAppMode.SINGLE:
                    assert (
                        await management.begin_connection_disconnect(
                            session,
                            workspace_id=fixture.workspace_id,
                            agent_id=fixture.agent_id,
                            connection_id=fixture.connection_id,
                            now=datetime.now(UTC),
                        )
                        is not None
                    )
                else:
                    assert (
                        await lifecycle.disconnect_multi_connection(
                            session,
                            connection_id=fixture.connection_id,
                            now=datetime.now(UTC),
                            reason="Synthetic disconnect",
                        )
                        is not None
                    )
                attempted.clear()
                task = asyncio.create_task(replace("second"))
                await asyncio.wait_for(attempted.wait(), timeout=2)
                assert not task.done()
            result = await asyncio.wait_for(task, timeout=3)
            async with writes() as session:
                obsolete = await ExternalChannelRepository().update_connection_health(
                    session,
                    connection_id=fixture.connection_id,
                    status=ExternalChannelConnectionStatus.ACTIVE,
                    provider_tenant_id="obsolete-tenant",
                    provider_bot_user_id=None,
                    capabilities=None,
                    checked_at=datetime.now(UTC),
                    expected_encrypted_credentials=(
                        "first" if first == "replace" else "ciphertext-only"
                    ),
                    expected_configuration_generation=2 if first == "replace" else 1,
                )
                assert obsolete is None
                stored = await session.read_session.get(
                    RDBExternalChannelConnection, fixture.connection_id
                )
                assert stored is not None
                if first == "replace":
                    assert result is not None
                    assert stored.configuration_generation == 3
                    assert stored.encrypted_credentials == "second"
                else:
                    assert result is None
                    assert stored.status is (
                        ExternalChannelConnectionStatus.DISCONNECTING
                        if app_mode is ExternalChannelAppMode.SINGLE
                        else ExternalChannelConnectionStatus.DISCONNECTED
                    )
        finally:
            event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
