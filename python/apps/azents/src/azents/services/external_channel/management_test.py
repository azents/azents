"""External Channel management orchestration tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelTransport,
)
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelConnection,
)
from azents.repos.external_channel.data import (
    ExternalChannelMultiConnectionDisconnect,
)
from azents.repos.external_channel.management import ExternalChannelManagementRepository
from azents.repos.external_channel.management_data import (
    ManagedBinding,
    ManagedChannelDefault,
    ManagedConnection,
    ManagedMultiRoute,
)
from azents.services.external_channel.connection import (
    ExternalChannelConnectionService,
)
from azents.services.external_channel.data import (
    DiscordConnectionConfiguration,
    DiscordConnectionCredentials,
)
from azents.services.external_channel.management import (
    ExternalChannelManagementNotFound,
    ExternalChannelManagementService,
    ExternalChannelResponseModeSetting,
    slack_manifest_guidance,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.testing.external_channel import make_provider_effect_plan


class _Lock:
    """Provide one owned coordination lease for management tests."""

    def acquire(self, **_: object) -> object:
        @asynccontextmanager
        async def owned() -> AsyncGenerator[object, None]:
            yield SimpleNamespace(assert_owned=AsyncMock())

        return owned()


class _RecordingLock:
    """Record coordination acquisition, ownership, and release order."""

    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def acquire(self, **_: object) -> object:
        self.events.append(f"{self.name}:acquire")

        @asynccontextmanager
        async def owned() -> AsyncGenerator[object, None]:
            self.events.append(f"{self.name}:enter")

            async def assert_owned() -> None:
                self.events.append(f"{self.name}:owned")

            try:
                yield SimpleNamespace(assert_owned=assert_owned)
            finally:
                self.events.append(f"{self.name}:exit")

        return owned()


def _connection() -> ManagedConnection:
    return ManagedConnection(
        id="connection-1",
        route_id="route-1",
        agent_id="agent-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=ExternalChannelConnectionStatus.DISCONNECTED,
        provider_app_id="A1",
        provider_tenant_id=None,
        provider_bot_user_id=None,
        open_access_enabled=True,
        credentials_configured=False,
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        disconnected_at=None,
    )


def _binding(
    response_mode: ExternalChannelResponseMode = (
        ExternalChannelResponseMode.MENTION_ONLY
    ),
) -> ManagedBinding:
    now = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    return ManagedBinding(
        id="binding-1",
        agent_session_id="session-1",
        provider=ExternalChannelProvider.SLACK,
        response_mode=response_mode,
        resource_type=ExternalChannelResourceType.THREAD,
        conversation_location=ExternalChannelConversationLocation.THREADS,
        resource_label="Channel thread",
        connected_at=now,
        disconnected_at=None,
        disconnect_reason=None,
        latest_activity_at=now,
        work=None,
    )


def _management_service(
    *,
    session: AsyncSession,
    repository: AsyncMock,
    agent_repository: AsyncMock,
    agent_admin_repository: AsyncMock,
    action_service: AsyncMock | None = None,
    conversation_lock: object | None = None,
    participation_lock: object | None = None,
) -> ExternalChannelManagementService:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    return ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=AsyncMock(),
        lifecycle_repository=AsyncMock(),
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=AsyncMock(),
        connection_service=AsyncMock(),
        discord_activation_service=AsyncMock(),
        action_service=AsyncMock() if action_service is None else action_service,
        access_service=AsyncMock(),
        conversation_lock=cast(
            Any,
            _Lock() if conversation_lock is None else conversation_lock,
        ),
        participation_lock=cast(
            Any,
            _Lock() if participation_lock is None else participation_lock,
        ),
    )


def _channel_default() -> ManagedChannelDefault:
    """Build one stable selected-Agent management projection."""
    now = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    return ManagedChannelDefault(
        id="default-1",
        provider_channel_id="channel-1",
        route_id="route-1",
        agent_id="agent-1",
        agent_name="Agent One",
        status=ExternalChannelChannelDefaultStatus.ACTIVE,
        configured_by_user_id="user-1",
        configured_by_principal_id=None,
        invalidated_at=None,
        invalidation_reason=None,
        created_at=now,
        updated_at=now,
    )


async def test_replace_multi_default_commits_before_cleanup_outside_locks() -> None:
    """Selected-Agent cleanup starts only after commit and coordination release."""
    events: list[str] = []
    expected_generation = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    connection = SimpleNamespace(
        id="connection-1",
        updated_at=expected_generation,
    )
    selected = _channel_default()
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit
    repository = AsyncMock()
    repository.get_multi_connection.return_value = connection
    first_plan = make_provider_effect_plan("default-cleanup-1")
    second_plan = make_provider_effect_plan("default-cleanup-2")

    async def replace(*_: object, **__: object) -> object:
        events.append("repository")
        return SimpleNamespace(
            channel_default=selected,
            changed=True,
            invalidated_setting_count=1,
            terminated_setup_claim_count=1,
            expired_interaction_count=2,
            disconnected_parent_binding_count=1,
            cleanup_plans=(first_plan, second_plan),
        )

    repository.replace_multi_channel_default.side_effect = replace
    action_service = AsyncMock()

    async def deliver(plan: ProviderEffectPlan) -> None:
        events.append("delivery:first" if plan is first_plan else "delivery:second")

    action_service.execute_terminal_control.side_effect = deliver
    service = _management_service(
        session=session,
        repository=repository,
        agent_repository=AsyncMock(),
        agent_admin_repository=AsyncMock(),
        action_service=action_service,
        conversation_lock=_RecordingLock("conversation", events),
        participation_lock=_RecordingLock("participation", events),
    )

    result = await service.replace_multi_channel_default(
        workspace_id="workspace-1",
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_channel_id="channel-1",
        route_id="route-1",
        user_id="user-1",
        expected_generation=expected_generation,
    )

    assert result.channel_default == selected
    assert result.changed is True
    assert result.invalidated_participation_setting_count == 1
    assert result.terminated_setup_claim_count == 1
    assert result.expired_interaction_count == 2
    assert result.disconnected_parent_binding_count == 1
    assert result.direct_cleanup_count == 2
    assert events == [
        "conversation:acquire",
        "conversation:enter",
        "conversation:owned",
        "participation:acquire",
        "participation:enter",
        "participation:owned",
        "repository",
        "commit",
        "participation:exit",
        "conversation:exit",
        "delivery:first",
        "delivery:second",
    ]


async def test_replace_same_multi_default_preserves_connection_generation() -> None:
    """An already-selected route remains a complete mutation no-op."""
    expected_generation = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    connection = SimpleNamespace(
        id="connection-1",
        updated_at=expected_generation,
    )
    session = AsyncMock(spec=AsyncSession)
    repository = AsyncMock()
    repository.get_multi_connection.return_value = connection
    repository.replace_multi_channel_default.return_value = SimpleNamespace(
        channel_default=_channel_default(),
        changed=False,
        invalidated_setting_count=0,
        terminated_setup_claim_count=0,
        expired_interaction_count=0,
        disconnected_parent_binding_count=0,
        cleanup_plans=(),
    )
    action_service = AsyncMock()
    service = _management_service(
        session=session,
        repository=repository,
        agent_repository=AsyncMock(),
        agent_admin_repository=AsyncMock(),
        action_service=action_service,
    )

    await service.replace_multi_channel_default(
        workspace_id="workspace-1",
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_channel_id="channel-1",
        route_id="route-1",
        user_id="user-1",
        expected_generation=expected_generation,
    )

    assert connection.updated_at == expected_generation
    session.commit.assert_awaited_once_with()
    action_service.execute_terminal_control.assert_not_awaited()


async def test_default_response_mode_read_projects_agent_value() -> None:
    """Visible Agent management state includes the concrete creation default."""
    session = AsyncMock(spec=AsyncSession)
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1",
        external_channel_default_response_mode=(
            ExternalChannelResponseMode.MENTION_ONLY
        ),
    )
    agent_admin_repository = AsyncMock()
    service = _management_service(
        session=session,
        repository=AsyncMock(),
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
    )

    result = await service.get_default_response_mode(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
    )

    assert result.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    agent_admin_repository.is_admin.assert_not_awaited()


async def test_default_response_mode_update_requires_agent_admin() -> None:
    """A non-admin cannot mutate the Agent-scoped creation default."""
    session = AsyncMock(spec=AsyncSession)
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = False
    service = _management_service(
        session=session,
        repository=AsyncMock(),
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
    )

    with pytest.raises(ExternalChannelManagementNotFound):
        await service.update_default_response_mode(
            workspace_id="workspace-1",
            agent_id="agent-1",
            workspace_user_id="workspace-user-1",
            setting=ExternalChannelResponseModeSetting(
                response_mode=ExternalChannelResponseMode.MENTION_ONLY
            ),
        )

    agent_repository.update_external_channel_default_response_mode.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_default_response_mode_update_does_not_rewrite_bindings() -> None:
    """Replacing the Agent default calls only the Agent repository mutation."""
    session = AsyncMock(spec=AsyncSession)
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_repository.update_external_channel_default_response_mode.return_value = (
        SimpleNamespace(
            workspace_id="workspace-1",
            external_channel_default_response_mode=(
                ExternalChannelResponseMode.MENTION_ONLY
            ),
        )
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = True
    repository = AsyncMock()
    service = _management_service(
        session=session,
        repository=repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
    )

    result = await service.update_default_response_mode(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        setting=ExternalChannelResponseModeSetting(
            response_mode=ExternalChannelResponseMode.MENTION_ONLY
        ),
    )

    assert result.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    agent_repository.update_external_channel_default_response_mode.assert_awaited_once_with(
        session,
        agent_id="agent-1",
        response_mode=ExternalChannelResponseMode.MENTION_ONLY,
    )
    repository.update_binding_response_mode.assert_not_awaited()
    session.commit.assert_awaited_once()


async def test_binding_response_mode_update_uses_full_ownership_scope() -> None:
    """The service supplies Workspace, Agent, Session, and binding ownership."""
    session = AsyncMock(spec=AsyncSession)
    repository = AsyncMock()
    repository.get_binding_mutation_scope.return_value = SimpleNamespace(
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        resource_type=ExternalChannelResourceType.THREAD,
    )
    repository.update_binding_response_mode.return_value = True
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = True
    service = _management_service(
        session=session,
        repository=repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
    )
    service.list_bindings = AsyncMock(return_value=[_binding()])

    result = await service.update_binding_response_mode(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        agent_session_id="session-1",
        binding_id="binding-1",
        setting=ExternalChannelResponseModeSetting(
            response_mode=ExternalChannelResponseMode.MENTION_ONLY
        ),
    )

    assert result.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    repository.update_binding_response_mode.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        agent_id="agent-1",
        agent_session_id="session-1",
        binding_id="binding-1",
        configured_by_user_id="user-1",
        response_mode=ExternalChannelResponseMode.MENTION_ONLY,
    )
    session.commit.assert_awaited_once()


async def test_parent_binding_response_mode_update_uses_participation_locks() -> None:
    """Parent response-mode mutation commits inside canonical coordination locks."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit
    repository = AsyncMock()
    repository.get_binding_mutation_scope.return_value = SimpleNamespace(
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
    )

    async def update(*_: object, **__: object) -> bool:
        events.append("repository")
        return True

    repository.update_binding_response_mode.side_effect = update
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = True
    service = _management_service(
        session=session,
        repository=repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        conversation_lock=_RecordingLock("conversation", events),
        participation_lock=_RecordingLock("participation", events),
    )
    service.list_bindings = AsyncMock(
        return_value=[
            _binding().model_copy(
                update={
                    "resource_type": ExternalChannelResourceType.PARENT_CHANNEL,
                    "conversation_location": (
                        ExternalChannelConversationLocation.CHANNEL
                    ),
                }
            )
        ]
    )

    result = await service.update_binding_response_mode(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        agent_session_id="session-1",
        binding_id="binding-1",
        setting=ExternalChannelResponseModeSetting(
            response_mode=ExternalChannelResponseMode.MENTION_ONLY
        ),
    )

    assert result.conversation_location is ExternalChannelConversationLocation.CHANNEL
    assert events == [
        "conversation:acquire",
        "conversation:enter",
        "conversation:owned",
        "participation:acquire",
        "participation:enter",
        "participation:owned",
        "repository",
        "commit",
        "participation:exit",
        "conversation:exit",
    ]


async def test_setup_discord_commits_route_before_callback_activation() -> None:
    """Dedicated setup cannot make provider ingress active before its route exists."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    domain_repository = AsyncMock()

    async def create_agent_route(*args: object, **kwargs: object) -> None:
        del args, kwargs
        events.append("route")

    domain_repository.create_agent_route.side_effect = create_agent_route
    connection_service = AsyncMock()
    connection_service.create_discord_connection.return_value = SimpleNamespace(
        connection=SimpleNamespace(id="connection-1")
    )
    activation_service = AsyncMock()

    async def activate(*, connection_id: str) -> object:
        assert connection_id == "connection-1"
        events.append("activate")
        return object()

    activation_service.activate.side_effect = activate
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = True
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=AsyncMock(),
        domain_repository=domain_repository,
        lifecycle_repository=AsyncMock(),
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=AsyncMock(),
        connection_service=connection_service,
        discord_activation_service=activation_service,
        action_service=AsyncMock(),
        access_service=AsyncMock(),
        conversation_lock=cast(Any, _Lock()),
        participation_lock=cast(Any, _Lock()),
    )
    managed = _connection().model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "status": ExternalChannelConnectionStatus.ACTIVE,
        }
    )
    service.list_connections = AsyncMock(return_value=[managed])

    result = await service.setup_discord(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        app_id="app-1",
        configuration=DiscordConnectionConfiguration(target_guild_id="guild-1"),
        credentials=DiscordConnectionCredentials(bot_token="discord-bot-token"),
    )

    assert result.connection == managed
    assert events == ["route", "commit", "activate"]
    activation_service.activate.assert_awaited_once_with(connection_id="connection-1")


async def test_update_discord_commits_reset_before_callback_activation() -> None:
    """Dedicated replacement fences durable authority before provider mutation."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    repository = AsyncMock()
    repository.get_connection.return_value = object()

    async def replace(*args: object, **kwargs: object) -> object:
        del args, kwargs
        events.append("reset")
        return object()

    repository.replace_discord_configuration.side_effect = replace
    activation_service = AsyncMock()

    async def activate(*, connection_id: str) -> object:
        assert connection_id == "connection-1"
        events.append("activate")
        return object()

    activation_service.activate.side_effect = activate
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = True
    connection_service = cast(
        ExternalChannelConnectionService,
        SimpleNamespace(
            credentials_codec=Mock(encrypt=Mock(return_value="encrypted-token"))
        ),
    )
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=AsyncMock(),
        lifecycle_repository=AsyncMock(),
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=AsyncMock(),
        connection_service=connection_service,
        discord_activation_service=activation_service,
        action_service=AsyncMock(),
        access_service=AsyncMock(),
        conversation_lock=cast(Any, _Lock()),
        participation_lock=cast(Any, _Lock()),
    )

    await service.update_discord(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        connection_id="connection-1",
        app_id="discord-app-1",
        configuration=DiscordConnectionConfiguration(target_guild_id="guild-1"),
        credentials=DiscordConnectionCredentials(bot_token="discord-bot-token"),
    )

    assert events == ["reset", "commit", "activate"]
    repository.replace_discord_configuration.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        agent_id="agent-1",
        connection_id="connection-1",
        provider_app_id="discord-app-1",
        encrypted_credentials="encrypted-token",
        provider_config={"provider": "discord", "target_guild_id": "guild-1"},
    )


async def test_update_multi_discord_commits_reset_before_callback_activation() -> None:
    """Multi replacement cannot invoke Discord before durable fencing commits."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    repository = AsyncMock()

    async def replace(*args: object, **kwargs: object) -> object:
        del args, kwargs
        events.append("reset")
        return object()

    repository.replace_multi_discord_configuration.side_effect = replace
    activation_service = AsyncMock()

    async def activate(*, connection_id: str) -> object:
        assert connection_id == "connection-1"
        events.append("activate")
        return object()

    activation_service.activate.side_effect = activate
    connection_service = cast(
        ExternalChannelConnectionService,
        SimpleNamespace(
            credentials_codec=Mock(encrypt=Mock(return_value="encrypted-token"))
        ),
    )
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=AsyncMock(),
        lifecycle_repository=AsyncMock(),
        agent_repository=AsyncMock(),
        agent_admin_repository=AsyncMock(),
        workspace_user_repository=AsyncMock(),
        connection_service=connection_service,
        discord_activation_service=activation_service,
        action_service=AsyncMock(),
        access_service=AsyncMock(),
        conversation_lock=cast(Any, _Lock()),
        participation_lock=cast(Any, _Lock()),
    )

    await service.update_multi_discord(
        workspace_id="workspace-1",
        connection_id="connection-1",
        app_id="discord-app-1",
        configuration=DiscordConnectionConfiguration(target_guild_id="guild-1"),
        credentials=DiscordConnectionCredentials(bot_token="discord-bot-token"),
    )

    assert events == ["reset", "commit", "activate"]
    repository.replace_multi_discord_configuration.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        connection_id="connection-1",
        provider_app_id="discord-app-1",
        encrypted_credentials="encrypted-token",
        provider_config={"provider": "discord", "target_guild_id": "guild-1"},
    )


async def test_discord_replacement_failure_leaves_durable_fence_committed() -> None:
    """Activation failure retains configuring state instead of restoring authority."""
    session = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    repository = AsyncMock()
    repository.replace_multi_discord_configuration.return_value = object()
    activation_service = AsyncMock()
    activation_service.activate.side_effect = ValueError("Discord callback failed.")
    connection_service = cast(
        ExternalChannelConnectionService,
        SimpleNamespace(
            credentials_codec=Mock(encrypt=Mock(return_value="encrypted-token"))
        ),
    )
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=AsyncMock(),
        lifecycle_repository=AsyncMock(),
        agent_repository=AsyncMock(),
        agent_admin_repository=AsyncMock(),
        workspace_user_repository=AsyncMock(),
        connection_service=connection_service,
        discord_activation_service=activation_service,
        action_service=AsyncMock(),
        access_service=AsyncMock(),
        conversation_lock=cast(Any, _Lock()),
        participation_lock=cast(Any, _Lock()),
    )

    with pytest.raises(ValueError, match="Discord callback failed"):
        await service.update_multi_discord(
            workspace_id="workspace-1",
            connection_id="connection-1",
            app_id="discord-app-1",
            configuration=DiscordConnectionConfiguration(target_guild_id="guild-1"),
            credentials=DiscordConnectionCredentials(bot_token="discord-bot-token"),
        )

    session.commit.assert_awaited_once()
    activation_service.activate.assert_awaited_once_with(connection_id="connection-1")


async def test_replace_discord_configuration_invalidates_prior_authority() -> None:
    """Credential replacement clears callback, identity, health, and lease state."""
    connection = cast(
        RDBExternalChannelConnection,
        SimpleNamespace(
            id="connection-1",
            provider=ExternalChannelProvider.DISCORD,
            transport=ExternalChannelTransport.HTTP,
            provider_app_id="old-app",
            provider_tenant_id="old-guild",
            provider_bot_user_id="old-bot",
            http_callback_selector_hash="old-selector",
            encrypted_credentials="old-encrypted",
            capabilities={"interaction_public_key": "old-key"},
            provider_config={"target_guild_id": "old-guild"},
            configuration_generation=7,
            status=ExternalChannelConnectionStatus.ACTIVE,
            last_verified_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
            last_health_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
            disconnected_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
            socket_lease_owner="worker-1",
            socket_lease_until=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
            socket_heartbeat_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
            socket_gap_detected_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
            socket_gap_reason="gap",
        ),
    )
    route = cast(
        RDBExternalChannelAgentRoute,
        SimpleNamespace(
            id="route-1",
            agent_id="agent-1",
            open_access_enabled=True,
        ),
    )
    session = AsyncMock(spec=AsyncSession)
    repository = ExternalChannelManagementRepository()
    repository.get_connection = AsyncMock(return_value=(connection, route))

    result = await repository.replace_discord_configuration(
        session,
        workspace_id="workspace-1",
        agent_id="agent-1",
        connection_id="connection-1",
        provider_app_id="discord-app-1",
        encrypted_credentials="encrypted-token",
        provider_config={"provider": "discord", "target_guild_id": "guild-1"},
    )

    assert result is not None
    assert result.provider is ExternalChannelProvider.DISCORD
    assert result.status is ExternalChannelConnectionStatus.CONFIGURING
    assert result.provider_config == {
        "provider": "discord",
        "target_guild_id": "guild-1",
    }
    assert connection.provider_app_id == "discord-app-1"
    assert connection.provider_tenant_id is None
    assert connection.provider_bot_user_id is None
    assert connection.http_callback_selector_hash is None
    assert connection.encrypted_credentials == "encrypted-token"
    assert connection.capabilities is None
    assert connection.configuration_generation == 8
    assert connection.status is ExternalChannelConnectionStatus.CONFIGURING
    assert connection.last_verified_at is None
    assert connection.last_health_at is None
    assert connection.disconnected_at is None
    assert connection.socket_lease_owner is None
    assert connection.socket_lease_until is None
    assert connection.socket_heartbeat_at is None
    assert connection.socket_gap_detected_at is None
    assert connection.socket_gap_reason is None


def _multi_route(
    *,
    status: ExternalChannelRouteCatalogStatus = (
        ExternalChannelRouteCatalogStatus.AVAILABLE
    ),
) -> ManagedMultiRoute:
    now = datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC)
    return ManagedMultiRoute(
        id="route-1",
        agent_id="agent-1",
        agent_id_snapshot="agent-1",
        agent_name="Agent One",
        catalog_status=status,
        catalog_removed_at=None,
        created_at=now,
        updated_at=now,
    )


def test_socket_manifest_keeps_required_bot_events_without_callback() -> None:
    """Socket Mode manifests still contain every subscribed Bot Event."""
    guidance = slack_manifest_guidance(
        ExternalChannelTransport.SOCKET,
        callback_url="https://callbacks.example.test/external-channel/v1/slack/events",
        app_name="Incident Agent",
    )

    settings = guidance.manifest["settings"]
    assert isinstance(settings, dict)
    subscriptions = settings["event_subscriptions"]
    assert isinstance(subscriptions, dict)
    assert subscriptions["bot_events"] == list(guidance.event_subscriptions)
    assert "channels:read" in guidance.bot_scopes
    assert "groups:read" in guidance.bot_scopes
    assert "files:read" in guidance.bot_scopes
    assert "files:write" in guidance.bot_scopes
    assert "commands" in guidance.bot_scopes
    assert "request_url" not in subscriptions
    assert settings["interactivity"] == {"is_enabled": True}
    features = guidance.manifest["features"]
    assert isinstance(features, dict)
    assert features["slash_commands"] == [
        {
            "command": "/azents",
            "description": "Open Azents conversation settings",
            "usage_hint": "settings",
            "should_escape": False,
        }
    ]
    shortcuts = features["shortcuts"]
    assert isinstance(shortcuts, list)
    assert [
        shortcut["callback_id"] for shortcut in shortcuts if isinstance(shortcut, dict)
    ] == [
        "azents_ask_agent",
        "azents_conversation_settings",
    ]
    assert guidance.callback_url is None
    assert "signing_secret" not in guidance.manifest_json


def test_http_manifest_routes_commands_interactivity_and_events_to_callback() -> None:
    """HTTP Apps use the fixed authenticated callback for every Slack surface."""
    callback_url = "https://callbacks.example.test/external-channel/v1/slack/events"
    guidance = slack_manifest_guidance(
        ExternalChannelTransport.HTTP,
        callback_url=callback_url,
        app_name="Incident Agent",
    )

    features = guidance.manifest["features"]
    settings = guidance.manifest["settings"]
    assert isinstance(features, dict)
    assert isinstance(settings, dict)
    slash_commands = features["slash_commands"]
    interactivity = settings["interactivity"]
    subscriptions = settings["event_subscriptions"]
    assert isinstance(slash_commands, list)
    assert isinstance(slash_commands[0], dict)
    assert isinstance(interactivity, dict)
    assert isinstance(subscriptions, dict)
    assert slash_commands[0]["url"] == callback_url
    assert interactivity["request_url"] == callback_url
    assert subscriptions["request_url"] == callback_url
    assert guidance.callback_url == callback_url


async def test_add_multi_route_returns_existing_available_association() -> None:
    """Repeated catalog addition is idempotent under the connection lock."""
    session = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    repository = AsyncMock()
    repository.get_multi_connection.return_value = SimpleNamespace(id="connection-1")
    existing = _multi_route()
    repository.get_multi_route_by_agent.return_value = existing
    domain_repository = AsyncMock()
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=domain_repository,
        lifecycle_repository=AsyncMock(),
        agent_repository=agent_repository,
        agent_admin_repository=AsyncMock(),
        workspace_user_repository=AsyncMock(),
        connection_service=AsyncMock(),
        discord_activation_service=AsyncMock(),
        action_service=AsyncMock(),
        access_service=AsyncMock(),
        conversation_lock=cast(Any, _Lock()),
        participation_lock=cast(Any, _Lock()),
    )

    result = await service.add_multi_route(
        workspace_id="workspace-1",
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        agent_id="agent-1",
    )

    assert result == existing
    repository.get_multi_route_by_agent.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        agent_id="agent-1",
    )
    domain_repository.create_agent_route.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_repeated_disconnect_reterminalizes_connection() -> None:
    """An already disconnected row still passes through terminalization."""
    connection = SimpleNamespace(
        status=ExternalChannelConnectionStatus.DISCONNECTED,
    )
    route = SimpleNamespace(id="route-1")
    session = AsyncMock(spec=AsyncSession)
    scalars = Mock()
    scalars.all.return_value = []
    session.scalars.return_value = scalars
    repository = ExternalChannelManagementRepository()
    repository.get_connection = AsyncMock(return_value=(connection, route))
    now = datetime.datetime.now(datetime.UTC)

    cleanup_ids = await repository.begin_connection_disconnect(
        session,
        workspace_id="workspace-1",
        agent_id="agent-1",
        connection_id="connection-1",
        now=now,
    )

    assert cleanup_ids == ()
    assert connection.status is ExternalChannelConnectionStatus.DISCONNECTING
    repository.get_connection.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        agent_id="agent-1",
        connection_id="connection-1",
        lock=True,
        include_disconnected=True,
    )
    session.flush.assert_awaited_once()


async def test_disconnect_prepares_cleanup_before_terminal_secret_purge() -> None:
    """Provider cleanup retains its target while terminal state commits first."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    repository = AsyncMock()
    repository.get_connection.return_value = object()
    plan = make_provider_effect_plan("single-disconnect")

    async def begin_disconnect(
        *args: object,
        **kwargs: object,
    ) -> tuple[ProviderEffectPlan, ...]:
        events.append("begin")
        return (plan,)

    async def complete_disconnect(*args: object, **kwargs: object) -> ManagedConnection:
        events.append("complete")
        return _connection()

    repository.begin_connection_disconnect.side_effect = begin_disconnect
    repository.complete_connection_disconnect.side_effect = complete_disconnect
    lifecycle_repository = AsyncMock()

    async def disconnect_single(*args: object, **kwargs: object) -> object:
        events.append("lifecycle")
        return object()

    lifecycle_repository.disconnect_single_connection.side_effect = disconnect_single

    action_service = AsyncMock()

    async def execute_terminal_control(effect: ProviderEffectPlan) -> None:
        assert effect is plan
        events.append("delivery")

    action_service.execute_terminal_control.side_effect = execute_terminal_control
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = True

    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=AsyncMock(),
        lifecycle_repository=lifecycle_repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=AsyncMock(),
        connection_service=AsyncMock(),
        discord_activation_service=AsyncMock(),
        action_service=action_service,
        access_service=AsyncMock(),
        conversation_lock=cast(Any, _Lock()),
        participation_lock=cast(Any, _Lock()),
    )

    result = await service.disconnect_connection(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        connection_id="connection-1",
    )

    assert result.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert events == [
        "begin",
        "commit",
        "lifecycle",
        "complete",
        "commit",
        "delivery",
    ]


async def test_multi_disconnect_captures_cleanup_before_provider_state_purge() -> None:
    """Multi disconnect captures cleanup before it purges provider state."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    now = datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC)
    connection = SimpleNamespace(id="connection-1", updated_at=now)
    plan = make_provider_effect_plan("multi-disconnect")
    disconnected = ExternalChannelMultiConnectionDisconnect(
        disconnected_route_count=1,
        invalidated_default_count=0,
        invalidated_participation_setting_count=0,
        terminated_setup_claim_count=0,
        expired_admission_count=0,
        expired_access_request_count=0,
        unavailable_resource_count=0,
        disconnected_binding_count=1,
        cleanup_plans=(plan,),
    )
    repository = AsyncMock()
    repository.get_multi_connection.return_value = connection
    lifecycle_repository = AsyncMock()

    async def disconnect_multi(*args: object, **kwargs: object) -> object:
        events.append("disconnect")
        assert kwargs["defer_provider_state_purge"] is True
        return disconnected

    async def purge(*args: object, **kwargs: object) -> int:
        events.append("purge")
        return 1

    lifecycle_repository.disconnect_multi_connection.side_effect = disconnect_multi
    lifecycle_repository.purge_disconnected_connection_provider_state.side_effect = (
        purge
    )
    action_service = AsyncMock()

    async def deliver(value: ProviderEffectPlan) -> None:
        assert value is plan
        events.append("delivery")

    action_service.execute_terminal_control.side_effect = deliver
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=AsyncMock(),
        lifecycle_repository=lifecycle_repository,
        agent_repository=AsyncMock(),
        agent_admin_repository=AsyncMock(),
        workspace_user_repository=AsyncMock(),
        connection_service=AsyncMock(),
        discord_activation_service=AsyncMock(),
        action_service=action_service,
        access_service=AsyncMock(),
        conversation_lock=cast(Any, _Lock()),
        participation_lock=cast(Any, _Lock()),
    )

    result = await service.disconnect_multi_connection(
        workspace_id="workspace-1",
        connection_id=connection.id,
        provider=ExternalChannelProvider.SLACK,
        expected_generation=now,
    )

    assert result.disconnected_binding_count == 1
    assert events == ["disconnect", "purge", "commit", "delivery"]
