"""Isolated PostgreSQL authority, atomicity and native RO observation regressions."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.core.external_channel_participation import ExternalChannelParticipationError
from azents.core.external_channel_selection import ExternalChannelSelectorError
from azents.core.external_channel_selector_state import (
    ExternalChannelSelectorState,
    projection_with_selector_state,
    selector_state_from_interaction,
)
from azents.core.external_channel_shortcut_source import (
    ShortcutSelectionUnavailable,
    ShortcutSourceProjection,
)
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel import (
    RDBExternalChannelConversationPosition,
    RDBExternalChannelInteraction,
    RDBExternalChannelResource,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelChannelDefaultCreate,
    ExternalChannelConnection,
    ExternalChannelConversationPositionCreate,
    ExternalChannelInteraction,
    ExternalChannelInteractionCreate,
    ExternalChannelParticipationSetting,
    ExternalChannelParticipationSettingCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelResourceCreate,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.interaction_operations import (
    ExternalChannelInteractionOperations,
)
from azents.repos.external_channel.management import ExternalChannelManagementRepository
from azents.repos.external_channel.participation_operations import (
    ExternalChannelParticipationOperations,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.repository_test import _connection_create
from azents.repos.external_channel.selector_operations import (
    ExternalChannelSelectorOperations,
)
from azents.repos.external_channel.shortcut_source_operations import (
    ExternalChannelShortcutSourceOperations,
)
from azents.repos.workspace import WorkspaceRepository
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


@dataclass(frozen=True)
class _Graph:
    repository: ExternalChannelRepository
    write: SessionManager[WriteSession]
    read: SessionManager[ReadSession]
    connection: ExternalChannelConnection
    interaction: ExternalChannelInteraction
    principal_id: str
    resource_id: str
    position_id: str
    route_ids: tuple[str, str]
    setting: ExternalChannelParticipationSetting
    now: datetime.datetime

    def selectors(
        self, repository: ExternalChannelRepository | None = None
    ) -> ExternalChannelSelectorOperations:
        return ExternalChannelSelectorOperations(
            session_manager=self.write,
            read_session_manager=self.read,
            repository=repository or self.repository,
        )

    def interactions(
        self, read: SessionManager[ReadSession] | None = None
    ) -> ExternalChannelInteractionOperations:
        return ExternalChannelInteractionOperations(
            session_manager=self.write,
            read_session_manager=read or self.read,
            repository=self.repository,
        )

    def participation(
        self, repository: ExternalChannelRepository | None = None
    ) -> ExternalChannelParticipationOperations:
        return ExternalChannelParticipationOperations(
            session_manager=self.write,
            read_session_manager=self.read,
            repository=repository or self.repository,
            management_repository=ExternalChannelManagementRepository.create(),
            agent_repository=AgentRepository(),
            workspace_repository=WorkspaceRepository(),
        )


@pytest_asyncio.fixture
async def graph(rdb_engine: AsyncEngine, latest_db_schema: None) -> _Graph:
    """Commit unique owners on independent native PostgreSQL scopes."""
    del latest_db_schema
    write = create_read_write_session_manager(rdb_engine)
    read = create_read_only_session_manager(rdb_engine)
    repository = ExternalChannelRepository.create()
    suffix = uuid4().hex
    now = datetime.datetime.now(datetime.UTC)
    async with write() as session:
        created = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(name="Selection ownership", handle=f"selection-{suffix}"),
        )
        assert isinstance(created, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session, f"selection-{suffix}"
        )
        assert workspace_id is not None
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace_id,
            provider=LLMProvider.ANTHROPIC,
            name="Selection test",
            encrypted_credentials="fixture",
            config=None,
        )
        session.write_session.add(integration)
        await session.write_session.flush()
        selection = make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="fixture-model",
        )
        agents = [
            RDBAgent(
                workspace_id=workspace_id,
                name=name,
                model_selection=selection,
                lightweight_model_selection=selection,
                selectable_model_options=make_test_selectable_model_option_dicts(
                    model_selection=selection,
                    lightweight_model_selection=selection,
                ),
                main_model_label="default",
                lightweight_model_label="lightweight",
            )
            for name in ("Alpha", "Zeta")
        ]
        session.write_session.add_all(agents)
        await session.write_session.flush()
        connection = await repository.create_connection(
            session,
            _connection_create(workspace_id).model_copy(
                update={
                    "app_mode": ExternalChannelAppMode.MULTI,
                    "provider_tenant_id": suffix,
                    "provider_app_id": suffix,
                }
            ),
        )
        principal = await repository.create_principal_idempotent(
            session,
            ExternalChannelPrincipalCreate(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id=suffix,
                provider_user_id="human",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name="Human",
                avatar_url=None,
                profile=None,
            ),
        )
        position = await repository.create_conversation_position_idempotent(
            session,
            ExternalChannelConversationPositionCreate(
                connection_id=connection.id,
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="channel",
                provider_thread_key=None,
                read_through_position=None,
            ),
        )
        resource = await repository.create_resource_idempotent(
            session,
            ExternalChannelResourceCreate(
                connection_id=connection.id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key=f"slack:{suffix}:channel:100",
                labels={"channel_id": "channel", "thread_ts": "100"},
                status=ExternalChannelResourceStatus.ACTIVE,
                latest_activity_at=now,
                unavailable_at=None,
                deleted_at=None,
            ),
        )
        routes = [
            await repository.create_agent_route(
                session,
                ExternalChannelAgentRouteCreate(
                    connection_id=connection.id,
                    agent_id=agent.id,
                    agent_id_snapshot=agent.id,
                    route_mode=ExternalChannelRouteMode.DEDICATED,
                    connection_app_mode=ExternalChannelAppMode.MULTI,
                    catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                    catalog_removed_at=None,
                    catalog_removed_by_user_id=None,
                ),
            )
            for agent in agents
        ]
        state = ExternalChannelSelectorState(
            connection_id=connection.id,
            resource_id=resource.id,
            principal_id=principal.id,
            conversation_position_id=position.id,
            trigger_provider_message_key=f"slack:{suffix}:channel:100",
            range_start_position=None,
            trigger_position="100",
            selected_route_id=None,
        )
        admitted = await repository.admit_interaction(
            session,
            ExternalChannelInteractionCreate(
                connection_id=connection.id,
                transport=ExternalChannelTransport.HTTP,
                provider_interaction_key="selector",
                interaction_type=ExternalChannelInteractionType.SHORTCUT,
                callback_id=None,
                action_id=None,
                principal_id=principal.id,
                setup_claim_id=None,
                resource_correlation_key="channel:100",
                projection=projection_with_selector_state({}, state),
                status=ExternalChannelInteractionStatus.ACCEPTED,
                expires_at=now + datetime.timedelta(hours=1),
                error_kind=None,
                error_summary=None,
            ),
        )
        processing = await repository.transition_interaction(
            session,
            interaction_id=admitted.interaction.id,
            status=ExternalChannelInteractionStatus.PROCESSING,
            error_kind=None,
            error_summary=None,
            transitioned_at=now,
        )
        assert processing is not None
        await repository.create_channel_default(
            session,
            ExternalChannelChannelDefaultCreate(
                connection_id=connection.id,
                provider_channel_id="channel",
                route_id=routes[0].id,
                status=ExternalChannelChannelDefaultStatus.ACTIVE,
                configured_by_user_id=None,
                configured_by_principal_id=principal.id,
                invalidated_at=None,
                invalidation_reason=None,
            ),
        )
        setting = await repository.create_participation_setting(
            session,
            ExternalChannelParticipationSettingCreate(
                connection_id=connection.id,
                provider_parent_channel_id="channel",
                route_id=routes[0].id,
                location=ExternalChannelConversationLocation.THREADS,
                response_mode=ExternalChannelResponseMode.MENTION_ONLY,
                settings_generation=1,
                configured_by_user_id=None,
                configured_by_principal_id=principal.id,
                status=ExternalChannelParticipationSettingStatus.ACTIVE,
                invalidated_at=None,
                invalidation_reason=None,
            ),
        )
    return _Graph(
        repository=repository,
        write=write,
        read=read,
        connection=connection,
        interaction=processing,
        principal_id=principal.id,
        resource_id=resource.id,
        position_id=position.id,
        route_ids=(routes[0].id, routes[1].id),
        setting=setting,
        now=now,
    )


async def test_native_read_operations_do_not_wait_for_writer_row_lock(
    graph: _Graph,
) -> None:
    """Read-only observations do not wait on an uncommitted writer row lock."""
    async with graph.write() as writer:
        locked = await writer.write_session.scalar(
            sa.select(RDBExternalChannelInteraction)
            .where(RDBExternalChannelInteraction.id == graph.interaction.id)
            .with_for_update()
        )
        assert locked is not None
        locked.status = ExternalChannelInteractionStatus.REJECTED
        await writer.write_session.flush()
        # Timeout bounds a hang only; success is authoritative returned state.
        async with asyncio.timeout(5):
            processing = await graph.interactions().load_processing_interaction(
                graph.interaction.id
            )
            scope = await graph.interactions().load_scope(
                graph.interaction.id,
                selector_interaction_id=None,
                now=graph.now,
            )
            catalog = await graph.selectors().project_catalog(
                selector_interaction_id=graph.interaction.id,
                principal_id=graph.principal_id,
                search=None,
                offset=0,
                now=graph.now,
            )
        assert (
            processing.interaction.status is ExternalChannelInteractionStatus.PROCESSING
        )
        assert scope.selector.id == graph.interaction.id
        assert [candidate.agent_name for candidate in catalog.candidates] == [
            "Alpha",
            "Zeta",
        ]
        await writer.write_session.rollback()
    async with graph.read() as read:
        assert (
            await read.read_session.scalar(sa.text("SHOW transaction_read_only"))
            == "on"
        )


async def test_descriptive_read_failure_and_cancellation_close_native_scope(
    graph: _Graph,
) -> None:
    """Missing identity and cancellation unwind the real read-only transaction."""
    active = 0
    entered = asyncio.Event()
    gate = asyncio.Event()

    @asynccontextmanager
    async def gated_read() -> AsyncGenerator[ReadSession, None]:
        nonlocal active
        async with graph.read() as session:
            active += 1
            try:
                await session.read_session.execute(sa.text("SELECT 1"))
                entered.set()
                await gate.wait()
                yield session
            finally:
                active -= 1

    task = asyncio.create_task(
        graph.interactions(gated_read).load_processing_interaction(graph.interaction.id)
    )
    await entered.wait()
    assert active == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == 0
    with pytest.raises(ValueError, match="unavailable"):
        await graph.interactions().load_processing_interaction(uuid4().hex)
    # Same pool can begin a writable transaction after either exit path.
    async with graph.write() as write:
        assert (
            await write.write_session.scalar(sa.text("SHOW transaction_read_only"))
            == "off"
        )


async def test_selector_authorization_rejects_cross_actor_without_mutation(
    graph: _Graph,
) -> None:
    """Read and mutation paths preserve exact selector principal authority."""
    with pytest.raises(ExternalChannelSelectorError, match="unavailable"):
        await graph.selectors().project_catalog(
            selector_interaction_id=graph.interaction.id,
            principal_id=uuid4().hex,
            search=None,
            offset=0,
            now=graph.now,
        )
    with pytest.raises(ExternalChannelSelectorError, match="unavailable"):
        await graph.selectors().select_route(
            selector_interaction_id=graph.interaction.id,
            principal_id=uuid4().hex,
            route_id=graph.route_ids[0],
            now=graph.now,
        )
    snapshot = await graph.interactions().load_processing_interaction(
        graph.interaction.id
    )
    assert (
        selector_state_from_interaction(snapshot.interaction).selected_route_id is None
    )


async def test_concurrent_different_route_selections_have_one_immutable_winner(
    graph: _Graph,
) -> None:
    """Independent native writes serialize on the selector row, not test sleeps."""

    async def choose(route_id: str) -> str:
        try:
            result = await graph.selectors().select_route(
                selector_interaction_id=graph.interaction.id,
                principal_id=graph.principal_id,
                route_id=route_id,
                now=graph.now,
            )
            return result.status
        except ExternalChannelSelectorError as error:
            assert "immutable" in str(error)
            return "immutable"

    results = await asyncio.gather(*(choose(route) for route in graph.route_ids))
    assert sorted(results) == ["immutable", "selected"]
    snapshot = await graph.interactions().load_processing_interaction(
        graph.interaction.id
    )
    winner = selector_state_from_interaction(snapshot.interaction).selected_route_id
    assert winner in graph.route_ids


class _LateProjectionFailure(ExternalChannelRepository):
    """Fail after actual SQL mutation to verify completed operation rollback."""

    async def replace_interaction_projection(
        self,
        session: WriteSession,
        *,
        interaction_id: str,
        projection: dict[str, object],
    ) -> ExternalChannelInteraction | None:
        await super().replace_interaction_projection(
            session,
            interaction_id=interaction_id,
            projection=projection,
        )
        raise RuntimeError("late selector failure")


async def test_late_selector_failure_rolls_back_flushed_selection(
    graph: _Graph,
) -> None:
    """The current projection pointer is unchanged after a post-flush exception."""
    with pytest.raises(RuntimeError, match="late selector"):
        await graph.selectors(_LateProjectionFailure()).select_route(
            selector_interaction_id=graph.interaction.id,
            principal_id=graph.principal_id,
            route_id=graph.route_ids[0],
            now=graph.now,
        )
    snapshot = await graph.interactions().load_processing_interaction(
        graph.interaction.id
    )
    assert (
        selector_state_from_interaction(snapshot.interaction).selected_route_id is None
    )


async def test_parent_settings_generation_cas_is_atomic_under_concurrency(
    graph: _Graph,
) -> None:
    """Exactly one matching generation can write settings from independent callers."""

    async def mutate(mode: ExternalChannelResponseMode) -> str:
        try:
            result = await graph.participation().mutate_parent_settings(
                connection_id=graph.connection.id,
                provider_parent_channel_id="channel",
                principal_id=graph.principal_id,
                expected_setting_id=graph.setting.id,
                expected_settings_generation=1,
                location=ExternalChannelConversationLocation.THREADS,
                response_mode=mode,
                now=graph.now,
            )
            assert result.settings.setting is not None
            assert result.settings.setting.settings_generation == 2
            return "committed"
        except ExternalChannelParticipationError:
            return "stale"

    results = await asyncio.gather(
        mutate(ExternalChannelResponseMode.ALL_MESSAGES),
        mutate(ExternalChannelResponseMode.MENTION_ONLY),
    )
    assert sorted(results) == ["committed", "stale"]
    async with graph.read() as session:
        setting = await graph.repository.get_active_participation_setting(
            session,
            connection_id=graph.connection.id,
            provider_parent_channel_id="channel",
        )
    assert setting is not None and setting.settings_generation == 2


async def test_parent_settings_actor_denial_preserves_generation(graph: _Graph) -> None:
    """Foreign principal cannot write an otherwise-current settings generation."""
    with pytest.raises(ExternalChannelParticipationError, match="unavailable"):
        await graph.participation().mutate_parent_settings(
            connection_id=graph.connection.id,
            provider_parent_channel_id="channel",
            principal_id=uuid4().hex,
            expected_setting_id=graph.setting.id,
            expected_settings_generation=1,
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            now=graph.now,
        )
    async with graph.read() as session:
        setting = await graph.repository.get_active_participation_setting(
            session,
            connection_id=graph.connection.id,
            provider_parent_channel_id="channel",
        )
    assert setting is not None and setting.settings_generation == 1


async def test_shortcut_revalidates_preparation_generation_before_new_rows(
    graph: _Graph,
) -> None:
    """Detached source evidence cannot authorize admission after connection change."""
    operations = ExternalChannelShortcutSourceOperations(
        session_manager=graph.write,
        read_session_manager=graph.read,
        repository=graph.repository,
    )
    snapshot = await operations.read_connection(graph.connection.id)
    assert snapshot is not None
    projection = ShortcutSourceProjection(
        provider_resource_key=f"slack:{graph.connection.provider_tenant_id}:other:200",
        position_scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
        position_provider_channel_id="other",
        position_provider_thread_key=None,
        provider_parent_channel_id="other",
        delivery_thread_key="200",
        trigger_provider_message_id="200",
        labels={"channel_id": "other", "thread_ts": "200"},
        provider_created_at=graph.now,
        provider_message_key="new-source",
        provider_position="200",
    )
    source = ExternalChannelTrigger(
        connection_id=graph.connection.id,
        provider_event_id="source",
        transport_envelope_id=None,
        event_type="app_mention",
        provider_app_id=None,
        provider_tenant_id=graph.connection.provider_tenant_id,
        provider_enterprise_id=None,
        resource_correlation_key="other:200",
        envelope={},
        provider_occurred_at=graph.now,
        received_at=graph.now,
    )
    with pytest.raises(ShortcutSelectionUnavailable, match="changed"):
        await operations.ensure(
            shortcut_source_event=source,
            interaction_id=graph.interaction.id,
            now=graph.now,
            connection_snapshot=snapshot.model_copy(
                update={
                    "configuration_generation": snapshot.configuration_generation - 1
                }
            ),
            projection=projection,
        )
    async with graph.read() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalChannelResource)
                .where(
                    RDBExternalChannelResource.connection_id == graph.connection.id,
                    RDBExternalChannelResource.provider_resource_key
                    == projection.provider_resource_key,
                )
            )
            == 0
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalChannelConversationPosition)
                .where(
                    RDBExternalChannelConversationPosition.connection_id
                    == graph.connection.id,
                    RDBExternalChannelConversationPosition.provider_channel_id
                    == "other",
                )
            )
            == 0
        )
