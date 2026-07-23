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
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelWork,
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
from azents.testing.model_selection import make_test_model_selection_dict


def _at(second: int) -> datetime.datetime:
    return datetime.datetime(2026, 7, 22, 0, 0, second, tzinfo=datetime.UTC)


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
        "state": "checking",
        "tasks": [],
        "session_url": "https://azents.example/w/test/agents/agent/sessions/session",
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
            route_mode=ExternalChannelRouteMode.DEDICATED,
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
            hydration_status=ExternalChannelHydrationStatus.COMPLETE,
            hydration_cursor=None,
            hydration_high_watermark_position=None,
            reconciliation_boundary_received_at=None,
            reconciliation_boundary_event_id=None,
            hydration_error_kind=None,
            hydration_error_summary=None,
            hydration_started_at=_at(0),
            hydration_completed_at=_at(1),
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
            status=ExternalChannelBindingStatus.ACTIVE,
            activation_status=ExternalChannelBindingActivationStatus.ACTIVE,
            activation_trigger_message_id=None,
            activated_at=_at(1),
            projected_through_position=None,
            truncated_message_count=0,
            truncated_size=0,
            disconnected_at=None,
            disconnect_reason=None,
        ),
    )
    await session.flush()
    return agent.id, binding.id


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
        ChannelWorkTask(
            id="investigate",
            title="Investigate the incident",
            status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
        )
    ]

    first = await repository.commit_action(
        rdb_session,
        session_id=agent_session.id,
        agent_id=agent_id,
        run_id=None,
        client_tool_call_id="call-1",
        binding_id=binding_id,
        mode=ExternalChannelActionMode.CONTINUE,
        message="I am investigating.",
        tasks=tasks,
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
        tasks=tasks,
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
            tasks=tasks,
            now=_at(4),
        )


async def test_delivery_identity_and_finish_are_recorded_without_retry(
    rdb_session: AsyncSession,
) -> None:
    """Todo and completion update one retained Activity Tracker."""
    agent_id, binding_id = await _setup_binding(rdb_session)
    agent_session = await rdb_session.scalar(
        sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
    )
    assert agent_session is not None
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
        tasks=[
            ChannelWorkTask(
                id="notify",
                title="Notify the channel",
                status=ExternalChannelWorkTaskStatus.PENDING,
            )
        ],
        now=_at(2),
    )
    update_delivery = continued.deliveries[0]
    assert await repository.start_delivery(
        rdb_session,
        delivery_attempt_id=update_delivery.id,
        now=_at(3),
    )
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
        tasks=None,
        now=_at(5),
    )

    assert finished.work_status is ExternalChannelWorkStatus.FINISHED
    assert [delivery.operation for delivery in finished.deliveries] == [
        ExternalChannelDeliveryOperation.REPLY,
        ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
    ]
    completion_attempt = await rdb_session.get(
        RDBExternalChannelDeliveryAttempt,
        finished.deliveries[1].id,
    )
    assert completion_attempt is not None
    assert completion_attempt.request_payload["text"] == "Answer complete"
    assert work.progress_provider_message_key == "slack:T1:C1:2.000001"
    assert work.desired_progress_payload == {
        "state": "completed",
        "tasks": [],
        "session_url": "https://azents.example/w/test/agents/agent/sessions/session",
    }

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
        "state": "working",
        "tasks": [{"title": "Investigate", "status": "in_progress"}],
        "session_url": "https://azents.example/w/test/agents/agent/sessions/session",
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
    assert followup.request_payload["text"] == "Agent is working\n◐ Investigate"


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
        tasks=[
            ChannelWorkTask(
                id="work",
                title="Complete the work",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
            )
        ],
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
