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
    ExternalModelEditorReady,
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
    ExternalAccountLinkRepository,
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
                with pytest.raises(ExternalAccountLinkBusy):
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
            if (change == "disable" and "UPDATE users" in statement) or (
                change in {"block", "grant"} and "pg_advisory_xact_lock" in statement
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
            if change == "link":
                await asyncio.wait_for(changed, timeout=3)
            else:
                await asyncio.wait_for(attempted.wait(), timeout=2)
                assert not changed.done()
            release.set()
            result = await asyncio.wait_for(pending, timeout=3)
            assert isinstance(result.result, ExternalModelApplied)
            await asyncio.wait_for(changed, timeout=3)
            if change == "link":
                await links.unlink(
                    user_id=fixture.user_id,
                    auth_session_id=fixture.auth_session_id,
                    link_id=fixture.link_id,
                    now=now,
                )
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
