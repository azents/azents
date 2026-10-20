"""Single App validation and final publication cannot revive a deleting Agent."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from azents.core.agent_mutation import AgentMutationReadOnly
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
)
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime_removal.repository_test import _create_agent
from azents.repos.discord_connection_operations import (
    DiscordConnectionOperationRepository,
)
from azents.repos.external_channel.agent_mutation import require_active_single_app_agent
from azents.repos.external_channel.connection import ExternalChannelConnectionRepository
from azents.repos.external_channel.connection_test import _connection_create
from azents.repos.external_channel.data import ExternalChannelAgentRouteCreate
from azents.repos.external_channel.management_operations import (
    ExternalChannelManagementOperationRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


@pytest.mark.parametrize(
    "mode", [ExternalChannelAppMode.SINGLE, ExternalChannelAppMode.MULTI]
)
async def test_activation_scope_preserves_shared_configuration(
    rdb_session: WriteSession, mode: ExternalChannelAppMode
) -> None:
    fixture = await _create_agent(rdb_session)
    repo = ExternalChannelRepository()
    connection = await repo.create_connection(
        rdb_session,
        _connection_create(fixture.workspace_id).model_copy(update={"app_mode": mode}),
    )
    if mode is ExternalChannelAppMode.SINGLE:
        await repo.create_agent_route(
            rdb_session,
            ExternalChannelAgentRouteCreate(
                connection_id=connection.id,
                agent_id=fixture.agent_id,
                agent_id_snapshot=fixture.agent_id,
                route_mode=ExternalChannelRouteMode.DEDICATED,
                connection_app_mode=mode,
                catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                catalog_removed_at=None,
                catalog_removed_by_user_id=None,
            ),
        )
    await require_active_single_app_agent(rdb_session, connection_id=connection.id)
    await AgentRepository().mark_decommissioning(rdb_session, fixture.agent_id)
    if mode is ExternalChannelAppMode.MULTI:
        await require_active_single_app_agent(rdb_session, connection_id=connection.id)
        return

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        yield rdb_session

    connections = ExternalChannelConnectionRepository(repo, manager)
    discord = DiscordConnectionOperationRepository(manager, repo)
    management = object.__new__(ExternalChannelManagementOperationRepository)
    management.session_manager = manager
    with pytest.raises(AgentMutationReadOnly):
        await connections.load_connection_configuration(
            workspace_id=fixture.workspace_id, connection_id=connection.id
        )
    with pytest.raises(AgentMutationReadOnly):
        await connections.update_connection_health(
            connection_id=connection.id,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_tenant_id=None,
            provider_bot_user_id=None,
            capabilities=None,
            checked_at=datetime.datetime.now(datetime.UTC),
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=1,
        )
    with pytest.raises(AgentMutationReadOnly):
        await discord.get_configuration(connection.id)
    with pytest.raises(AgentMutationReadOnly):
        await discord.prepare_callback(
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=1,
            provider_app_id="app-operation-test",
            interaction_public_key="ab" * 32,
            callback_selector_hash="cd" * 32,
        )
    with pytest.raises(AgentMutationReadOnly):
        await discord.activate(
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=1,
            provider_app_id="app-operation-test",
            provider_tenant_id="tenant",
            provider_bot_user_id=None,
            interaction_public_key="ab" * 32,
            command_set={},
            capabilities={},
            callback_selector_hash="cd" * 32,
            checked_at=datetime.datetime.now(datetime.UTC),
        )
    with pytest.raises(AgentMutationReadOnly):
        await management.replace_slack_configuration(
            workspace_id=fixture.workspace_id,
            connection_id=connection.id,
            agent_id=fixture.agent_id,
            app_id="replacement",
            encrypted="new-ciphertext",
            transport=ExternalChannelTransport.HTTP,
        )
    with pytest.raises(AgentMutationReadOnly):
        await management.replace_discord_configuration(
            workspace_id=fixture.workspace_id,
            connection_id=connection.id,
            agent_id=fixture.agent_id,
            app_id="replacement",
            encrypted="new-ciphertext",
            provider_config={},
        )
