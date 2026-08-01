"""Channel Work atomic transition and recovery tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
    LLMProvider,
)
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelResource,
    RDBExternalChannelWork,
    RDBExternalChannelWorkProjectionPart,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelBindingCreate,
    ExternalChannelConnectionCreate,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ChannelWorkTask
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.testing.model_selection import make_test_model_selection_dict


def _at(second: int) -> datetime.datetime:
    return datetime.datetime(2026, 7, 22, 0, 0, second, tzinfo=datetime.UTC)


def _task(
    *,
    id: str,
    title: str,
    status: ExternalChannelWorkTaskStatus,
) -> ChannelWorkTask:
    return ChannelWorkTask(
        id=id,
        title=title,
        status=status,
        details=None,
        output=None,
        sources=[],
    )


async def _seed_activity_tracker(
    session: AsyncSession,
    *,
    binding_id: str,
) -> RDBExternalChannelWork:
    work = await session.scalar(
        sa.select(RDBExternalChannelWork).where(
            RDBExternalChannelWork.binding_id == binding_id,
            RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
        )
    )
    assert work is not None
    work.desired_progress_revision = 1
    work.desired_progress_payload = {
        "schema_version": 2,
        "state": "checking",
        "title": None,
        "tasks": [],
    }
    work.progress_provider_message_key = "slack:T1:C1:2.000001"
    await session.flush()
    return work


async def _setup_binding(session: AsyncSession) -> tuple[str, str]:
    workspace_result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Channel Work test", handle="channel-work-test"),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, "channel-work-test")
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="channel-work-integration",
        encrypted_credentials="encrypted",
        config=None,
    )
    session.add(integration)
    await session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="channel-work-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Channel Work Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    session.add(agent)
    await session.flush()
    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    repository = ExternalChannelRepository()
    connection = await repository.create_connection(
        session,
        ExternalChannelConnectionCreate(
            workspace_id=workspace_id,
            provider=ExternalChannelProvider.SLACK,
            transport=ExternalChannelTransport.HTTP,
            app_mode=ExternalChannelAppMode.SINGLE,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_app_id="A1",
            provider_tenant_id="T1",
            provider_bot_user_id="B1",
            http_callback_selector_hash="channel-work-selector",
            encrypted_credentials="ciphertext",
            capabilities=None,
            provider_config=None,
            last_verified_at=_at(0),
            last_health_at=_at(0),
            disconnected_at=None,
            socket_lease_owner=None,
            socket_lease_until=None,
            socket_heartbeat_at=None,
            socket_gap_detected_at=None,
            socket_gap_reason=None,
        ),
    )
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
    resource = await repository.create_resource_idempotent(
        session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key="slack:T1:C1:1.000001",
            labels={
                "channel_id": "C1",
                "thread_ts": "1.000001",
                "channel_name": "incident",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_at(1),
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    binding = await repository.create_binding_idempotent(
        session,
        ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=route.id,
            agent_session_id=agent_session.id,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    await session.flush()
    return agent.id, binding.id


async def _as_discord_binding(
    session: AsyncSession,
    *,
    binding_id: str,
) -> None:
    """Turn the generic test binding into one active Discord thread binding."""
    binding = await session.get(RDBExternalChannelBinding, binding_id)
    assert binding is not None
    resource = await session.get(RDBExternalChannelResource, binding.resource_id)
    connection = await session.scalar(
        sa.select(RDBExternalChannelConnection)
        .join(
            RDBExternalChannelAgentRoute,
            RDBExternalChannelAgentRoute.connection_id
            == RDBExternalChannelConnection.id,
        )
        .where(RDBExternalChannelAgentRoute.id == binding.route_id)
    )
    assert resource is not None
    assert connection is not None
    connection.provider = ExternalChannelProvider.DISCORD
    connection.provider_tenant_id = "111"
    resource.labels = {
        "guild_id": "111",
        "thread_id": "333",
        "channel_name": "incident",
    }
    await session.flush()


async def test_channel_action_commits_work_and_delivery_intents_idempotently(
    rdb_session: AsyncSession,
) -> None:
    """One durable call mutates work once and creates explicit provider intents."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    assert agent_session is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    await _seed_activity_tracker(rdb_session, binding_id=binding_id)
    tasks = [
        _task(
            id="investigate",
            title="Investigate the incident",
            status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
        )
    ]
    files = (
        ExternalChannelOutboundFileManifest(
            path="/workspace/agent/report.csv",
            filename="report.csv",
            media_type="text/csv",
            expected_size=42,
        ),
    )

    first = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-1",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message="I am investigating.",
        title="Investigating the incident…",
        tasks=tasks,
        files=files,
        now=_at(2),
    )
    duplicate = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-1",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message="I am investigating.",
        title="Investigating the incident…",
        tasks=tasks,
        files=files,
        now=_at(3),
    )

    assert duplicate.action_id == first.action_id
    assert duplicate.state_revision == first.state_revision == 2
    assert [item.operation for item in first.deliveries] == [
        ExternalChannelDeliveryOperation.REPLY,
        ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
    ]
    assert all(
        item.status is ExternalChannelDeliveryStatus.PENDING
        for item in first.deliveries
    )
    action = await rdb_session.get(RDBExternalChannelAction, first.action_id)
    reply = await rdb_session.get(
        RDBExternalChannelDeliveryAttempt,
        first.deliveries[0].id,
    )
    expected_manifest = [files[0].model_dump(mode="json")]
    assert action is not None
    assert reply is not None
    assert action.request_payload["files"] == expected_manifest
    assert reply.request_payload["files"] == expected_manifest
    assert "content" not in str(action.request_payload).lower()
    assert "upload_url" not in str(reply.request_payload).lower()
    existing = await repository.find_action_by_client_tool_call(
        rdb_session,
        session_id=agent_session.id,
        client_tool_call_id="call-1",
    )
    assert existing is not None
    assert existing[0].action_id == first.action_id
    assert existing[1]["files"] == expected_manifest
    with pytest.raises(ValueError, match="identity conflicts"):
        await repository.commit_action(
            rdb_session,
            session_id=agent_session.id,
            agent_id=agent_id,
            run_id=None,
            client_tool_call_id="call-1",
            binding_id=binding_id,
            mode=ExternalChannelActionMode.CONTINUE,
            message="Different input.",
            title="Investigating the incident…",
            tasks=tasks,
            files=files,
            now=_at(4),
        )


async def test_delivery_identity_and_finish_are_recorded_without_retry(
    rdb_session: AsyncSession,
) -> None:
    """Todo updates the Tracker and successful finish schedules its deletion."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    agent = await rdb_session.get(RDBAgent, agent_id)
    connection = await rdb_session.scalar(sa.select(RDBExternalChannelConnection))
    assert agent_session is not None
    assert agent is not None
    assert connection is not None
    agent.avatar = {"kind": "generated", "seed": "channel-work-agent"}
    connection.capabilities = {"upload_files": True}
    await rdb_session.flush()
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    work = await _seed_activity_tracker(rdb_session, binding_id=binding_id)
    continued = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-continue",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message=None,
        title="Preparing the channel update…",
        tasks=[
            _task(
                id="notify",
                title="Notify the channel",
                status=ExternalChannelWorkTaskStatus.PENDING,
            )
        ],
        files=(),
        now=_at(2),
    )
    update_delivery = continued.deliveries[0]
    target = await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=update_delivery.id,
        now=_at(3),
    )
    assert target is not None
    assert target.capabilities == connection.capabilities
    assert target.app_mode is connection.app_mode
    assert target.agent_name == agent.name
    assert target.agent_avatar == agent.avatar
    await repository.finish_delivery(
        rdb_session,
        delivery_attempt_id=update_delivery.id,
        status=ExternalChannelDeliveryStatus.DELIVERED,
        provider_message_key="slack:T1:C1:2.000001",
        error_kind=None,
        error_summary=None,
        now=_at(4),
    )

    finished = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-finish",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.FINISH,
        message="Done.",
        title=None,
        tasks=None,
        files=(),
        now=_at(5),
    )

    assert finished.work_status is ExternalChannelWorkStatus.FINISHED
    assert [delivery.operation for delivery in finished.deliveries] == [
        ExternalChannelDeliveryOperation.REPLY,
        ExternalChannelDeliveryOperation.PROGRESS_DELETE,
    ]
    delete_attempt = await rdb_session.get(
        RDBExternalChannelDeliveryAttempt,
        finished.deliveries[1].id,
    )
    assert delete_attempt is not None
    assert "text" not in delete_attempt.request_payload
    assert work.progress_provider_message_key == "slack:T1:C1:2.000001"
    assert work.desired_progress_payload is None

    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    snapshots = await repository.list_active_work(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
    )

    assert len(snapshots) == 1
    assert snapshots[0].latest_action_mode is None
    assert snapshots[0].latest_deliveries == []
    assert snapshots[0].projection_drift == "none"


async def test_binding_disconnect_presence_crosses_terminal_delivery_boundary(
    rdb_session: AsyncSession,
) -> None:
    """A leave control can start only after its binding becomes disconnected."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    binding = await rdb_session.get(RDBExternalChannelBinding, binding_id)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    assert binding is not None
    assert agent_session is not None
    route = await rdb_session.get(RDBExternalChannelAgentRoute, binding.route_id)
    assert route is not None
    binding.disconnected_at = _at(2)
    binding.disconnect_reason = "manager_disconnected"
    route.agent_id = None
    route.catalog_status = ExternalChannelRouteCatalogStatus.REMOVED
    route.catalog_removed_at = _at(2)
    attempt = RDBExternalChannelDeliveryAttempt(
        origin_type=ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
        origin_id=binding.id,
        channel_action_id=None,
        binding_id=binding.id,
        operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
        request_payload={
            "control_kind": "session_presence",
            "presence_state": "left",
            "channel_id": "C1",
            "thread_ts": "1.000001",
        },
        status=ExternalChannelDeliveryStatus.PENDING,
        provider_message_key=None,
        error_kind=None,
        error_summary=None,
        attempted_at=None,
        completed_at=None,
    )
    rdb_session.add(attempt)
    await rdb_session.flush()

    repository = ExternalChannelWorkRepository()
    prepared = await repository.get_delivery_target(
        rdb_session,
        delivery_attempt_id=attempt.id,
    )
    assert prepared is not None
    assert prepared.agent_name == "Channel Work Agent"
    assert prepared.agent_session_id == agent_session.id
    connection = await rdb_session.get(
        RDBExternalChannelConnection,
        prepared.connection_id,
    )
    resource = await rdb_session.get(
        RDBExternalChannelResource,
        prepared.resource_id,
    )
    assert connection is not None
    assert resource is not None
    connection.status = ExternalChannelConnectionStatus.DISCONNECTED
    connection.encrypted_credentials = None
    connection.provider_tenant_id = None
    connection.capabilities = None
    resource.status = ExternalChannelResourceStatus.UNAVAILABLE
    await rdb_session.flush()

    target = await repository.start_captured_terminal_delivery(
        rdb_session,
        target=prepared,
        now=_at(3),
    )

    assert target is not None
    assert target.status is ExternalChannelDeliveryStatus.ATTEMPTING
    assert target.encrypted_credentials == "ciphertext"
    assert target.provider_tenant_id == "T1"
    assert target.workspace_handle == "channel-work-test"
    assert target.agent_id == agent_id
    assert target.agent_session_id == agent_session.id


async def test_discord_progress_updates_one_tracker_and_finishes_cleanup(
    rdb_session: AsyncSession,
) -> None:
    """Discord retains one compact Tracker through update and cleanup."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    await _as_discord_binding(rdb_session, binding_id=binding_id)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    assert agent_session is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    task = _task(
        id="investigate",
        title="Inspect the incident",
        status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
    )
    initial = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="discord-progress-initial",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message=None,
        title="Inspecting the incident…",
        tasks=[task],
        files=(),
        now=_at(2),
    )

    assert [delivery.operation for delivery in initial.deliveries] == [
        ExternalChannelDeliveryOperation.PROGRESS_CREATE,
    ]
    create_rows = list(
        await rdb_session.scalars(
            sa.select(RDBExternalChannelDeliveryAttempt)
            .where(
                RDBExternalChannelDeliveryAttempt.channel_action_id == initial.action_id
            )
            .order_by(RDBExternalChannelDeliveryAttempt.part_ordinal)
        )
    )
    assert [row.part_ordinal for row in create_rows] == [0]
    assert create_rows[0].request_payload["text"] == ""
    assert create_rows[0].request_payload["embeds"] == [
        {
            "title": "Inspecting the incident…",
            "description": "**0/1 complete**\n◉ Inspect the incident",
            "color": 0x5865F2,
        }
    ]
    for ordinal, row in enumerate(create_rows):
        assert await repository.start_delivery(
            rdb_session,
            delivery_attempt_id=row.id,
            now=_at(3 + ordinal),
        )
        assert (
            await repository.finish_delivery(
                rdb_session,
                delivery_attempt_id=row.id,
                status=ExternalChannelDeliveryStatus.DELIVERED,
                provider_message_key=f"discord:111:{500 + ordinal}",
                error_kind=None,
                error_summary=None,
                now=_at(5 + ordinal),
            )
            is None
        )

    changed = task.model_copy(update={"details": "Inspect current provider logs."})
    update = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="discord-progress-update",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message=None,
        title="Inspecting the incident…",
        tasks=[changed],
        files=(),
        now=_at(7),
    )

    assert [delivery.operation for delivery in update.deliveries] == [
        ExternalChannelDeliveryOperation.PROGRESS_UPDATE
    ]
    update_row = await rdb_session.get(
        RDBExternalChannelDeliveryAttempt,
        update.deliveries[0].id,
    )
    assert update_row is not None
    assert update_row.part_ordinal == 0
    assert update_row.request_payload["provider_message_key"] == "discord:111:500"
    assert update_row.request_payload["text"] == ""
    assert update_row.request_payload["embeds"] == [
        {
            "title": "Inspecting the incident…",
            "description": (
                "**0/1 complete**\n"
                "◉ Inspect the incident\n"
                "  ↳ Inspect current provider logs."
            ),
            "color": 0x5865F2,
        }
    ]
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=update_row.id,
        now=_at(8),
    )
    assert (
        await repository.finish_delivery(
            rdb_session,
            delivery_attempt_id=update_row.id,
            status=ExternalChannelDeliveryStatus.DELIVERED,
            provider_message_key="discord:111:500",
            error_kind=None,
            error_summary=None,
            now=_at(9),
        )
        is None
    )

    finish = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="discord-progress-finish",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.FINISH,
        message="Done. " * 700,
        title=None,
        tasks=None,
        files=(),
        now=_at(10),
    )
    replies = [
        delivery
        for delivery in finish.deliveries
        if delivery.operation is ExternalChannelDeliveryOperation.REPLY
    ]
    assert len(replies) > 1
    reply_ordinals = {
        row.id: row.part_ordinal
        for row in await rdb_session.scalars(
            sa.select(RDBExternalChannelDeliveryAttempt).where(
                RDBExternalChannelDeliveryAttempt.id.in_(
                    [reply.id for reply in replies]
                )
            )
        )
    }
    assert [reply_ordinals[reply.id] for reply in replies] == list(range(len(replies)))
    cleanup_id: str | None = None
    for ordinal, reply in enumerate(replies):
        assert await repository.start_delivery(
            rdb_session,
            delivery_attempt_id=reply.id,
            now=_at(11 + ordinal),
        )
        cleanup_id = await repository.finish_delivery(
            rdb_session,
            delivery_attempt_id=reply.id,
            status=ExternalChannelDeliveryStatus.DELIVERED,
            provider_message_key=f"discord:111:{600 + ordinal}",
            error_kind=None,
            error_summary=None,
            now=_at(13 + ordinal),
        )
        if ordinal < len(replies) - 1:
            assert cleanup_id is None
    assert cleanup_id is not None

    cleanup_ids: list[str] = []
    while cleanup_id is not None:
        cleanup_ids.append(cleanup_id)
        assert await repository.start_delivery(
            rdb_session,
            delivery_attempt_id=cleanup_id,
            now=_at(20 + len(cleanup_ids)),
        )
        cleanup_id = await repository.finish_delivery(
            rdb_session,
            delivery_attempt_id=cleanup_id,
            status=ExternalChannelDeliveryStatus.DELIVERED,
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
            now=_at(30 + len(cleanup_ids)),
        )

    parts = list(
        await rdb_session.scalars(
            sa.select(RDBExternalChannelWorkProjectionPart)
            .where(RDBExternalChannelWorkProjectionPart.work_id == finish.work_id)
            .order_by(RDBExternalChannelWorkProjectionPart.part_ordinal)
        )
    )
    assert len(cleanup_ids) == 1
    assert all(
        part.status is ExternalChannelWorkProjectionStatus.DELETED for part in parts
    )


async def test_recreated_tracker_catches_up_to_latest_desired_revision(
    rdb_session: AsyncSession,
) -> None:
    """A replacement created during work changes receives one durable update."""
    _, binding_id = await _setup_binding(rdb_session)
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    work = await _seed_activity_tracker(rdb_session, binding_id=binding_id)
    work.progress_provider_message_key = None
    work.desired_progress_revision = 2
    work.desired_progress_payload = {
        "schema_version": 2,
        "state": "working",
        "title": "Investigating…",
        "tasks": [
            {
                "id": "investigate",
                "title": "Investigate",
                "status": "in_progress",
                "details": None,
                "output": None,
                "sources": [],
            }
        ],
    }
    create_attempt = RDBExternalChannelDeliveryAttempt(
        origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
        origin_id="replacement-event",
        operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
        request_payload={
            "work_id": work.id,
            "tenant_id": "T1",
            "channel_id": "C1",
            "thread_ts": "1.000001",
            "text": "Agent is checking your message",
            "blocks": [],
            "desired_progress_revision": 1,
        },
        status=ExternalChannelDeliveryStatus.PENDING,
        channel_action_id=None,
        binding_id=binding_id,
        provider_message_key=None,
        error_kind=None,
        error_summary=None,
        attempted_at=None,
        completed_at=None,
    )
    rdb_session.add(create_attempt)
    await rdb_session.flush()
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=create_attempt.id,
        now=_at(6),
    )

    followup_id = await repository.finish_delivery(
        rdb_session,
        delivery_attempt_id=create_attempt.id,
        status=ExternalChannelDeliveryStatus.DELIVERED,
        provider_message_key="slack:T1:C1:3.000001",
        error_kind=None,
        error_summary=None,
        now=_at(7),
    )

    assert followup_id is not None
    followup = await rdb_session.get(RDBExternalChannelDeliveryAttempt, followup_id)
    assert followup is not None
    assert followup.operation is ExternalChannelDeliveryOperation.PROGRESS_UPDATE
    assert followup.status is ExternalChannelDeliveryStatus.PENDING
    assert followup.request_payload["provider_message_key"] == ("slack:T1:C1:3.000001")
    assert followup.request_payload["desired_progress_revision"] == 2
    assert followup.request_payload["text"] == (
        "Investigating…\nIn progress: Investigate"
    )
    assert followup.request_payload["blocks"] == [
        {
            "type": "plan",
            "block_id": f"work_{work.id}_2",
            "title": "Investigating…",
            "tasks": [
                {
                    "task_id": "investigate",
                    "title": "Investigate",
                    "status": "in_progress",
                }
            ],
        },
    ]


async def test_continue_after_finish_creates_a_new_activity_tracker(
    rdb_session: AsyncSession,
) -> None:
    """A new Todo after finish starts a new work cycle and provider message."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    assert agent_session is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    finished_work = await _seed_activity_tracker(
        rdb_session,
        binding_id=binding_id,
    )
    finished = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-finish-before-next-todo",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.FINISH,
        message="The first task is complete.",
        title=None,
        tasks=None,
        files=(),
        now=_at(2),
    )

    continued = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-next-todo",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message=None,
        title="Starting the next task…",
        tasks=[
            _task(
                id="next-task",
                title="Start the next task",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
            )
        ],
        files=(),
        now=_at(3),
    )

    assert finished.work_id == finished_work.id
    assert continued.work_id != finished.work_id
    assert continued.work_status is ExternalChannelWorkStatus.ACTIVE
    assert [item.operation for item in continued.deliveries] == [
        ExternalChannelDeliveryOperation.PROGRESS_CREATE
    ]
    create_attempt = await rdb_session.get(
        RDBExternalChannelDeliveryAttempt,
        continued.deliveries[0].id,
    )
    assert create_attempt is not None
    assert create_attempt.provider_message_key is None
    assert create_attempt.request_payload["desired_progress_revision"] == 1
    assert create_attempt.request_payload["text"] == (
        "Starting the next task…\nIn progress: Start the next task"
    )
    assert create_attempt.request_payload["blocks"] == [
        {
            "type": "plan",
            "block_id": f"work_{continued.work_id}_1",
            "title": "Starting the next task…",
            "tasks": [
                {
                    "task_id": "next-task",
                    "title": "Start the next task",
                    "status": "in_progress",
                }
            ],
        },
    ]
    active_work = await rdb_session.scalar(
        sa.select(RDBExternalChannelWork).where(
            RDBExternalChannelWork.id == continued.work_id
        )
    )
    assert active_work is not None
    assert active_work.progress_provider_message_key is None
    assert active_work.desired_progress_payload == {
        "schema_version": 2,
        "state": "working",
        "title": "Starting the next task…",
        "tasks": [
            {
                "id": "next-task",
                "title": "Start the next task",
                "status": "in_progress",
                "details": None,
                "output": None,
                "sources": [],
            }
        ],
    }


async def test_late_tracker_creation_after_delivered_finish_schedules_cleanup(
    rdb_session: AsyncSession,
) -> None:
    """The later of final reply and Tracker creation owns cleanup reconciliation."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    assert agent_session is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    work = await _seed_activity_tracker(rdb_session, binding_id=binding_id)
    work.progress_provider_message_key = None
    finished = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-finish-before-create",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.FINISH,
        message="Done.",
        title=None,
        tasks=None,
        files=(),
        now=_at(2),
    )
    assert [item.operation for item in finished.deliveries] == [
        ExternalChannelDeliveryOperation.REPLY
    ]
    reply = finished.deliveries[0]
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=reply.id,
        now=_at(3),
    )
    assert (
        await repository.finish_delivery(
            rdb_session,
            delivery_attempt_id=reply.id,
            status=ExternalChannelDeliveryStatus.DELIVERED,
            provider_message_key="slack:T1:C1:3.000001",
            error_kind=None,
            error_summary=None,
            now=_at(4),
        )
        is None
    )
    late_create = RDBExternalChannelDeliveryAttempt(
        origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
        origin_id="late-activity-create",
        operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
        request_payload={
            "work_id": work.id,
            "channel_id": "C1",
            "thread_ts": "1.000001",
            "text": "Agent is checking your message",
            "blocks": [],
            "desired_progress_revision": 1,
        },
        status=ExternalChannelDeliveryStatus.PENDING,
        channel_action_id=None,
        binding_id=binding_id,
        provider_message_key=None,
        error_kind=None,
        error_summary=None,
        attempted_at=None,
        completed_at=None,
    )
    rdb_session.add(late_create)
    await rdb_session.flush()
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=late_create.id,
        now=_at(5),
    )

    cleanup_id = await repository.finish_delivery(
        rdb_session,
        delivery_attempt_id=late_create.id,
        status=ExternalChannelDeliveryStatus.DELIVERED,
        provider_message_key="slack:T1:C1:4.000001",
        error_kind=None,
        error_summary=None,
        now=_at(6),
    )

    assert cleanup_id is not None
    cleanup = await rdb_session.get(RDBExternalChannelDeliveryAttempt, cleanup_id)
    assert cleanup is not None
    assert cleanup.operation is ExternalChannelDeliveryOperation.PROGRESS_DELETE
    assert cleanup.status is ExternalChannelDeliveryStatus.PENDING
    assert cleanup.channel_action_id == finished.action_id
    assert cleanup.request_payload["provider_message_key"] == ("slack:T1:C1:4.000001")


async def test_missing_tracker_delete_is_reconciled_as_already_absent(
    rdb_session: AsyncSession,
) -> None:
    """A missing delete target satisfies Tracker cleanup without recreation."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    assert agent_session is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    work = await _seed_activity_tracker(rdb_session, binding_id=binding_id)
    finished = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-finish-missing-delete",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.FINISH,
        message="Done.",
        title=None,
        tasks=None,
        files=(),
        now=_at(2),
    )
    reply, cleanup = finished.deliveries
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=reply.id,
        now=_at(3),
    )
    assert (
        await repository.finish_delivery(
            rdb_session,
            delivery_attempt_id=reply.id,
            status=ExternalChannelDeliveryStatus.DELIVERED,
            provider_message_key="slack:T1:C1:3.000001",
            error_kind=None,
            error_summary=None,
            now=_at(4),
        )
        == cleanup.id
    )
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=cleanup.id,
        now=_at(5),
    )

    recovery_id = await repository.finish_delivery(
        rdb_session,
        delivery_attempt_id=cleanup.id,
        status=ExternalChannelDeliveryStatus.FAILED,
        provider_message_key=None,
        error_kind="message_not_found",
        error_summary="Slack no longer contains the Activity Tracker.",
        now=_at(6),
    )

    persisted_cleanup = await rdb_session.get(
        RDBExternalChannelDeliveryAttempt,
        cleanup.id,
    )
    assert recovery_id is None
    assert persisted_cleanup is not None
    assert persisted_cleanup.status is ExternalChannelDeliveryStatus.DELIVERED
    assert persisted_cleanup.error_kind == "message_already_absent"
    assert work.progress_provider_message_key is None


async def test_recovery_terminalizes_pending_and_attempting_without_execution(
    rdb_session: AsyncSession,
) -> None:
    """Recovery conservatively reports committed attempts and never re-executes."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    assert agent_session is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    await _seed_activity_tracker(rdb_session, binding_id=binding_id)
    committed = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-recover",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Working on it.",
        title="Completing the work…",
        tasks=[
            _task(
                id="work",
                title="Complete the work",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
            )
        ],
        files=(),
        now=_at(2),
    )
    await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=committed.deliveries[0].id,
        now=_at(3),
    )

    recovered = await repository.recover_action_by_client_tool_call(
        rdb_session,
        session_id=agent_session.id,
        client_tool_call_id="call-recover",
        now=_at(4),
    )

    assert recovered is not None
    assert [item.status for item in recovered.deliveries] == [
        ExternalChannelDeliveryStatus.UNKNOWN,
        ExternalChannelDeliveryStatus.NOT_ATTEMPTED,
    ]


async def test_runtime_authority_revocation_after_provider_start_is_unknown(
    rdb_session: AsyncSession,
) -> None:
    """A later authority revocation cannot erase durable provider-start evidence."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    binding = await rdb_session.get(RDBExternalChannelBinding, binding_id)
    assert agent_session is not None
    assert binding is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    committed = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-runtime-authority-revoked",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message="Uploading the report.",
        title=None,
        tasks=None,
        files=(),
        now=_at(2),
    )
    delivery_id = committed.deliveries[0].id
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=delivery_id,
        now=_at(3),
        runtime_target=None,
    )
    attempt = await rdb_session.get(RDBExternalChannelDeliveryAttempt, delivery_id)
    assert attempt is not None
    attempt.request_payload = {
        **attempt.request_payload,
        "runtime_provider_recovery": {"state": "provider_started"},
    }
    await rdb_session.flush()

    current = await repository.revalidate_runtime_delivery_authority(
        rdb_session,
        delivery_attempt_id=delivery_id,
        runtime_target=ServerToRuntimeTarget(
            runtime_id="runtime-1",
            desired_generation=1,
        ),
        provider_started=False,
        now=_at(4),
    )

    assert not current
    assert attempt.status is ExternalChannelDeliveryStatus.UNKNOWN
    assert attempt.error_kind == "runtime_delivery_authority_revoked"


async def test_provider_control_final_settlement_revalidates_current_authority(
    rdb_session: AsyncSession,
) -> None:
    """A provider control becomes unknown when its binding is revoked after I/O."""
    _agent_id, binding_id = await _setup_binding(rdb_session)
    binding = await rdb_session.get(RDBExternalChannelBinding, binding_id)
    assert binding is not None
    attempt = RDBExternalChannelDeliveryAttempt(
        origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
        origin_id="manager-operation-1",
        operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
        request_payload={
            "channel_id": "C1",
            "thread_ts": "1.000001",
            "text": "Control",
        },
        status=ExternalChannelDeliveryStatus.PENDING,
        channel_action_id=None,
        binding_id=binding_id,
        provider_message_key=None,
        error_kind=None,
        error_summary=None,
        attempted_at=None,
        completed_at=None,
    )
    rdb_session.add(attempt)
    await rdb_session.flush()
    repository = ExternalChannelWorkRepository()
    started = await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=attempt.id,
        now=_at(2),
    )
    assert started is not None
    binding.disconnected_at = _at(2)
    await rdb_session.flush()

    settlement = await repository.settle_delivery(
        rdb_session,
        delivery_attempt_id=attempt.id,
        status=ExternalChannelDeliveryStatus.DELIVERED,
        provider_message_key="slack:T1:C1:2.000001",
        error_kind=None,
        error_summary=None,
        now=_at(3),
    )

    assert settlement.accepted
    assert settlement.status is ExternalChannelDeliveryStatus.UNKNOWN
    assert settlement.recovery_delivery_id is None
    assert attempt.status is ExternalChannelDeliveryStatus.UNKNOWN
    assert attempt.provider_message_key == "slack:T1:C1:2.000001"
    assert attempt.error_kind == "delivery_authority_revoked_after_provider"
    assert attempt.completed_at == _at(3)


async def test_initial_discord_delivery_uses_active_binding_authority(
    rdb_session: AsyncSession,
) -> None:
    """Initial Discord intents use the same retained active-binding authority."""
    _agent_id, binding_id = await _setup_binding(rdb_session)
    await _as_discord_binding(rdb_session, binding_id=binding_id)
    binding = await rdb_session.get(RDBExternalChannelBinding, binding_id)
    assert binding is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    work = await rdb_session.scalar(
        sa.select(RDBExternalChannelWork).where(
            RDBExternalChannelWork.binding_id == binding_id,
            RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
        )
    )
    assert work is not None
    work.desired_progress_revision = 1
    work.desired_progress_payload = {
        "schema_version": 2,
        "state": "checking",
        "title": None,
        "tasks": [],
    }
    progress_ids = await repository.ensure_initial_discord_progress(
        rdb_session,
        work_id=work.id,
        binding_id=binding_id,
        labels={"guild_id": "111", "thread_id": "333"},
    )
    assert len(progress_ids) == 1
    progress_id = progress_ids[0]
    progress = await rdb_session.get(
        RDBExternalChannelDeliveryAttempt,
        progress_id,
    )
    assert progress is not None
    session_presence = RDBExternalChannelDeliveryAttempt(
        origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
        origin_id=binding_id,
        operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
        request_payload={
            "control_kind": "session_presence",
            "presence_state": "joined",
        },
        status=ExternalChannelDeliveryStatus.PENDING,
        channel_action_id=None,
        binding_id=binding_id,
        provider_message_key=None,
        error_kind=None,
        error_summary=None,
        attempted_at=None,
        completed_at=None,
    )
    rdb_session.add(session_presence)
    await rdb_session.flush()

    for attempt in (session_presence, progress):
        target = await repository.start_delivery(
            rdb_session,
            delivery_attempt_id=attempt.id,
            now=_at(3),
        )
        assert target is not None
        assert target.provider is ExternalChannelProvider.DISCORD
        assert attempt.status is ExternalChannelDeliveryStatus.ATTEMPTING


async def test_initial_discord_progress_update_uses_active_binding_authority(
    rdb_session: AsyncSession,
) -> None:
    """The current catch-up update uses retained active-binding authority."""
    _agent_id, binding_id = await _setup_binding(rdb_session)
    await _as_discord_binding(rdb_session, binding_id=binding_id)
    binding = await rdb_session.get(RDBExternalChannelBinding, binding_id)
    assert binding is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)
    work = await rdb_session.scalar(
        sa.select(RDBExternalChannelWork).where(
            RDBExternalChannelWork.binding_id == binding_id,
            RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
        )
    )
    assert work is not None
    work.desired_progress_revision = 1
    work.desired_progress_payload = {
        "schema_version": 2,
        "state": "checking",
        "title": None,
        "tasks": [],
    }
    create_ids = await repository.ensure_initial_discord_progress(
        rdb_session,
        work_id=work.id,
        binding_id=binding_id,
        labels={"guild_id": "111", "thread_id": "333"},
    )
    assert len(create_ids) == 1
    create_id = create_ids[0]
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=create_id,
        now=_at(2),
    )
    work.desired_progress_revision = 2
    work.desired_progress_payload = {
        "schema_version": 2,
        "state": "working",
        "title": "Investigating…",
        "tasks": [
            {
                "id": "investigate",
                "title": "Investigate",
                "status": "in_progress",
                "details": None,
                "output": None,
                "sources": [],
            }
        ],
    }
    update_id = await repository.finish_delivery(
        rdb_session,
        delivery_attempt_id=create_id,
        status=ExternalChannelDeliveryStatus.DELIVERED,
        provider_message_key="discord:111:500",
        error_kind=None,
        error_summary=None,
        now=_at(3),
    )
    assert update_id is not None

    target = await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=update_id,
        now=_at(4),
    )

    assert target is not None
    assert target.operation is ExternalChannelDeliveryOperation.PROGRESS_UPDATE
    assert target.request_payload["provider_message_key"] == "discord:111:500"


async def test_active_work_snapshot_fences_session_and_agent_lifecycle(
    rdb_session: AsyncSession,
) -> None:
    """Archived Sessions and decommissioning Agents expose no Channel Work."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    agent = await rdb_session.get(RDBAgent, agent_id)
    assert agent_session is not None
    assert agent is not None
    repository = ExternalChannelWorkRepository()
    await repository.ensure_active_work(rdb_session, binding_id=binding_id)

    assert await repository.has_active_binding(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
    )
    assert (
        len(
            await repository.list_active_work(
                rdb_session,
                session_id=agent_session.id,
                agent_id=agent_id,
            )
        )
        == 1
    )

    agent_session.status = AgentSessionStatus.ARCHIVED
    await rdb_session.flush()

    assert not await repository.has_active_binding(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
    )
    assert (
        await repository.list_active_work(
            rdb_session,
            session_id=agent_session.id,
            agent_id=agent_id,
        )
        == []
    )

    agent_session.status = AgentSessionStatus.ACTIVE
    agent.lifecycle_status = AgentLifecycleStatus.DECOMMISSIONING
    await rdb_session.flush()

    assert not await repository.has_active_binding(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
    )
    assert (
        await repository.list_active_work(
            rdb_session,
            session_id=agent_session.id,
            agent_id=agent_id,
        )
        == []
    )


async def test_file_access_target_requires_complete_active_binding_chain(
    rdb_session: AsyncSession,
) -> None:
    """File access resolves credentials only through the owned active binding."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    connection = await rdb_session.scalar(sa.select(RDBExternalChannelConnection))
    binding = await rdb_session.get(RDBExternalChannelBinding, binding_id)
    assert agent_session is not None
    assert connection is not None
    assert binding is not None
    connection.capabilities = {
        "provider": "slack",
        "transport": "http",
        "inbound_events": True,
        "thread_history": True,
        "post_messages": True,
        "update_messages": True,
        "delete_messages": True,
        "download_files": True,
        "upload_files": False,
    }
    await rdb_session.flush()
    repository = ExternalChannelWorkRepository()

    target = await repository.get_active_file_access_target(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        binding_id=binding_id,
    )

    assert target is not None
    assert target.binding_id == binding_id
    assert target.connection_id == connection.id
    assert target.encrypted_credentials == "ciphertext"
    assert target.capabilities is not None
    assert target.capabilities["download_files"] is True
    assert (
        await repository.get_active_file_access_target(
            rdb_session,
            session_id="unrelated-session",
            agent_id=agent_id,
            binding_id=binding_id,
        )
        is None
    )

    binding.disconnected_at = _at(2)
    binding.disconnect_reason = "test_disconnect"
    await rdb_session.flush()

    assert (
        await repository.get_active_file_access_target(
            rdb_session,
            session_id=agent_session.id,
            agent_id=agent_id,
            binding_id=binding_id,
        )
        is None
    )
