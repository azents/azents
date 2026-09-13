"""ExternalChannelRepository tests."""

import dataclasses
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionProductMode,
    AgentSessionStatus,
    ExternalChannelAccessGrantScope,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
    LLMProvider,
    WorkspaceUserRole,
)
from azents.core.external_model_settings import (
    ExternalModelActorContext,
    ExternalModelApplied,
    ExternalModelBusy,
    ExternalModelEditorReady,
    ExternalModelStale,
    ExternalModelTargetContext,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_account_link import RDBExternalAccountLink
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelAppClaim,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelIngressLease,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
)
from azents.rdb.models.external_model_settings import (
    RDBExternalModelDraft,
    RDBExternalModelMutation,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.external_account_link import ExternalAccountLinkRepository
from azents.repos.external_channel.data import (
    ExternalChannelAccessGrantCreate,
    ExternalChannelAgentRouteCreate,
    ExternalChannelBindingCreate,
    ExternalChannelBlockCreate,
    ExternalChannelConnectionCreate,
    ExternalChannelConversationPosition,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel.model_settings import (
    ExternalModelSettingsRepository,
)
from azents.repos.external_channel.repository import (
    ExternalChannelRepository,
    _slack_work_presence_target,
)
from azents.repos.external_channel.work_state import (
    CHANNEL_WORK_STATE_SCHEMA_VERSION,
    EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
    ChannelWorkState,
    channel_work_state_name,
)
from azents.repos.session_model_profile.repository import (
    SessionModelProfileRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


def _at(minute: int) -> datetime.datetime:
    """Return a stable timezone-aware test timestamp."""
    return datetime.datetime(2026, 7, 21, 0, minute, tzinfo=datetime.UTC)


def _discord_capabilities() -> dict[str, object]:
    """Return one complete persisted Discord capability snapshot."""
    return {
        "provider": ExternalChannelProvider.DISCORD.value,
        "transport": ExternalChannelTransport.HTTP.value,
        "inbound_events": True,
        "thread_history": True,
        "post_messages": True,
        "update_messages": True,
        "delete_messages": True,
        "download_files": True,
        "upload_files": True,
    }


def _discord_command_set() -> dict[str, object]:
    """Return one complete versioned Discord command capability proof."""
    return {
        "schema_version": 1,
        "command_ids": {
            "message_action": "123456789012345671",
            "azents_settings": "123456789012345672",
            "conversation_settings": "123456789012345673",
        },
    }


async def _create_workspace(
    session: AsyncSession,
    handle: str = "external-channel-repository-test",
) -> str:
    """Create a Workspace required by an External Channel connection."""
    result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(
            name="External Channel repository test",
            handle=handle,
        ),
    )
    assert isinstance(result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(
        session,
        handle,
    )
    assert workspace_id is not None
    return workspace_id


def _connection_create(workspace_id: str) -> ExternalChannelConnectionCreate:
    """Build a redacted test connection persistence payload."""
    return ExternalChannelConnectionCreate(
        workspace_id=workspace_id,
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        app_mode=ExternalChannelAppMode.SINGLE,
        status=ExternalChannelConnectionStatus.ACTIVE,
        provider_app_id="app-1",
        provider_tenant_id="tenant-1",
        provider_bot_user_id=None,
        http_callback_selector_hash=None,
        encrypted_credentials="ciphertext-only",
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        disconnected_at=None,
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
    )


@dataclasses.dataclass(frozen=True)
class _DiscordGatewayTypingFixture:
    """Persisted owners needed to project Discord Gateway typing targets."""

    repository: ExternalChannelRepository
    connection_id: str
    agent_id: str
    agent_session_id: str
    route_id: str
    lease_owner: str
    lease_generation: int


async def _create_discord_gateway_typing_fixture(
    session: AsyncSession,
    *,
    suffix: str = "",
) -> _DiscordGatewayTypingFixture:
    """Create one valid leased Discord Gateway ownership graph."""
    identifier_suffix = f"-{suffix}" if suffix else ""
    workspace_id = await _create_workspace(
        session,
        f"discord-gateway-typing-targets{identifier_suffix}",
    )
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"discord-gateway-typing-integration{identifier_suffix}",
        encrypted_credentials="encrypted",
        config=None,
    )
    session.add(integration)
    await session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier=f"discord-gateway-typing-model{identifier_suffix}",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Discord Gateway Typing Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=(selection),
            lightweight_model_selection=(selection),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    session.add(agent)
    await session.flush()
    runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent.id)
    runtime.workspace_path = "/workspace/agent"
    session.add(runtime)
    await session.flush()

    repository = ExternalChannelRepository()
    connection = await repository.create_connection(
        session,
        _connection_create(workspace_id).model_copy(
            update={
                "provider": ExternalChannelProvider.DISCORD,
                "ingress_profile": (ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP),
                "provider_app_id": (f"discord-gateway-typing-app{identifier_suffix}"),
                "provider_tenant_id": "100",
            }
        ),
    )
    session.add(
        RDBExternalChannelAppClaim(
            provider=ExternalChannelProvider.DISCORD,
            provider_app_id=f"discord-gateway-typing-app{identifier_suffix}",
            connection_id=connection.id,
            claim_generation=1,
        )
    )
    await session.flush()
    route = await repository.create_agent_route(
        session,
        ExternalChannelAgentRouteCreate(
            connection_id=connection.id,
            agent_id=agent.id,
            agent_id_snapshot=agent.id,
            route_mode=ExternalChannelRouteMode.DEDICATED,
            connection_app_mode=ExternalChannelAppMode.SINGLE,
            catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
            catalog_removed_at=None,
            catalog_removed_by_user_id=None,
        ),
    )
    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            agent_id=agent.id,
            title=None,
        ),
    )
    claim = await repository.claim_discord_gateway_lease(
        session,
        connection_id=connection.id,
        lease_owner="typing-manager",
        now=_at(1),
        lease_until=_at(10),
    )
    assert claim is not None
    return _DiscordGatewayTypingFixture(
        repository=repository,
        connection_id=connection.id,
        agent_id=agent.id,
        agent_session_id=agent_session.id,
        route_id=route.id,
        lease_owner="typing-manager",
        lease_generation=claim.lease.lease_generation,
    )


async def _create_discord_gateway_typing_binding(
    session: AsyncSession,
    fixture: _DiscordGatewayTypingFixture,
    *,
    key: str,
    resource_type: ExternalChannelResourceType,
    labels: dict[str, object],
    work_cycle_id: str,
    work_status: ExternalChannelWorkStatus = ExternalChannelWorkStatus.ACTIVE,
    tracker_visibility: Literal["hidden", "visible"] = "visible",
    awaiting_input_run_id: str | None = None,
) -> str:
    """Create one binding and its exact current Channel Work Toolkit State."""
    resource = await fixture.repository.create_resource_idempotent(
        session,
        ExternalChannelResourceCreate(
            connection_id=fixture.connection_id,
            resource_type=resource_type,
            provider_resource_key=key,
            labels=labels,
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=None,
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    binding = await fixture.repository.create_binding_idempotent(
        session,
        ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=fixture.route_id,
            agent_session_id=fixture.agent_session_id,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    session.add(
        RDBToolkitState(
            agent_id=fixture.agent_id,
            session_id=fixture.agent_session_id,
            toolkit_namespace=EXTERNAL_CHANNEL_TOOLKIT_STATE_NAMESPACE,
            state_name=channel_work_state_name(binding.id),
            state_json=ChannelWorkState(
                schema_version=CHANNEL_WORK_STATE_SCHEMA_VERSION,
                binding_id=binding.id,
                work_cycle_id=work_cycle_id,
                status=work_status,
                tracker_visibility=tracker_visibility,
                slack_presence_thread_ts=None,
                slack_presence_initiator_user_id=None,
                title=None,
                tasks=[],
                state_revision=1,
                desired_progress_revision=0,
                desired_progress=None,
                awaiting_input_run_id=awaiting_input_run_id,
                finished_at=(
                    None if work_status is ExternalChannelWorkStatus.ACTIVE else _at(2)
                ),
                projection_parts=[],
            ).model_dump(mode="json"),
            schema_version=CHANNEL_WORK_STATE_SCHEMA_VERSION,
        )
    )
    await session.flush()
    return binding.id


@pytest.mark.asyncio
async def test_detach_user_references_preserves_external_channel_invariants() -> None:
    """Detach retained audit references without violating configured-actor checks."""
    repository = ExternalChannelRepository()
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=[SimpleNamespace(rowcount=1) for _ in range(10)]
    )
    session.flush = AsyncMock()

    await repository.detach_user_references(session, user_id="user-1")

    assert session.execute.await_count == 10
    sql = "\n".join(
        str(call.args[0].compile(dialect=postgresql.dialect()))
        for call in session.execute.await_args_list
    )
    assert "external_channel_agent_routes" in sql
    assert "external_channel_channel_defaults" in sql
    assert "external_channel_participation_settings" in sql
    assert "external_channel_access_requests" in sql
    assert "external_channel_access_grants" in sql
    assert "external_channel_blocks" in sql
    assert "configured_by_principal_id" in sql
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_conversation_position_lock_and_compare_and_set_are_fenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable position row is locked and advances only from its expected value."""
    repository = ExternalChannelRepository()
    position = SimpleNamespace(id="position-1", read_through_position=None)
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=position)
    first_update = MagicMock()
    first_update.scalar_one_or_none.return_value = "position-1"
    stale_update = MagicMock()
    stale_update.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[first_update, stale_update])
    session.flush = AsyncMock()
    monkeypatch.setattr(
        ExternalChannelConversationPosition,
        "model_validate",
        classmethod(lambda cls, value: value),
    )

    locked = await repository.lock_conversation_position(
        session,
        position_id="position-1",
    )
    advanced = await repository.advance_conversation_position_if_current(
        session,
        position_id="position-1",
        expected_read_through_position=None,
        read_through_position="0000000002",
    )
    stale = await repository.advance_conversation_position_if_current(
        session,
        position_id="position-1",
        expected_read_through_position="0000000001",
        read_through_position="0000000003",
    )

    assert locked is position
    assert advanced is True
    assert stale is False
    lock_statement = session.scalar.await_args.args[0]
    assert "FOR UPDATE" in str(lock_statement.compile(dialect=postgresql.dialect()))
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_discord_gateway_typing_targets_fence_stale_lease_and_allow_empty(
    rdb_session: AsyncSession,
) -> None:
    """A valid lease returns an empty projection while stale authority returns None."""
    fixture = await _create_discord_gateway_typing_fixture(rdb_session)

    stale = await fixture.repository.list_owned_discord_typing_targets(
        rdb_session,
        connection_id=fixture.connection_id,
        lease_owner="stale-manager",
        lease_generation=fixture.lease_generation,
        now=_at(2),
    )
    empty = await fixture.repository.list_owned_discord_typing_targets(
        rdb_session,
        connection_id=fixture.connection_id,
        lease_owner=fixture.lease_owner,
        lease_generation=fixture.lease_generation,
        now=_at(2),
    )

    assert stale is None
    assert empty == ()


@pytest.mark.asyncio
async def test_discord_gateway_typing_targets_project_active_current_work(
    rdb_session: AsyncSession,
) -> None:
    """Only active Work on current owners contributes its exact delivery target."""
    fixture = await _create_discord_gateway_typing_fixture(rdb_session)
    await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-parent",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        labels={
            "guild_id": "100",
            "parent_channel_id": "200",
        },
        work_cycle_id="work-hidden-parent",
        tracker_visibility="hidden",
    )
    await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-thread-delivery",
        resource_type=ExternalChannelResourceType.THREAD,
        labels={
            "guild_id": "100",
            "thread_id": "301",
            "delivery_channel_id": "300",
        },
        work_cycle_id="work-visible-thread",
    )
    await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-thread-shared",
        resource_type=ExternalChannelResourceType.THREAD,
        labels={
            "guild_id": "100",
            "thread_id": "302",
            "delivery_channel_id": "300",
        },
        work_cycle_id="work-shared-channel",
    )
    await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-thread-fallback",
        resource_type=ExternalChannelResourceType.THREAD,
        labels={
            "guild_id": "100",
            "thread_id": "400",
        },
        work_cycle_id="work-thread-fallback",
    )
    await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-awaiting",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        labels={
            "guild_id": "100",
            "parent_channel_id": "450",
        },
        work_cycle_id="work-awaiting",
        awaiting_input_run_id="run-request",
    )
    await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-finished",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        labels={
            "guild_id": "100",
            "parent_channel_id": "500",
        },
        work_cycle_id="work-finished",
        work_status=ExternalChannelWorkStatus.FINISHED,
    )
    disconnected_binding_id = await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-disconnected",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        labels={
            "guild_id": "100",
            "parent_channel_id": "600",
        },
        work_cycle_id="work-disconnected",
    )
    unavailable_binding_id = await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-unavailable",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        labels={
            "guild_id": "100",
            "parent_channel_id": "700",
        },
        work_cycle_id="work-unavailable",
    )
    await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-malformed",
        resource_type=ExternalChannelResourceType.THREAD,
        labels={
            "guild_id": "999",
            "thread_id": "not-a-snowflake",
        },
        work_cycle_id="work-malformed",
    )
    disconnected_binding = await rdb_session.get(
        RDBExternalChannelBinding,
        disconnected_binding_id,
    )
    unavailable_binding = await rdb_session.get(
        RDBExternalChannelBinding,
        unavailable_binding_id,
    )
    assert disconnected_binding is not None
    assert unavailable_binding is not None
    disconnected_binding.disconnected_at = _at(2)
    unavailable_resource = await rdb_session.get(
        RDBExternalChannelResource,
        unavailable_binding.resource_id,
    )
    assert unavailable_resource is not None
    unavailable_resource.status = ExternalChannelResourceStatus.UNAVAILABLE
    await rdb_session.flush()

    targets = await fixture.repository.list_owned_discord_typing_targets(
        rdb_session,
        connection_id=fixture.connection_id,
        lease_owner=fixture.lease_owner,
        lease_generation=fixture.lease_generation,
        now=_at(3),
    )

    assert targets is not None
    assert [
        (target.guild_id, target.channel_id, target.work_cycle_ids)
        for target in targets
    ] == [
        ("100", "200", ("work-hidden-parent",)),
        (
            "100",
            "300",
            ("work-shared-channel", "work-visible-thread"),
        ),
        ("100", "400", ("work-thread-fallback",)),
    ]


@pytest.mark.asyncio
async def test_discord_gateway_typing_targets_exclude_stopping_session(
    rdb_session: AsyncSession,
) -> None:
    """A stop request immediately removes otherwise active Work from projection."""
    fixture = await _create_discord_gateway_typing_fixture(rdb_session)
    await _create_discord_gateway_typing_binding(
        rdb_session,
        fixture,
        key="typing-stopping-session",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        labels={
            "guild_id": "100",
            "parent_channel_id": "200",
        },
        work_cycle_id="work-stopping-session",
    )
    agent_session = await rdb_session.get(
        RDBAgentSession,
        fixture.agent_session_id,
    )
    assert agent_session is not None
    agent_session.stop_requested_at = _at(2)
    await rdb_session.flush()

    targets = await fixture.repository.list_owned_discord_typing_targets(
        rdb_session,
        connection_id=fixture.connection_id,
        lease_owner=fixture.lease_owner,
        lease_generation=fixture.lease_generation,
        now=_at(3),
    )

    assert targets == ()


@pytest.mark.asyncio
class TestExternalChannelRepository:
    """External Channel foundation repository tests."""

    async def test_principal_agent_authorization_fence_covers_absent_block(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """The fence conflicts even when there is no block row to lock."""
        del latest_db_schema
        repository = ExternalChannelRepository()
        async with (
            AsyncSession(rdb_engine) as first,
            AsyncSession(rdb_engine) as second,
        ):
            acquired = await repository.acquire_principal_agent_authorization_fence(
                first,
                agent_id="agent-without-row",
                principal_id="principal-without-row",
                nowait=False,
            )
            conflicted = await repository.acquire_principal_agent_authorization_fence(
                second,
                agent_id="agent-without-row",
                principal_id="principal-without-row",
                nowait=True,
            )
            assert acquired is True
            assert conflicted is False

            await first.commit()
            acquired_after_release = (
                await repository.acquire_principal_agent_authorization_fence(
                    second,
                    agent_id="agent-without-row",
                    principal_id="principal-without-row",
                    nowait=True,
                )
            )
            assert acquired_after_release is True

    async def test_native_model_authorization_fences_user_disable_both_orders(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """User disable conflicts before and after native authorization."""
        del latest_db_schema
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
            fixture = await _create_discord_gateway_typing_fixture(
                setup,
                suffix="native-model-authorization",
            )
            connection = await setup.get(
                RDBExternalChannelConnection,
                fixture.connection_id,
            )
            assert connection is not None
            user = await UserRepository().create(
                setup,
                UserCreate(email="native-model-fence@example.com"),
            )
            membership = await WorkspaceUserRepository().create(
                setup,
                WorkspaceUserCreate(
                    workspace_id=connection.workspace_id,
                    user_id=user.id,
                    name="Native model member",
                    role=WorkspaceUserRole.MEMBER,
                ),
            )
            assert isinstance(membership, Success)
            principal = RDBExternalChannelPrincipal(
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="100",
                provider_user_id="native-model-user",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name="Native user",
                avatar_url=None,
                profile=None,
            )
            setup.add(principal)
            await setup.flush()
            grant = await fixture.repository.ensure_access_grant(
                setup,
                ExternalChannelAccessGrantCreate(
                    agent_id=fixture.agent_id,
                    principal_id=principal.id,
                    scope=ExternalChannelAccessGrantScope.AGENT,
                    agent_session_id=None,
                    granted_by_user_id=user.id,
                    source_access_request_id=None,
                    revoked_by_user_id=None,
                    revoked_at=None,
                ),
            )
            setup.add(
                RDBExternalAccountLink(
                    workspace_id=connection.workspace_id,
                    user_id=user.id,
                    provider=ExternalChannelProvider.DISCORD,
                    identity_scope="global",
                    provider_user_id=principal.provider_user_id,
                    provider_tenant_display_label="Test guild",
                    provider_display_label="Native user",
                    linked_at=_at(0),
                    revoked_at=None,
                )
            )
            binding_id = await _create_discord_gateway_typing_binding(
                setup,
                fixture,
                key="discord:100:native-model-thread",
                resource_type=ExternalChannelResourceType.THREAD,
                labels={
                    "guild_id": "100",
                    "conversation_scope": "thread",
                    "thread_id": "native-model-thread",
                    "parent_channel_id": "native-model-parent",
                },
                work_cycle_id="native-model-work",
            )
            await setup.commit()

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise
                else:
                    await session.commit()

        agent_repository = AgentRepository()
        agent_session_repository = AgentSessionRepository()
        workspace_user_repository = WorkspaceUserRepository()
        external_repository = ExternalChannelRepository()
        repository = ExternalModelSettingsRepository(
            session_manager=session_manager,
            external_channel_repository=external_repository,
            external_account_link_repository=ExternalAccountLinkRepository(
                session_manager=session_manager
            ),
            session_model_profile_repository=SessionModelProfileRepository(
                agent_repository=agent_repository,
                agent_session_repository=agent_session_repository,
                workspace_user_repository=workspace_user_repository,
                chat_write_request_repository=ChatWriteRequestRepository(),
                session_manager=session_manager,
            ),
            agent_repository=agent_repository,
            agent_session_repository=agent_session_repository,
        )
        actor = ExternalModelActorContext(
            provider=ExternalChannelProvider.DISCORD,
            connection_id=fixture.connection_id,
            configuration_generation=1,
            principal_id=principal.id,
            provider_tenant_id="100",
            provider_user_id=principal.provider_user_id,
            provider_display_name="Native user",
        )
        target = ExternalModelTargetContext(
            binding_id=binding_id,
            session_id=fixture.agent_session_id,
            agent_id=fixture.agent_id,
        )

        async with AsyncSession(rdb_engine) as disabling:
            await disabling.execute(
                sa.update(RDBUser)
                .where(RDBUser.id == user.id)
                .values(access_disabled_at=_at(1))
            )
            busy = await repository.open_editor(
                actor=actor,
                target=target,
                owner_interaction_key="disable-before-authorization",
                now=_at(1),
                offset=0,
                limit=10,
            )
            assert isinstance(busy, ExternalModelBusy)
            await disabling.rollback()

        async with (
            AsyncSession(rdb_engine) as authorized_session,
            AsyncSession(rdb_engine) as disabling,
        ):
            authorization = await repository._authorize(
                authorized_session,
                actor=actor,
                target=target,
            )
            assert authorization.target is not None
            await disabling.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError) as raised:
                await disabling.execute(
                    sa.update(RDBUser)
                    .where(RDBUser.id == user.id)
                    .values(access_disabled_at=_at(2))
                )
            assert getattr(raised.value.orig, "sqlstate", None) == "55P03"
            await disabling.rollback()
            await disabling.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError) as block_conflict:
                await external_repository.create_block_idempotent(
                    disabling,
                    ExternalChannelBlockCreate(
                        agent_id=fixture.agent_id,
                        principal_id=principal.id,
                        blocked_by_user_id=user.id,
                        reason=None,
                        removed_by_user_id=None,
                        removed_at=None,
                    ),
                )
            assert getattr(block_conflict.value.orig, "sqlstate", None) == "55P03"
            await disabling.rollback()
            await disabling.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError) as grant_conflict:
                await external_repository.delete_access_grant(
                    disabling,
                    grant_id=grant.id,
                )
            assert getattr(grant_conflict.value.orig, "sqlstate", None) == "55P03"
            await disabling.rollback()
            await disabling.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError) as member_conflict:
                await disabling.execute(
                    sa.delete(RDBWorkspaceUser).where(
                        RDBWorkspaceUser.workspace_id == connection.workspace_id,
                        RDBWorkspaceUser.user_id == user.id,
                    )
                )
            assert getattr(member_conflict.value.orig, "sqlstate", None) == "55P03"
            await disabling.rollback()
            await disabling.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError) as link_conflict:
                await disabling.execute(
                    sa.update(RDBExternalAccountLink)
                    .where(
                        RDBExternalAccountLink.workspace_id == connection.workspace_id,
                        RDBExternalAccountLink.user_id == user.id,
                    )
                    .values(revoked_at=_at(2))
                )
            assert getattr(link_conflict.value.orig, "sqlstate", None) == "55P03"
            await disabling.rollback()
            await disabling.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError) as archive_conflict:
                await disabling.execute(
                    sa.update(RDBAgentSession)
                    .where(RDBAgentSession.id == fixture.agent_session_id)
                    .values(status=AgentSessionStatus.ARCHIVED)
                )
            assert getattr(archive_conflict.value.orig, "sqlstate", None) == "55P03"

        opened = await repository.open_editor(
            actor=actor,
            target=target,
            owner_interaction_key="aba-draft",
            now=_at(3),
            offset=0,
            limit=10,
        )
        assert isinstance(opened, ExternalModelEditorReady)
        async with session_manager() as changing:
            await agent_session_repository.set_applied_inference_profile(
                changing,
                session_id=fixture.agent_session_id,
                model_target_label="temporary",
                reasoning_effort=None,
                enabled_execution_options=[],
            )
            await agent_session_repository.set_applied_inference_profile(
                changing,
                session_id=fixture.agent_session_id,
                model_target_label="default",
                reasoning_effort=None,
                enabled_execution_options=[],
            )
        stale = await repository.apply_draft(
            actor=actor,
            draft_id=opened.editor.draft.id,
            expected_selection_fingerprint=(opened.editor.draft.selection_fingerprint),
            apply_interaction_key="aba-apply",
            now=_at(4),
        )
        assert isinstance(stale.result, ExternalModelStale)
        assert stale.result.editor.current_generation == 2
        assert stale.notice_plan is None
        repeated_stale = await repository.apply_draft(
            actor=actor,
            draft_id=opened.editor.draft.id,
            expected_selection_fingerprint=(opened.editor.draft.selection_fingerprint),
            apply_interaction_key="aba-apply-repeated",
            now=_at(5),
        )
        assert isinstance(repeated_stale.result, ExternalModelStale)
        assert repeated_stale.notice_plan is None

        displayed = await repository.open_editor(
            actor=actor,
            target=target,
            owner_interaction_key="displayed-selection-draft",
            now=_at(6),
            offset=0,
            limit=10,
        )
        assert isinstance(displayed, ExternalModelEditorReady)
        async with session_manager() as concurrent_update:
            await concurrent_update.execute(
                sa.update(RDBExternalModelDraft)
                .where(RDBExternalModelDraft.id == displayed.editor.draft.id)
                .values(selected_enabled_execution_options=["fast"])
            )
        unseen = await repository.apply_draft(
            actor=actor,
            draft_id=displayed.editor.draft.id,
            expected_selection_fingerprint=(
                displayed.editor.draft.selection_fingerprint
            ),
            apply_interaction_key="displayed-selection-apply",
            now=_at(7),
        )
        assert isinstance(unseen.result, ExternalModelStale)
        assert unseen.notice_plan is None

        mutation_draft = await repository.open_editor(
            actor=actor,
            target=target,
            owner_interaction_key="mutation-before-purge",
            now=_at(8),
            offset=0,
            limit=10,
        )
        assert isinstance(mutation_draft, ExternalModelEditorReady)
        committed = await repository.apply_draft(
            actor=actor,
            draft_id=mutation_draft.editor.draft.id,
            expected_selection_fingerprint=(
                mutation_draft.editor.draft.selection_fingerprint
            ),
            apply_interaction_key="mutation-before-purge-apply",
            now=_at(9),
        )
        assert isinstance(committed.result, ExternalModelApplied)
        assert committed.notice_plan is not None

        removed_option = await repository.open_editor(
            actor=actor,
            target=target,
            owner_interaction_key="removed-option-draft",
            now=_at(8),
            offset=0,
            limit=10,
        )
        assert isinstance(removed_option, ExternalModelEditorReady)
        async with session_manager() as catalog_change:
            agent_row = await catalog_change.get(RDBAgent, fixture.agent_id)
            assert agent_row is not None
            assert agent_row.selectable_model_options is not None
            replacement = dict(agent_row.selectable_model_options[0])
            replacement["label"] = "replacement"
            agent_row.selectable_model_options = [replacement]
            agent_row.main_model_label = "replacement"
            agent_row.lightweight_model_label = "replacement"
        rejected = await repository.apply_draft(
            actor=actor,
            draft_id=removed_option.editor.draft.id,
            expected_selection_fingerprint=(
                removed_option.editor.draft.selection_fingerprint
            ),
            apply_interaction_key="removed-option-apply",
            now=_at(9),
        )
        assert isinstance(rejected.result, ExternalModelStale)
        assert rejected.result.editor.current_generation == 3
        assert rejected.notice_plan is None
        repeated_removed = await repository.apply_draft(
            actor=actor,
            draft_id=removed_option.editor.draft.id,
            expected_selection_fingerprint=(
                removed_option.editor.draft.selection_fingerprint
            ),
            apply_interaction_key="removed-option-apply-repeated",
            now=_at(10),
        )
        assert isinstance(repeated_removed.result, ExternalModelStale)
        assert repeated_removed.notice_plan is None
        async with session_manager() as verify_unchanged:
            unchanged = await agent_session_repository.get_by_id(
                verify_unchanged,
                fixture.agent_session_id,
            )
            assert unchanged is not None
            assert unchanged.applied_profile_generation == 3
            assert unchanged.applied_inference_profile is not None
            assert unchanged.applied_inference_profile.model_target_label == "default"

        async with session_manager() as purging:
            await ExternalChannelLifecycleRepository().purge_session_tree(
                purging,
                session_ids=[fixture.agent_session_id],
            )
            remaining_drafts = await purging.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalModelDraft)
                .where(RDBExternalModelDraft.session_id == fixture.agent_session_id)
            )
            remaining_mutations = await purging.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalModelMutation)
                .where(RDBExternalModelMutation.session_id == fixture.agent_session_id)
            )
            remaining_binding = await purging.get(
                RDBExternalChannelBinding,
                binding_id,
            )
            assert remaining_drafts == 0
            assert remaining_mutations == 1
            assert remaining_binding is None
            await purging.execute(
                sa.delete(RDBExternalModelMutation).where(
                    RDBExternalModelMutation.session_id == fixture.agent_session_id
                )
            )
            await purging.execute(
                sa.delete(RDBExternalChannelAccessGrant).where(
                    RDBExternalChannelAccessGrant.id == grant.id
                )
            )
            await purging.execute(
                sa.delete(RDBExternalAccountLink).where(
                    RDBExternalAccountLink.workspace_id == connection.workspace_id,
                    RDBExternalAccountLink.user_id == user.id,
                )
            )
            await purging.execute(
                sa.delete(RDBExternalChannelPrincipal).where(
                    RDBExternalChannelPrincipal.id == principal.id
                )
            )
            await purging.execute(
                sa.delete(RDBWorkspaceUser).where(
                    RDBWorkspaceUser.workspace_id == connection.workspace_id,
                    RDBWorkspaceUser.user_id == user.id,
                )
            )
            await purging.execute(sa.delete(RDBUser).where(RDBUser.id == user.id))
            await purging.execute(
                sa.delete(RDBExternalChannelIngressLease).where(
                    RDBExternalChannelIngressLease.connection_id
                    == fixture.connection_id
                )
            )
            await purging.execute(
                sa.delete(RDBExternalChannelAppClaim).where(
                    RDBExternalChannelAppClaim.connection_id == fixture.connection_id
                )
            )
            await purging.execute(
                sa.delete(RDBExternalChannelAgentRoute).where(
                    RDBExternalChannelAgentRoute.connection_id == fixture.connection_id
                )
            )
            await purging.execute(
                sa.delete(RDBExternalChannelResource).where(
                    RDBExternalChannelResource.connection_id == fixture.connection_id
                )
            )
            await purging.execute(
                sa.delete(RDBExternalChannelConnection).where(
                    RDBExternalChannelConnection.id == fixture.connection_id
                )
            )

    async def test_connection_lookup_is_redacted_and_provider_scoped(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Connection lookup retains ciphertext in storage but not its DTO."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()

        created = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        configuration = await repo.get_slack_http_configuration_by_provider_identity(
            rdb_session,
            provider_app_id="app-1",
            provider_tenant_id="tenant-1",
        )

        assert configuration is not None
        assert configuration.id == created.id
        assert not hasattr(created, "encrypted_credentials")
        assert created.provider is ExternalChannelProvider.SLACK
        by_id = await repo.get_connection_configuration(
            rdb_session,
            connection_id=created.id,
        )
        assert by_id is not None
        assert by_id.encrypted_credentials == "ciphertext-only"

    async def test_installation_identity_is_unique_across_workspaces(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """One active Slack App and Team installation has one callback owner."""
        first_workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-installation-first",
        )
        second_workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-installation-second",
        )
        repo = ExternalChannelRepository()
        await repo.create_connection(
            rdb_session,
            _connection_create(first_workspace_id),
        )

        with pytest.raises(
            IntegrityError,
            match="uq_external_channel_connections_installation_identity",
        ):
            async with rdb_session.begin_nested():
                await repo.create_connection(
                    rdb_session,
                    _connection_create(second_workspace_id),
                )

    async def test_released_disconnected_identity_can_be_added_again(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Clearing retained disconnected identity releases the installation."""
        first_workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-released-first",
        )
        second_workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-released-second",
        )
        repo = ExternalChannelRepository()
        first = await repo.create_connection(
            rdb_session,
            _connection_create(first_workspace_id),
        )
        terminated = await repo.terminate_connection_for_provider_event(
            rdb_session,
            connection_id=first.id,
            status=ExternalChannelConnectionStatus.DISCONNECTED,
            reason="app_uninstalled",
            now=_at(4),
            required_configuration_generation=None,
            required_socket_lease_owner=None,
            defer_provider_state_purge=False,
        )
        released = await repo.get_connection_configuration(
            rdb_session,
            connection_id=first.id,
        )

        second = await repo.create_connection(
            rdb_session,
            _connection_create(second_workspace_id),
        )

        assert terminated == ()
        assert released is not None
        assert released.status is ExternalChannelConnectionStatus.DISCONNECTED
        assert released.encrypted_credentials is None
        assert released.provider_tenant_id is None
        assert second.workspace_id == second_workspace_id
        assert second.provider_app_id == "app-1"
        assert second.provider_tenant_id == "tenant-1"

    async def test_provider_state_purge_can_follow_cleanup_target_capture(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Uninstall keeps credentials only until cleanup targets are captured."""
        workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-deferred-provider-purge",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )

        terminated = await repo.terminate_connection_for_provider_event(
            rdb_session,
            connection_id=connection.id,
            status=ExternalChannelConnectionStatus.DISCONNECTED,
            reason="app_uninstalled",
            now=_at(4),
            required_configuration_generation=None,
            required_socket_lease_owner=None,
            defer_provider_state_purge=True,
        )
        retained = await repo.get_connection_configuration(
            rdb_session,
            connection_id=connection.id,
        )

        assert terminated == ()
        assert retained is not None
        assert retained.status is ExternalChannelConnectionStatus.DISCONNECTED
        assert retained.encrypted_credentials is not None
        assert retained.provider_tenant_id == "tenant-1"

        assert await repo.purge_disconnected_connection_provider_state(
            rdb_session,
            connection_id=connection.id,
        )
        purged = await repo.get_connection_configuration(
            rdb_session,
            connection_id=connection.id,
        )

        assert purged is not None
        assert purged.encrypted_credentials is None
        assert purged.provider_tenant_id is None

    async def test_provider_lifecycle_rejects_stale_configuration_generation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A replaced configuration wins over an in-flight provider callback."""
        workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-stale-provider-lifecycle",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        stale_generation = connection.configuration_generation + 1

        terminated = await repo.terminate_connection_for_provider_event(
            rdb_session,
            connection_id=connection.id,
            status=ExternalChannelConnectionStatus.DISCONNECTED,
            reason="app_uninstalled",
            now=_at(4),
            required_configuration_generation=stale_generation,
            required_socket_lease_owner=None,
            defer_provider_state_purge=True,
        )
        reconnect_required = await repo.mark_connection_reconnect_required(
            rdb_session,
            connection_id=connection.id,
            reason="tokens_revoked",
            now=_at(4),
            required_configuration_generation=stale_generation,
            required_socket_lease_owner=None,
        )
        retained = await repo.get_connection_configuration(
            rdb_session,
            connection_id=connection.id,
        )

        assert terminated is None
        assert reconnect_required is False
        assert retained is not None
        assert retained.status is ExternalChannelConnectionStatus.ACTIVE

    async def test_connection_health_update_returns_refreshed_projection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Health updates return server-updated fields without lazy loading."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        created = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        configuration = await repo.get_connection_configuration(
            rdb_session,
            connection_id=created.id,
        )
        assert configuration is not None
        assert configuration.encrypted_credentials is not None

        updated = await repo.update_connection_health(
            rdb_session,
            connection_id=created.id,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_tenant_id="tenant-1",
            provider_bot_user_id="bot-1",
            capabilities={"supports_reply": True},
            checked_at=_at(3),
            expected_encrypted_credentials=configuration.encrypted_credentials,
            expected_configuration_generation=configuration.configuration_generation,
        )

        assert updated is not None
        assert updated.status is ExternalChannelConnectionStatus.ACTIVE
        assert updated.provider_tenant_id == "tenant-1"
        assert updated.provider_bot_user_id == "bot-1"
        assert updated.capabilities == {"supports_reply": True}
        assert updated.last_verified_at == _at(3)
        assert updated.last_health_at == _at(3)

    async def test_prepared_discord_callback_restores_ping_authority_on_retry(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A retry exposes only provisional PING authority before activation."""
        workspace_id = await _create_workspace(
            rdb_session,
            "discord-prepared-callback-retry",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "status": ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
                    "provider_app_id": "discord-app-retry",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-1"},
                }
            ),
        )

        prepared = await repo.prepare_discord_callback(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-retry",
            interaction_public_key="a" * 64,
            callback_selector_hash="retry-selector-hash",
        )
        configured = await repo.get_discord_http_configuration_by_selector_hash(
            rdb_session,
            selector_hash="retry-selector-hash",
        )

        assert prepared is True
        assert configured is not None
        assert configured.status is ExternalChannelConnectionStatus.CONFIGURING
        assert configured.capabilities == {"interaction_public_key": "a" * 64}

    async def test_discord_activation_reclaims_a_disconnected_app_claim(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A disconnected App history cannot block a later activation."""
        workspace_id = await _create_workspace(
            rdb_session,
            "discord-disconnected-app-claim",
        )
        repo = ExternalChannelRepository()
        stale = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "status": ExternalChannelConnectionStatus.DISCONNECTED,
                    "provider_app_id": "discord-app-reclaimed",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-1"},
                }
            ),
        )
        rdb_session.add(
            RDBExternalChannelAppClaim(
                provider=ExternalChannelProvider.DISCORD,
                provider_app_id="discord-app-reclaimed",
                connection_id=stale.id,
                claim_generation=1,
            )
        )
        replacement = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "provider_app_id": "discord-app-reclaimed",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-1"},
                }
            ),
        )
        await rdb_session.flush()

        prepared = await repo.prepare_discord_callback(
            rdb_session,
            connection_id=replacement.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=replacement.configuration_generation,
            provider_app_id="discord-app-reclaimed",
            interaction_public_key="a" * 64,
            callback_selector_hash="reclaimed-selector-hash",
        )
        assert prepared is True
        activated = await repo.activate_discord_connection(
            rdb_session,
            connection_id=replacement.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=replacement.configuration_generation,
            provider_app_id="discord-app-reclaimed",
            provider_tenant_id="guild-1",
            provider_bot_user_id=None,
            interaction_public_key="a" * 64,
            command_set=_discord_command_set(),
            capabilities=_discord_capabilities(),
            callback_selector_hash="reclaimed-selector-hash",
            checked_at=_at(1),
        )

        assert activated is not None
        assert activated.capabilities is not None
        assert activated.capabilities["discord_command_set"] == _discord_command_set()
        claim = await rdb_session.scalar(
            sa.select(RDBExternalChannelAppClaim).where(
                RDBExternalChannelAppClaim.provider == ExternalChannelProvider.DISCORD,
                RDBExternalChannelAppClaim.provider_app_id == "discord-app-reclaimed",
            )
        )
        assert claim is not None
        assert claim.connection_id == replacement.id
        assert claim.claim_generation == 2

    async def test_discord_gateway_terminal_transition_fences_stale_lease(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Only the current Gateway lease can suppress future scheduler claims."""
        workspace_id = await _create_workspace(
            rdb_session,
            "discord-gateway-terminal-transition",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "provider_app_id": "discord-app-terminal-1",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-terminal-1"},
                }
            ),
        )
        prepared = await repo.prepare_discord_callback(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-terminal-1",
            interaction_public_key="a" * 64,
            callback_selector_hash="terminal-selector-hash",
        )
        assert prepared is True
        activated = await repo.activate_discord_connection(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-terminal-1",
            provider_tenant_id="guild-terminal-1",
            provider_bot_user_id=None,
            interaction_public_key="a" * 64,
            command_set=_discord_command_set(),
            capabilities=_discord_capabilities(),
            callback_selector_hash="terminal-selector-hash",
            checked_at=_at(1),
        )
        assert activated is not None
        stale_claim = await repo.claim_discord_gateway_lease(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-stale",
            now=_at(2),
            lease_until=_at(3),
        )
        assert stale_claim is not None
        current_claim = await repo.claim_discord_gateway_lease(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-current",
            now=_at(4),
            lease_until=_at(10),
        )
        assert current_claim is not None

        stale_terminalized = await repo.mark_discord_gateway_reconnect_required(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-stale",
            lease_generation=stale_claim.lease.lease_generation,
            now=_at(5),
            reason="gateway_credentials_invalid",
        )
        terminalized = await repo.mark_discord_gateway_reconnect_required(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-current",
            lease_generation=current_claim.lease.lease_generation,
            now=_at(5),
            reason="gateway_credentials_invalid",
        )

        rdb_connection = await rdb_session.get(
            RDBExternalChannelConnection,
            connection.id,
        )
        lease = await rdb_session.scalar(
            sa.select(RDBExternalChannelIngressLease).where(
                RDBExternalChannelIngressLease.connection_id == connection.id
            )
        )

        assert stale_terminalized is False
        assert terminalized is True
        assert rdb_connection is not None
        assert (
            rdb_connection.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        )
        assert lease is not None
        assert lease.lease_owner is None
        assert lease.lease_until is None
        assert lease.gap_detected_at == _at(5)
        assert lease.gap_reason == "gateway_credentials_invalid"
        assert await repo.list_discord_gateway_connection_ids(rdb_session) == []

    async def test_discord_gateway_gap_and_active_transitions_are_fenced(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Project Gateway lifecycle health only from the current durable owner."""
        workspace_id = await _create_workspace(
            rdb_session,
            "discord-gateway-lifecycle-transition",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "provider_app_id": "discord-app-lifecycle-1",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-lifecycle-1"},
                }
            ),
        )
        prepared = await repo.prepare_discord_callback(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-lifecycle-1",
            interaction_public_key="a" * 64,
            callback_selector_hash="lifecycle-selector-hash",
        )
        assert prepared is True
        activated = await repo.activate_discord_connection(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-lifecycle-1",
            provider_tenant_id="guild-lifecycle-1",
            provider_bot_user_id=None,
            interaction_public_key="a" * 64,
            command_set=_discord_command_set(),
            capabilities=_discord_capabilities(),
            callback_selector_hash="lifecycle-selector-hash",
            checked_at=_at(1),
        )
        assert activated is not None
        claim = await repo.claim_discord_gateway_lease(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-current",
            now=_at(2),
            lease_until=_at(10),
        )
        assert claim is not None

        stale_gap = await repo.record_discord_gateway_gap(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-stale",
            lease_generation=claim.lease.lease_generation,
            now=_at(3),
            reason="gateway_disconnected",
        )
        gap_recorded = await repo.record_discord_gateway_gap(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-current",
            lease_generation=claim.lease.lease_generation,
            now=_at(3),
            reason="gateway_disconnected",
        )
        degraded = await repo.get_connection(
            rdb_session,
            connection_id=connection.id,
        )
        degraded_lease = await rdb_session.scalar(
            sa.select(RDBExternalChannelIngressLease).where(
                RDBExternalChannelIngressLease.connection_id == connection.id
            )
        )

        assert stale_gap is False
        assert gap_recorded is True
        assert degraded is not None
        assert degraded.status is ExternalChannelConnectionStatus.DEGRADED
        assert degraded_lease is not None
        assert degraded_lease.gap_detected_at == _at(3)
        assert degraded_lease.gap_reason == "gateway_disconnected"

        stale_active = await repo.mark_discord_gateway_active(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-stale",
            lease_generation=claim.lease.lease_generation,
            now=_at(4),
        )
        marked_active = await repo.mark_discord_gateway_active(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-current",
            lease_generation=claim.lease.lease_generation,
            now=_at(4),
        )
        recovered = await repo.get_connection(
            rdb_session,
            connection_id=connection.id,
        )

        assert stale_active is False
        assert marked_active is True
        assert recovered is not None
        assert recovered.status is ExternalChannelConnectionStatus.ACTIVE
        await rdb_session.refresh(degraded_lease)
        assert degraded_lease.gap_detected_at is None
        assert degraded_lease.gap_reason is None

    async def test_socket_lease_fences_owner_and_reclaims_after_expiry(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Only one manager owns a socket until its durable lease expires."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "transport": ExternalChannelTransport.SOCKET,
                    "status": ExternalChannelConnectionStatus.ACTIVE,
                    "http_callback_selector_hash": None,
                }
            ),
        )

        first = await repo.claim_socket_connection(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(1),
            lease_until=_at(3),
        )
        fenced = await repo.claim_socket_connection(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-2",
            now=_at(2),
            lease_until=_at(4),
        )
        reclaimed = await repo.claim_socket_connection(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-2",
            now=_at(4),
            lease_until=_at(6),
        )

        assert first is not None
        assert first.socket_lease_owner == "manager-1"
        assert fenced is None
        assert reclaimed is not None
        assert reclaimed.socket_lease_owner == "manager-2"

    async def test_socket_gap_is_visible_until_reconnection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Record transport gaps and clear them only after a leased reconnect."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "transport": ExternalChannelTransport.SOCKET,
                    "status": ExternalChannelConnectionStatus.ACTIVE,
                    "http_callback_selector_hash": None,
                }
            ),
        )
        claimed = await repo.claim_socket_connection(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(1),
            lease_until=_at(5),
        )
        assert claimed is not None

        recorded = await repo.record_socket_connection_gap(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(2),
            gap_reason="connection_closed",
        )
        degraded = await repo.get_connection(
            rdb_session,
            connection_id=connection.id,
        )
        active = await repo.mark_socket_connection_active(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(3),
        )
        recovered = await repo.get_connection(
            rdb_session,
            connection_id=connection.id,
        )

        assert recorded is True
        assert degraded is not None
        assert degraded.status is ExternalChannelConnectionStatus.DEGRADED
        assert degraded.socket_gap_reason == "connection_closed"
        assert active is True
        assert recovered is not None
        assert recovered.status is ExternalChannelConnectionStatus.ACTIVE
        assert recovered.socket_gap_reason is None


async def test_slack_presence_lease_is_configuration_fenced(
    rdb_session: AsyncSession,
) -> None:
    """Only the current generation owner can renew or project Slack presence."""
    workspace_id = await _create_workspace(
        rdb_session,
        "slack-presence-lease",
    )
    repository = ExternalChannelRepository()
    connection = await repository.create_connection(
        rdb_session,
        _connection_create(workspace_id),
    )

    assert await repository.list_slack_presence_connection_ids(rdb_session) == [
        connection.id
    ]
    claimed = await repository.claim_slack_presence_connection(
        rdb_session,
        connection_id=connection.id,
        lease_owner="presence-manager",
        now=_at(1),
        lease_until=_at(10),
    )

    assert claimed is not None
    stale_generation = claimed.configuration_generation + 1
    assert (
        await repository.renew_slack_presence_lease(
            rdb_session,
            connection_id=connection.id,
            lease_owner="presence-manager",
            required_configuration_generation=stale_generation,
            now=_at(2),
            lease_until=_at(11),
        )
        is False
    )
    assert (
        await repository.list_owned_slack_work_presence_targets(
            rdb_session,
            connection_id=connection.id,
            lease_owner="presence-manager",
            required_configuration_generation=stale_generation,
            now=_at(2),
        )
        is None
    )
    assert (
        await repository.list_owned_slack_work_presence_targets(
            rdb_session,
            connection_id=connection.id,
            lease_owner="presence-manager",
            required_configuration_generation=claimed.configuration_generation,
            now=_at(2),
        )
        == ()
    )
    assert await repository.renew_slack_presence_lease(
        rdb_session,
        connection_id=connection.id,
        lease_owner="presence-manager",
        required_configuration_generation=claimed.configuration_generation,
        now=_at(2),
        lease_until=_at(11),
    )
    assert await repository.release_slack_presence_lease(
        rdb_session,
        connection_id=connection.id,
        lease_owner="presence-manager",
        now=_at(3),
    )


def test_slack_presence_projects_awaiting_work_as_idle() -> None:
    """Awaiting Work keeps its Tracker identity without active processing presence."""
    connection = create_autospec(RDBExternalChannelConnection, instance=True)
    connection.capabilities = None
    binding = create_autospec(RDBExternalChannelBinding, instance=True)
    binding.id = "binding-1"
    binding.disconnected_at = None
    resource = create_autospec(RDBExternalChannelResource, instance=True)
    resource.labels = {"channel_id": "C1"}
    resource.status = ExternalChannelResourceStatus.ACTIVE
    resource.resource_type = ExternalChannelResourceType.PARENT_CHANNEL
    route = create_autospec(RDBExternalChannelAgentRoute, instance=True)
    route.agent_id = "agent-1"
    route.catalog_status = ExternalChannelRouteCatalogStatus.AVAILABLE
    agent = create_autospec(RDBAgent, instance=True)
    agent.id = "agent-1"
    agent.name = "Agent"
    agent.lifecycle_status = AgentLifecycleStatus.ACTIVE
    agent_session = create_autospec(RDBAgentSession, instance=True)
    agent_session.status = AgentSessionStatus.ACTIVE
    agent_session.stop_requested_at = None
    work = ChannelWorkState(
        schema_version=CHANNEL_WORK_STATE_SCHEMA_VERSION,
        binding_id="binding-1",
        work_cycle_id="work-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        tracker_visibility="visible",
        slack_presence_thread_ts="123.456",
        slack_presence_initiator_user_id=None,
        title="Investigating…",
        tasks=[],
        state_revision=3,
        desired_progress_revision=0,
        desired_progress=None,
        awaiting_input_run_id="run-request",
        finished_at=None,
        projection_parts=[],
    )

    target = _slack_work_presence_target(
        connection=connection,
        binding=binding,
        resource=resource,
        route=route,
        agent=agent,
        agent_session=agent_session,
        work=work,
    )

    assert target is not None
    assert target.desired_state == "idle"
    assert target.status_text is None


async def test_create_agent_route_enforces_mode_and_workspace_boundaries(
    rdb_session: AsyncSession,
) -> None:
    """Route creation locks the connection and rejects mismatched boundaries."""
    first_workspace = await _create_workspace(rdb_session, "route-boundary-first")
    second_workspace = await _create_workspace(rdb_session, "route-boundary-second")
    integration = RDBLLMProviderIntegration(
        workspace_id=first_workspace,
        provider=LLMProvider.ANTHROPIC,
        name="route-boundary-integration",
        encrypted_credentials="encrypted",
        config=None,
    )
    rdb_session.add(integration)
    await rdb_session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="route-boundary-model",
    )
    agent = RDBAgent(
        workspace_id=first_workspace,
        name="Route Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=(selection),
            lightweight_model_selection=(selection),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    foreign_agent = RDBAgent(
        workspace_id=second_workspace,
        name="Foreign Route Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=(selection),
            lightweight_model_selection=(selection),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    second_agent = RDBAgent(
        workspace_id=first_workspace,
        name="Second Route Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=(selection),
            lightweight_model_selection=(selection),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    rdb_session.add_all((agent, second_agent, foreign_agent))
    await rdb_session.flush()
    repository = ExternalChannelRepository()
    connection = await repository.create_connection(
        rdb_session, _connection_create(first_workspace)
    )
    create = ExternalChannelAgentRouteCreate(
        connection_id=connection.id,
        agent_id=agent.id,
        agent_id_snapshot=agent.id,
        route_mode=ExternalChannelRouteMode.DEDICATED,
        connection_app_mode=ExternalChannelAppMode.SINGLE,
        catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
        catalog_removed_at=None,
        catalog_removed_by_user_id=None,
    )
    route = await repository.create_agent_route(rdb_session, create)
    assert route.agent_id == agent.id
    assert route.agent_id_snapshot == agent.id
    with pytest.raises(
        IntegrityError,
        match="uq_external_channel_agent_routes_single_connection",
    ):
        async with rdb_session.begin_nested():
            await repository.create_agent_route(
                rdb_session,
                create.model_copy(
                    update={
                        "agent_id": second_agent.id,
                        "agent_id_snapshot": second_agent.id,
                    }
                ),
            )
    with pytest.raises(ValueError, match="App mode"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(
                update={"connection_app_mode": ExternalChannelAppMode.MULTI}
            ),
        )
    with pytest.raises(ValueError, match="Workspace"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(
                update={
                    "agent_id": foreign_agent.id,
                    "agent_id_snapshot": foreign_agent.id,
                }
            ),
        )
    with pytest.raises(ValueError, match="dedicated mode"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(update={"route_mode": ExternalChannelRouteMode.PLATFORM}),
        )
    with pytest.raises(ValueError, match="catalog-available"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(
                update={"catalog_status": ExternalChannelRouteCatalogStatus.REMOVED}
            ),
        )
    with pytest.raises(ValueError, match="catalog-removal metadata"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(update={"catalog_removed_at": _at(1)}),
        )
    with pytest.raises(ValueError, match="catalog-removal metadata"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(
                update={"catalog_removed_by_user_id": "not-a-route-owner"}
            ),
        )
