"""Durable External Channel ingress queue repository tests."""

import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressItemState,
    ExternalChannelIngressProfile,
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
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel_ingress import (
    RDBExternalChannelIngressItem,
    RDBExternalChannelIngressOwner,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelConnectionCreate,
    ExternalChannelConversationPositionCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressItemCreate,
    ExternalChannelIngressOwnerCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

_NOW = datetime.datetime(2026, 8, 10, 1, tzinfo=datetime.UTC)


class _ExpiredUpdatedAtItem(SimpleNamespace):
    """Raise when DTO conversion reads updated_at before an explicit refresh."""

    updated_at_loaded: bool = True

    def __getattribute__(self, name: str) -> object:
        if name == "updated_at" and not super().__getattribute__("updated_at_loaded"):
            raise RuntimeError("updated_at remains expired")
        return super().__getattribute__(name)


def _owner(
    *,
    first_batch_pending: bool,
    lease_owner: str | None = "owner-1",
    lease_generation: int = 1,
    lease_expires_at: datetime.datetime | None = None,
) -> SimpleNamespace:
    """Build one mutable ORM-shaped drain row."""
    return SimpleNamespace(
        id="owner-1",
        connection_id="connection-1",
        target_resource_id="resource-1",
        route_id="route-1",
        participation_setting_id=None,
        participation_settings_generation=None,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        binding_id="binding-1",
        session_id="session-1",
        preparation_attempt_count=0,
        preparation_next_attempt_at=None,
        lease_owner=lease_owner,
        lease_generation=lease_generation,
        lease_acquired_at=_NOW if lease_owner is not None else None,
        lease_expires_at=lease_expires_at
        if lease_expires_at is not None
        else (_NOW + datetime.timedelta(minutes=5) if lease_owner else None),
        first_batch_pending=first_batch_pending,
        current_batch_id=None,
        current_batch_started_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _item(index: int) -> SimpleNamespace:
    """Build one mutable ORM-shaped active queue row."""
    position = f"{index:020d}"
    return SimpleNamespace(
        id=f"item-{index}",
        owner_id="owner-1",
        queue_key=f"{index:032d}",
        deduplication_key=f"{index:064d}",
        provider_event_id=f"event-{index}",
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
        configuration_generation=1,
        authority_kind=ExternalChannelIngressAuthorityKind.CONFIGURATION,
        authority_lease_owner=None,
        authority_lease_generation=None,
        provider_event_type="message",
        provider_tenant_id="tenant-1",
        scope_kind=ExternalChannelConversationScopeKind.THREAD,
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="thread-1",
        delivery_thread_key="thread-1",
        provider_resource_key="resource-1",
        source_resource_id="resource-1",
        conversation_position_id="position-1",
        principal_id="principal-1",
        trigger_provider_message_key=f"message-{index}",
        trigger_provider_message_id=str(index),
        trigger_position=position,
        provider_user_id="user-1",
        invocation=True,
        invocation_id=f"invocation-{index}",
        initial_title_eligible=False,
        state=ExternalChannelIngressItemState.PENDING,
        attempt_count=0,
        next_attempt_at=None,
        processing_owner=None,
        processing_generation=None,
        batch_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _session() -> MagicMock:
    """Build one AsyncSession-shaped mock with transactional methods."""
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock()
    session.scalars = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


async def test_claim_due_batch_uses_one_then_ten_item_limits() -> None:
    """The first execution is single-item and later claims are capped at ten."""
    repository = ExternalChannelIngressQueueRepository()

    first_session = _session()
    first_drain = _owner(first_batch_pending=True)
    first_row = _item(0)
    first_session.scalar.return_value = first_drain
    first_session.scalars.return_value = [first_row]

    first = await repository.claim_due_batch(
        first_session,
        owner_id="owner-1",
        lease_owner="owner-1",
        lease_generation=1,
        now=_NOW,
    )

    assert first is not None
    assert len(first.items) == 1
    assert first_row.state is ExternalChannelIngressItemState.PROCESSING
    assert first_row.attempt_count == 1
    assert first_drain.first_batch_pending is False
    first_statement = first_session.scalars.await_args.args[0]
    assert first_statement._limit_clause.value == 1  # noqa: SLF001

    later_session = _session()
    later_drain = _owner(first_batch_pending=False)
    later_rows = [_item(index) for index in range(10)]
    later_session.scalar.return_value = later_drain
    later_session.scalars.return_value = later_rows

    later = await repository.claim_due_batch(
        later_session,
        owner_id="owner-1",
        lease_owner="owner-1",
        lease_generation=1,
        now=_NOW,
    )

    assert later is not None
    assert len(later.items) == 10
    assert all(
        row.state is ExternalChannelIngressItemState.PROCESSING for row in later_rows
    )
    later_statement = later_session.scalars.await_args.args[0]
    assert later_statement._limit_clause.value == 10  # noqa: SLF001


async def test_claim_due_batch_refreshes_updated_at_before_dto_conversion() -> None:
    """A flush-expired onupdate timestamp is loaded before Pydantic reads it."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    drain = _owner(first_batch_pending=True)
    item = _ExpiredUpdatedAtItem(**vars(_item(0)))
    item.updated_at_loaded = False
    session.scalar.return_value = drain
    session.scalars.return_value = [item]

    async def refresh_updated_at(
        refreshed: _ExpiredUpdatedAtItem,
        *,
        attribute_names: list[str],
    ) -> None:
        assert refreshed is item
        assert attribute_names == ["updated_at"]
        refreshed.updated_at_loaded = True

    session.refresh.side_effect = refresh_updated_at

    claimed = await repository.claim_due_batch(
        session,
        owner_id="owner-1",
        lease_owner="owner-1",
        lease_generation=1,
        now=_NOW,
    )

    assert claimed is not None
    assert claimed.items[0].updated_at == _NOW
    session.refresh.assert_awaited_once_with(item, attribute_names=["updated_at"])


async def test_mark_owner_ready_preserves_creation_invocation_for_auto_title() -> None:
    """Provisioning marks the first invocation only after Session creation commits."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    owner = _owner(first_batch_pending=True)
    owner.binding_id = None
    owner.session_id = None
    first_invocation = _item(1)
    session.scalar.return_value = first_invocation

    await repository.mark_owner_ready(
        session,
        owner=cast(RDBExternalChannelIngressOwner, owner),
        binding_id="binding-created",
        session_id="session-created",
        initial_title_eligible=True,
    )

    assert owner.binding_id == "binding-created"
    assert owner.session_id == "session-created"
    assert owner.preparation_next_attempt_at is None
    assert first_invocation.initial_title_eligible is True
    session.scalar.assert_awaited_once()
    session.flush.assert_awaited_once()


async def test_expired_lease_is_reclaimed_and_current_lease_is_released() -> None:
    """A stale owner is fenced by generation and explicit release clears ownership."""
    repository = ExternalChannelIngressQueueRepository()
    claim_session = _session()
    drain = _owner(
        first_batch_pending=False,
        lease_owner="stale-owner",
        lease_generation=4,
        lease_expires_at=_NOW - datetime.timedelta(seconds=1),
    )
    claim_session.scalar.return_value = drain

    claim = await repository.claim_lease(
        claim_session,
        owner_id="owner-1",
        lease_owner="owner-2",
        now=_NOW,
        lease_expires_at=_NOW + datetime.timedelta(minutes=5),
    )

    assert claim is not None
    assert claim.owner.lease_owner == "owner-2"
    assert claim.owner.lease_generation == 5
    assert drain.current_batch_id is None
    reset_statement = claim_session.execute.await_args.args[0]
    reset_sql = str(
        reset_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "state='processing'" in reset_sql.replace(" ", "")

    release_session = _session()
    release_result = MagicMock()
    release_result.scalar_one_or_none.return_value = "session-1"
    release_session.execute.return_value = release_result

    released = await repository.release_lease(
        release_session,
        owner_id="owner-1",
        lease_owner="owner-2",
        lease_generation=5,
    )

    assert released is True
    release_sql = str(
        release_session.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "lease_owner=NULL" in release_sql.replace(" ", "")
    assert "lease_generation = 5" in release_sql


async def test_retry_moves_same_item_and_original_age_to_queue_tail() -> None:
    """Retry preserves durable identity/age while assigning a fresh tail key."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    item = _item(1)
    item.queue_key = "0" * 32
    item.state = ExternalChannelIngressItemState.PROCESSING
    item.attempt_count = 2
    item.processing_owner = "owner-1"
    item.processing_generation = 1
    item.batch_id = "batch-1"
    item_id = item.id
    created_at = item.created_at
    next_attempt_at = _NOW + datetime.timedelta(seconds=30)

    await repository.move_to_retry_tail(
        session,
        item=cast(RDBExternalChannelIngressItem, item),
        next_attempt_at=next_attempt_at,
    )

    assert item.id == item_id
    assert item.created_at == created_at
    assert item.queue_key != "0" * 32
    assert item.state is ExternalChannelIngressItemState.RETRY_WAITING
    assert item.attempt_count == 2
    assert item.next_attempt_at == next_attempt_at
    assert item.processing_owner is None
    assert item.processing_generation is None
    assert item.batch_id is None
    session.flush.assert_awaited_once()


async def test_recovery_query_includes_unowned_processing_rows() -> None:
    """Crash recovery can reclaim processing work after lease ownership is cleared."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    session.scalars.return_value = [_owner(first_batch_pending=False, lease_owner=None)]

    recovered = await repository.list_recoverable_owners(
        session,
        now=_NOW,
        limit=100,
    )

    assert [owner.id for owner in recovered] == ["owner-1"]
    assert recovered[0].created_at == _NOW
    statement = session.scalars.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "'processing'" in sql
    assert "external_channel_ingress_owners.lease_owner IS NULL" in sql
    assert "external_channel_ingress_owners.session_id IS NOT NULL" in sql


def test_ready_owner_is_not_reused_for_an_unready_target() -> None:
    """A disconnected Binding cannot keep accepting items through its old owner."""
    repository = ExternalChannelIngressQueueRepository()
    owner = _owner(first_batch_pending=True)

    compatible = repository._reconcile_owner(  # noqa: SLF001
        cast(RDBExternalChannelIngressOwner, owner),
        expected=ExternalChannelIngressOwnerCreate(
            connection_id="connection-1",
            target_resource_id="resource-1",
            route_id="route-1",
            participation_setting_id="setting-1",
            participation_settings_generation=2,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            binding_id=None,
            session_id=None,
        ),
    )

    assert compatible is False


def test_unready_owner_adopts_a_compatible_ready_binding() -> None:
    """Synchronous replay readiness preserves every retained owner item."""
    repository = ExternalChannelIngressQueueRepository()
    owner = _owner(first_batch_pending=True)
    owner.binding_id = None
    owner.session_id = None
    owner.participation_setting_id = "setting-old"
    owner.participation_settings_generation = 1

    compatible = repository._reconcile_owner(  # noqa: SLF001
        cast(RDBExternalChannelIngressOwner, owner),
        expected=ExternalChannelIngressOwnerCreate(
            connection_id="connection-1",
            target_resource_id="resource-1",
            route_id="route-1",
            participation_setting_id=None,
            participation_settings_generation=None,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            binding_id="binding-2",
            session_id="session-2",
        ),
    )

    assert compatible is True
    assert owner.binding_id == "binding-2"
    assert owner.session_id == "session-2"
    assert owner.response_mode is ExternalChannelResponseMode.MENTION_ONLY
    assert owner.participation_setting_id is None
    assert owner.participation_settings_generation is None


async def test_active_diagnostics_are_bounded_and_content_free() -> None:
    """Inspection exposes active ownership and timing without provider content."""
    repository = ExternalChannelIngressQueueRepository()
    session = _session()
    item = _item(1)
    item.state = ExternalChannelIngressItemState.RETRY_WAITING
    item.attempt_count = 2
    item.next_attempt_at = _NOW + datetime.timedelta(seconds=30)
    drain = _owner(first_batch_pending=False)
    drain.current_batch_id = "batch-1"
    drain.current_batch_started_at = _NOW - datetime.timedelta(seconds=2)

    summary_result = MagicMock()
    summary_result.one.return_value = (
        1,
        0,
        0,
        1,
        _NOW - datetime.timedelta(seconds=10),
        1,
    )
    rows_result = MagicMock()
    rows_result.tuples.return_value = [(item, drain)]
    session.execute.side_effect = [summary_result, rows_result]

    snapshot = await repository.inspect_active(
        session,
        now=_NOW,
        limit=10,
    )

    assert snapshot.owner_count == 1
    assert snapshot.counts.pending == 0
    assert snapshot.counts.processing == 0
    assert snapshot.counts.retry_waiting == 1
    assert snapshot.counts.total == 1
    assert snapshot.oldest_queue_age_seconds == 10
    assert snapshot.truncated is False
    assert snapshot.items[0].connection_id == "connection-1"
    assert snapshot.items[0].attempt_count == 2
    assert snapshot.items[0].next_attempt_at == item.next_attempt_at
    assert snapshot.items[0].lease_owner == "owner-1"
    serialized = snapshot.model_dump_json()
    for forbidden in (
        "deduplication_key",
        "provider_event_id",
        "trigger_provider_message_key",
        "provider_user_id",
        "principal_id",
    ):
        assert forbidden not in serialized


async def test_postgres_pre_session_callbacks_share_one_owner(
    rdb_session: AsyncSession,
) -> None:
    """Two durable callbacks converge without requiring a Binding or Session."""
    workspace_result = await WorkspaceRepository().create(
        rdb_session,
        WorkspaceCreate(
            name="Ingress owner convergence",
            handle="ingress-owner-convergence",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(
        rdb_session,
        "ingress-owner-convergence",
    )
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="ingress-owner-integration",
        encrypted_credentials="encrypted",
        config=None,
    )
    rdb_session.add(integration)
    await rdb_session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="ingress-owner-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Ingress owner Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    rdb_session.add(agent)
    await rdb_session.flush()
    external_repository = ExternalChannelRepository()
    connection = await external_repository.create_connection(
        rdb_session,
        ExternalChannelConnectionCreate(
            workspace_id=workspace_id,
            provider=ExternalChannelProvider.SLACK,
            transport=ExternalChannelTransport.HTTP,
            app_mode=ExternalChannelAppMode.SINGLE,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_app_id="ingress-owner-app",
            provider_tenant_id="ingress-owner-tenant",
            provider_bot_user_id=None,
            http_callback_selector_hash=None,
            encrypted_credentials="ciphertext",
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
        ),
    )
    route = await external_repository.create_agent_route(
        rdb_session,
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
    resource = await external_repository.create_resource_idempotent(
        rdb_session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key="ingress-owner-thread",
            labels={"provider": "slack", "channel_id": "C1", "thread_ts": "1.0"},
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_NOW,
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    position = await external_repository.create_conversation_position_idempotent(
        rdb_session,
        ExternalChannelConversationPositionCreate(
            connection_id=connection.id,
            scope_kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id="C1",
            provider_thread_key="1.0",
            read_through_position=None,
        ),
    )
    principal = await external_repository.create_principal_idempotent(
        rdb_session,
        ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="ingress-owner-tenant",
            provider_user_id="U1",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        ),
    )
    owner_create = ExternalChannelIngressOwnerCreate(
        connection_id=connection.id,
        target_resource_id=resource.id,
        route_id=route.id,
        participation_setting_id=None,
        participation_settings_generation=None,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        binding_id=None,
        session_id=None,
    )

    def item_create(
        index: int,
        *,
        invocation: bool = True,
    ) -> ExternalChannelIngressItemCreate:
        return ExternalChannelIngressItemCreate(
            deduplication_key=f"{index:064d}",
            provider_event_id=f"event-{index}",
            connection_id=connection.id,
            provider=ExternalChannelProvider.SLACK,
            ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
            configuration_generation=connection.configuration_generation,
            authority_kind=ExternalChannelIngressAuthorityKind.CONFIGURATION,
            authority_lease_owner=None,
            authority_lease_generation=None,
            provider_event_type="message",
            provider_tenant_id="ingress-owner-tenant",
            scope_kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id="C1",
            provider_parent_channel_id=None,
            provider_thread_key="1.0",
            delivery_thread_key="1.0",
            provider_resource_key="ingress-owner-thread",
            source_resource_id=resource.id,
            conversation_position_id=position.id,
            principal_id=principal.id,
            trigger_provider_message_key=f"message-{index}",
            trigger_provider_message_id=f"{index}.0",
            trigger_position=f"{index:020d}",
            provider_user_id="U1",
            invocation=invocation,
            invocation_id=f"invocation-{index}",
            initial_title_eligible=False,
        )

    repository = ExternalChannelIngressQueueRepository()
    first = await repository.admit(
        rdb_session,
        owner_create=owner_create,
        item_create=item_create(1),
    )
    second = await repository.admit(
        rdb_session,
        owner_create=owner_create,
        item_create=item_create(2, invocation=False),
    )

    assert first.owner.id == second.owner.id
    assert first.owner.ready is False
    assert first.created is True
    assert second.created is True
    assert (
        await rdb_session.scalar(
            sa.select(sa.func.count()).select_from(RDBExternalChannelIngressOwner)
        )
        == 1
    )
    assert (
        await rdb_session.scalar(
            sa.select(sa.func.count()).select_from(RDBExternalChannelIngressItem)
        )
        == 2
    )
    correlations = await repository.list_active_correlations(
        rdb_session,
        connection_id=connection.id,
        conversation_position_id=position.id,
    )
    assert set(correlations) == {"message-1", "message-2"}
    assert correlations["message-1"].invocation_id == "invocation-1"
    assert correlations["message-2"].invocation_id == "invocation-2"
    assert correlations["message-2"].principal_id == principal.id
    owner_row = await rdb_session.get(
        RDBExternalChannelIngressOwner,
        first.owner.id,
        with_for_update=True,
    )
    assert owner_row is not None
    owner_row.preparation_next_attempt_at = _NOW + datetime.timedelta(seconds=30)
    await rdb_session.flush()
    assert (
        await repository.claim_lease(
            rdb_session,
            owner_id=first.owner.id,
            lease_owner="worker-1",
            now=_NOW,
            lease_expires_at=_NOW + datetime.timedelta(minutes=1),
        )
        is None
    )
