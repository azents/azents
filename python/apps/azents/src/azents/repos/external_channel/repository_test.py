"""ExternalChannelRepository tests."""

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel import (
    RDBExternalChannelAppClaim,
    RDBExternalChannelConnection,
    RDBExternalChannelIngressLease,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelConnectionCreate,
    ExternalChannelConversationPosition,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict


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
class TestExternalChannelRepository:
    """External Channel foundation repository tests."""

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
    )
    foreign_agent = RDBAgent(
        workspace_id=second_workspace,
        name="Foreign Route Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    second_agent = RDBAgent(
        workspace_id=first_workspace,
        name="Second Route Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
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
