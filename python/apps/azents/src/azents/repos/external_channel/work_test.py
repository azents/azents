"""Focused current-projection tests for direct External Channel Work."""

import datetime
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.result import Success
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
    ExternalChannelTransport,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)
from azents.core.external_channel_progress import checking_progress
from azents.core.external_channel_title import DISCORD_INITIAL_THREAD_TITLE_LABEL
from azents.rdb.models.external_channel import RDBExternalChannelConnection
from azents.repos.external_channel.data import ExternalChannelConnectionCreate
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import (
    ExternalChannelWorkRepository,
    projection_state,
)
from azents.repos.external_channel.work_data import (
    ChannelActionEffectPlan,
    ChannelActionTransition,
    ChannelWorkTask,
)
from azents.repos.external_channel.work_state import (
    ChannelWorkProjectionPartState,
    ChannelWorkState,
    ChannelWorkStateMutation,
    ExternalChannelWorkStateStore,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.external_channel import make_provider_effect_plan


def _work(
    *,
    desired: bool,
    projection_parts: list[ChannelWorkProjectionPartState] | None = None,
) -> ChannelWorkState:
    return ChannelWorkState(
        binding_id="binding-1",
        work_cycle_id="work-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        title="Working…" if desired else None,
        tasks=[],
        state_revision=2,
        desired_progress_revision=3,
        desired_progress=checking_progress() if desired else None,
        finished_at=None,
        projection_parts=projection_parts or [],
    )


def _part(
    *,
    status: ExternalChannelWorkProjectionStatus,
    provider_message_key: str | None,
    revision: int = 3,
) -> ChannelWorkProjectionPartState:
    return ChannelWorkProjectionPartState(
        part_ordinal=0,
        desired_progress_revision=revision,
        status=status,
        provider_message_key=provider_message_key,
    )


def test_projection_state_is_missing_without_owned_parts() -> None:
    assert projection_state(_work(desired=True)) == "missing"


def test_projection_state_is_synchronized_for_current_present_part() -> None:
    assert (
        projection_state(
            _work(
                desired=True,
                projection_parts=[
                    _part(
                        status=ExternalChannelWorkProjectionStatus.PRESENT,
                        provider_message_key="provider-key",
                    )
                ],
            ),
        )
        == "synchronized"
    )


def test_projection_state_preserves_unknown_without_retry_authority() -> None:
    assert (
        projection_state(
            _work(
                desired=True,
                projection_parts=[
                    _part(
                        status=ExternalChannelWorkProjectionStatus.UNKNOWN,
                        provider_message_key=None,
                    )
                ],
            ),
        )
        == "unknown"
    )


def test_projection_state_reports_failed_terminal_delete() -> None:
    finished = _work(
        desired=False,
        projection_parts=[
            _part(
                status=ExternalChannelWorkProjectionStatus.FAILED,
                provider_message_key="provider-key",
            )
        ],
    )
    finished.status = ExternalChannelWorkStatus.FINISHED
    finished.finished_at = datetime.datetime(2026, 8, 3, tzinfo=datetime.UTC)
    assert projection_state(finished) == "delete_failed"


def test_projection_state_accepts_typed_projection_parts() -> None:
    assert (
        projection_state(
            _work(
                desired=False,
                projection_parts=[
                    _part(
                        status=ExternalChannelWorkProjectionStatus.DELETED,
                        provider_message_key=None,
                    )
                ],
            )
        )
        == "none"
    )


def _where_sql(statement: ClauseElement) -> str:
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    return compiled.partition("WHERE")[2]


async def test_direct_control_ignores_connection_health_status() -> None:
    """Provider controls use terminal lifecycle rather than Connection health."""
    connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        app_mode=ExternalChannelAppMode.SINGLE,
        encrypted_credentials="ciphertext-only",
        provider_tenant_id="tenant-1",
        capabilities={},
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=connection)
    repository = ExternalChannelWorkRepository()

    plan = await repository.prepare_direct_control(
        cast(AsyncSession, session),
        connection_id=connection.id,
        resource_id=None,
        route_id=None,
        binding_id=None,
        operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
        request_payload={"control_kind": "session_presence"},
        operation_seed="control-1",
    )

    assert plan is not None
    scalar_args = session.scalar.await_args
    assert scalar_args is not None
    connection_query = scalar_args.args[0]
    where_sql = _where_sql(connection_query)
    assert "external_channel_connections.status" not in where_sql
    assert "external_channel_connections.disconnected_at IS NULL" in where_sql


@pytest.mark.parametrize(
    "existing_status",
    list(ExternalChannelWorkProjectionStatus),
)
async def test_initial_progress_is_claimed_once_per_active_work(
    existing_status: ExternalChannelWorkProjectionStatus,
) -> None:
    """Repeated admissions cannot create another Tracker for the same active Work."""
    work = ChannelWorkState(
        binding_id="binding-1",
        work_cycle_id="work-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        title=None,
        tasks=[],
        state_revision=1,
        desired_progress_revision=1,
        desired_progress=checking_progress(),
        finished_at=None,
        projection_parts=[],
    )
    binding = SimpleNamespace(id="binding-1")
    resource = SimpleNamespace(
        id="resource-1",
        labels={
            "provider": "slack",
            "tenant_id": "tenant-1",
            "channel_id": "channel-1",
            "thread_ts": "1.000001",
        },
    )
    route = SimpleNamespace(id="route-1")
    connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.SLACK,
    )
    result = MagicMock()
    result.one_or_none.return_value = (
        binding,
        resource,
        route,
        connection,
    )
    current_work = work
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)

    async def load_state(*args: object, **kwargs: object) -> ChannelWorkState:
        del args, kwargs
        return current_work

    async def update_existing(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        mutator: Callable[
            [ChannelWorkState],
            ChannelWorkStateMutation[bool],
        ],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[bool]:
        nonlocal current_work
        del _session, agent_id, session_id, binding_id, max_retries
        mutation = mutator(current_work)
        current_work = mutation.state
        return mutation

    state_store.load = AsyncMock(side_effect=load_state)
    state_store.update_existing = AsyncMock(side_effect=update_existing)
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=result)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)
    plan = make_provider_effect_plan("initial-progress")
    repository.prepare_direct_control = AsyncMock(return_value=plan)

    first = await repository.prepare_initial_progress(
        cast(AsyncSession, session),
        agent_id="agent-1",
        session_id="session-1",
        binding_id=binding.id,
        work_cycle_id=work.work_cycle_id,
    )
    assert first == plan
    assert len(current_work.projection_parts) == 1
    claimed = current_work.projection_parts[0]
    assert claimed.part_ordinal == 0
    assert claimed.desired_progress_revision == work.desired_progress_revision
    assert claimed.status is ExternalChannelWorkProjectionStatus.UNKNOWN
    assert claimed.provider_message_key is None

    claimed.status = existing_status
    claimed.provider_message_key = (
        "provider-key"
        if existing_status is ExternalChannelWorkProjectionStatus.PRESENT
        else None
    )
    repeated = await repository.prepare_initial_progress(
        cast(AsyncSession, session),
        agent_id="agent-1",
        session_id="session-1",
        binding_id=binding.id,
        work_cycle_id=work.work_cycle_id,
    )

    assert repeated is None
    repository.prepare_direct_control.assert_awaited_once()


async def test_direct_control_rejects_terminal_connection_before_credential_purge(
    rdb_session: AsyncSession,
) -> None:
    """A terminal disconnect fences unbound controls before credential purge."""
    workspace_repository = WorkspaceRepository()
    created_workspace = await workspace_repository.create(
        rdb_session,
        WorkspaceCreate(
            name="Outbound terminal control test",
            handle="outbound-terminal-control-test",
        ),
    )
    assert isinstance(created_workspace, Success)
    workspace_id = await workspace_repository.resolve_id(
        rdb_session,
        "outbound-terminal-control-test",
    )
    assert workspace_id is not None
    connection = await ExternalChannelRepository().create_connection(
        rdb_session,
        ExternalChannelConnectionCreate(
            workspace_id=workspace_id,
            provider=ExternalChannelProvider.DISCORD,
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
        ),
    )
    connection_row = await rdb_session.get(
        RDBExternalChannelConnection,
        connection.id,
    )
    assert connection_row is not None
    connection_row.status = ExternalChannelConnectionStatus.DISCONNECTED
    connection_row.disconnected_at = datetime.datetime(
        2026,
        8,
        3,
        tzinfo=datetime.UTC,
    )
    await rdb_session.flush()

    plan = await ExternalChannelWorkRepository().prepare_direct_control(
        rdb_session,
        connection_id=connection.id,
        resource_id=None,
        route_id=None,
        binding_id=None,
        operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
        request_payload={"control_kind": "setup_required"},
        operation_seed="terminal-control",
    )

    assert plan is None
    assert connection_row.encrypted_credentials == "ciphertext-only"


async def test_channel_action_ignores_connection_health_status() -> None:
    """Channel Action validates Connection identity without an ingress-health gate."""

    class ResourceLookupReached(Exception):
        pass

    binding = SimpleNamespace(
        id="binding-1",
        route_id="route-1",
        resource_id="resource-1",
    )
    route = SimpleNamespace(id="route-1", connection_id="connection-1")
    connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(
        side_effect=[
            SimpleNamespace(id="session-1"),
            SimpleNamespace(id="agent-1"),
            binding,
            route,
            connection,
            ResourceLookupReached(),
        ]
    )
    repository = ExternalChannelWorkRepository()

    with pytest.raises(ResourceLookupReached):
        await repository.commit_direct_action(
            cast(AsyncSession, session),
            session_id="session-1",
            agent_id="agent-1",
            run_id="run-1",
            client_tool_call_id="tool-call-1",
            binding_id=binding.id,
            mode=ExternalChannelActionMode.CONTINUE,
            message=None,
            title=None,
            tasks=None,
            files=(),
            now=datetime.datetime(2026, 8, 3, tzinfo=datetime.UTC),
        )

    connection_query = session.scalar.await_args_list[4].args[0]
    assert "external_channel_connections.status" not in _where_sql(connection_query)


async def _commit_ignore(
    work: ChannelWorkState,
) -> tuple[ChannelActionTransition, ChannelWorkState, AsyncMock]:
    """Execute the canonical ignore mutator through repository authority checks."""
    binding = SimpleNamespace(
        id="binding-1",
        route_id="route-1",
        resource_id="resource-1",
    )
    route = SimpleNamespace(id="route-1", connection_id="connection-1")
    connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.SLACK,
    )
    agent = SimpleNamespace(
        id="agent-1",
        workspace_id="workspace-1",
        name="Agent",
        avatar=None,
    )
    resource = SimpleNamespace(id="resource-1", labels={})
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(
        side_effect=[
            SimpleNamespace(id="session-1"),
            agent,
            binding,
            route,
            connection,
            resource,
        ]
    )
    session.get = AsyncMock(return_value=SimpleNamespace(handle="workspace"))
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)
    current = work

    async def update(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        default_factory: Callable[[], ChannelWorkState],
        mutator: Callable[
            [ChannelWorkState],
            ChannelWorkStateMutation[object],
        ],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[object]:
        nonlocal current
        del (
            _session,
            agent_id,
            session_id,
            binding_id,
            default_factory,
            max_retries,
        )
        mutation = mutator(current)
        current = mutation.state
        return mutation

    state_store.update = AsyncMock(side_effect=update)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)
    transition = await repository.commit_direct_action(
        cast(AsyncSession, session),
        session_id="session-1",
        agent_id="agent-1",
        run_id="run-1",
        client_tool_call_id="tool-call-ignore",
        binding_id=binding.id,
        mode=ExternalChannelActionMode.IGNORE,
        message=None,
        title=None,
        tasks=None,
        files=(),
        now=datetime.datetime(2026, 8, 3, tzinfo=datetime.UTC),
    )
    return transition, current, state_store.update


@pytest.mark.parametrize(
    "statuses",
    [
        (),
        (ExternalChannelWorkTaskStatus.PENDING,),
        (ExternalChannelWorkTaskStatus.IN_PROGRESS,),
        (ExternalChannelWorkTaskStatus.COMPLETED,),
        (
            ExternalChannelWorkTaskStatus.COMPLETED,
            ExternalChannelWorkTaskStatus.FAILED,
        ),
    ],
)
async def test_ignore_finishes_active_work_without_provider_effects(
    statuses: tuple[ExternalChannelWorkTaskStatus, ...],
) -> None:
    """Ignore finishes Work regardless of current task status."""
    projection = _part(
        status=ExternalChannelWorkProjectionStatus.PRESENT,
        provider_message_key="provider-key",
    )
    work = _work(desired=True, projection_parts=[projection])
    work.tasks = [
        ChannelWorkTask(
            id=f"task-{index}",
            title=f"Task {index}",
            status=status,
            details=None,
            output=None,
            sources=[],
        )
        for index, status in enumerate(statuses)
    ]

    transition, updated, update = await _commit_ignore(work)

    assert transition.work_status is ExternalChannelWorkStatus.FINISHED
    assert transition.effects == ()
    assert updated.status is ExternalChannelWorkStatus.FINISHED
    assert updated.state_revision == work.state_revision + 1
    assert updated.desired_progress_revision == work.desired_progress_revision + 1
    assert updated.desired_progress is None
    assert updated.finished_at == datetime.datetime(
        2026,
        8,
        3,
        tzinfo=datetime.UTC,
    )
    assert updated.projection_parts == [projection]
    update.assert_awaited_once()


async def test_direct_effect_revalidation_ignores_connection_health_status() -> None:
    """Post-commit effect authority is independent from ingress health."""

    class QueryCaptured(Exception):
        pass

    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=QueryCaptured())
    repository = ExternalChannelWorkRepository()
    effect = cast(
        ChannelActionEffectPlan,
        SimpleNamespace(
            work_cycle_id="work-1",
            provider=SimpleNamespace(
                target=SimpleNamespace(
                    binding_id="binding-1",
                    resource_id="resource-1",
                    connection_id="connection-1",
                )
            ),
        ),
    )

    with pytest.raises(QueryCaptured):
        await repository.revalidate_direct_effect(
            cast(AsyncSession, session),
            effect=effect,
        )

    execute_args = session.execute.await_args
    assert execute_args is not None
    revalidation_query = execute_args.args[0]
    assert "external_channel_connections.status" not in _where_sql(revalidation_query)


async def test_access_control_create_is_claimed_once_before_provider_io() -> None:
    """A repeated access callback cannot create a second provider control."""
    request = SimpleNamespace(
        status=ExternalChannelAccessRequestStatus.PENDING,
        control_provider_message_key=None,
        control_projection_status=None,
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=request)
    session.flush = AsyncMock()
    repository = ExternalChannelWorkRepository()
    plan = make_provider_effect_plan("access-control")
    repository.prepare_direct_control = AsyncMock(return_value=plan)

    first = await repository.prepare_access_control_create(
        cast(AsyncSession, session),
        access_request_id="access-request-1",
        connection_id="connection-1",
        resource_id="resource-1",
        route_id="route-1",
        binding_id=None,
        request_payload={"access_request_id": "access-request-1"},
        operation_seed="access-request:access-request-1",
    )
    second = await repository.prepare_access_control_create(
        cast(AsyncSession, session),
        access_request_id="access-request-1",
        connection_id="connection-1",
        resource_id="resource-1",
        route_id="route-1",
        binding_id=None,
        request_payload={"access_request_id": "access-request-1"},
        operation_seed="access-request:access-request-1",
    )

    assert first == plan
    assert second is None
    assert (
        request.control_projection_status is ExternalChannelWorkProjectionStatus.UNKNOWN
    )
    session.flush.assert_awaited_once()
    repository.prepare_direct_control.assert_awaited_once()


async def test_discord_delivery_channel_records_direct_create_title_once() -> None:
    """Direct-create evidence is retained once and never manufactured later."""
    resource = SimpleNamespace(
        labels={"provider": "discord", "guild_id": "111"},
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=resource)
    session.flush = AsyncMock()
    repository = ExternalChannelWorkRepository()

    first = await repository.record_discord_delivery_channel(
        cast(AsyncSession, session),
        resource_id="resource-1",
        delivery_channel_id="444",
        initial_thread_title="Test agent",
    )
    second = await repository.record_discord_delivery_channel(
        cast(AsyncSession, session),
        resource_id="resource-1",
        delivery_channel_id="555",
        initial_thread_title="Another title",
    )

    assert first == "444"
    assert second == "444"
    assert resource.labels["delivery_channel_id"] == "444"
    assert resource.labels[DISCORD_INITIAL_THREAD_TITLE_LABEL] == "Test agent"
    session.flush.assert_awaited_once()
