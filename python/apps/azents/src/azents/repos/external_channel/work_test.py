"""Focused current-projection tests for direct External Channel Work."""

import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.result import Success
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from azents.rdb.models.external_channel import (
    RDBExternalChannelConnection,
    RDBExternalChannelWork,
    RDBExternalChannelWorkProjectionPart,
)
from azents.repos.external_channel.data import ExternalChannelConnectionCreate
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import (
    ExternalChannelWorkRepository,
    projection_state,
)
from azents.repos.external_channel.work_data import ChannelActionEffectPlan
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.external_channel import make_provider_effect_plan


def _work(*, desired: bool) -> RDBExternalChannelWork:
    return RDBExternalChannelWork(
        binding_id="binding-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        schema_version=2,
        title="Working…" if desired else None,
        tasks=[],
        state_revision=2,
        desired_progress_revision=3,
        desired_progress_payload={"state": "working"} if desired else None,
        finished_at=None,
    )


def _part(
    *,
    status: ExternalChannelWorkProjectionStatus,
    provider_message_key: str | None,
    revision: int = 3,
) -> RDBExternalChannelWorkProjectionPart:
    return RDBExternalChannelWorkProjectionPart(
        work_id="work-1",
        part_ordinal=0,
        desired_progress_revision=revision,
        status=status,
        provider_message_key=provider_message_key,
    )


def test_projection_state_is_missing_without_owned_parts() -> None:
    assert projection_state(_work(desired=True), []) == "missing"


def test_projection_state_is_synchronized_for_current_present_part() -> None:
    assert (
        projection_state(
            _work(desired=True),
            [
                _part(
                    status=ExternalChannelWorkProjectionStatus.PRESENT,
                    provider_message_key="provider-key",
                )
            ],
        )
        == "synchronized"
    )


def test_projection_state_preserves_unknown_without_retry_authority() -> None:
    assert (
        projection_state(
            _work(desired=True),
            [
                _part(
                    status=ExternalChannelWorkProjectionStatus.UNKNOWN,
                    provider_message_key=None,
                )
            ],
        )
        == "unknown"
    )


def test_projection_state_reports_failed_terminal_delete() -> None:
    finished = _work(desired=False)
    finished.status = ExternalChannelWorkStatus.FINISHED
    assert (
        projection_state(
            finished,
            [
                _part(
                    status=ExternalChannelWorkProjectionStatus.FAILED,
                    provider_message_key="provider-key",
                )
            ],
        )
        == "delete_failed"
    )


def test_projection_state_accepts_orm_sequence_contract() -> None:
    parts = [
        _part(
            status=ExternalChannelWorkProjectionStatus.DELETED,
            provider_message_key=None,
        )
    ]
    assert projection_state(_work(desired=False), parts) == "none"


def _where_sql(statement: object) -> str:
    compiled = str(
        statement.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    )
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
    connection_query = session.scalar.await_args.args[0]
    where_sql = _where_sql(connection_query)
    assert "external_channel_connections.status" not in where_sql
    assert "external_channel_connections.disconnected_at IS NULL" in where_sql


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
            work_id="work-1",
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

    revalidation_query = session.execute.await_args.args[0]
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
