"""Focused current-projection tests for direct External Channel Work."""

import datetime
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Literal, NamedTuple
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
    ExternalChannelResourceType,
    ExternalChannelTransport,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
    checking_progress,
)
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
from azents.services.external_channel.slack_events import (
    SLACK_MARKDOWN_TEXT_MAX_LENGTH,
)
from azents.testing.external_channel import make_provider_effect_plan


class _CommitIgnoreResult(NamedTuple):
    """Committed ignore transition and state-store observation."""

    transition: ChannelActionTransition
    work: ChannelWorkState
    update: AsyncMock


def _string(value: object) -> str:
    """Validate one provider payload string."""
    if not isinstance(value, str):
        raise AssertionError("Expected a string.")
    return value


def _work(
    *,
    desired: bool,
    tracker_visibility: Literal["hidden", "visible"] = "visible",
    projection_parts: list[ChannelWorkProjectionPartState] | None = None,
) -> ChannelWorkState:
    return ChannelWorkState(
        schema_version=4,
        binding_id="binding-1",
        work_cycle_id="work-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        tracker_visibility=tracker_visibility,
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
        title="Working…" if desired else None,
        tasks=[],
        state_revision=2,
        desired_progress_revision=3,
        desired_progress=checking_progress() if desired else None,
        awaiting_input_run_id=None,
        finished_at=None,
        projection_parts=projection_parts or [],
    )


def _part(
    *,
    status: ExternalChannelWorkProjectionStatus,
    provider_message_key: str | None,
    revision: int = 3,
    part_ordinal: int = 0,
) -> ChannelWorkProjectionPartState:
    return ChannelWorkProjectionPartState(
        part_ordinal=part_ordinal,
        desired_progress_revision=revision,
        status=status,
        provider_message_key=provider_message_key,
    )


def test_projection_state_is_missing_without_owned_parts() -> None:
    assert projection_state(_work(desired=True)) == "missing"


def test_projection_state_is_none_for_intentionally_hidden_work() -> None:
    assert projection_state(_work(desired=True, tracker_visibility="hidden")) == "none"


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
        provider_config={
            "provider": "discord",
            "target_guild_id": "tenant-1",
            "thread_auto_archive_duration_minutes": 1440,
        },
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=connection)
    repository = ExternalChannelWorkRepository()

    plan = await repository.prepare_direct_control(
        session,
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
    ("provider", "labels", "flag_name"),
    [
        (
            ExternalChannelProvider.SLACK,
            {
                "channel_id": "channel-1",
                "thread_ts": "1.000001",
                "conversation_scope": "thread",
            },
            "reply_broadcast",
        ),
        (
            ExternalChannelProvider.DISCORD,
            {
                "guild_id": "111",
                "thread_id": "333",
                "parent_channel_id": "222",
                "conversation_scope": "thread",
            },
            "forward_to_parent",
        ),
    ],
)
async def test_binding_reply_effects_preserve_exact_thread_surfacing(
    provider: ExternalChannelProvider,
    labels: dict[str, object],
    flag_name: str,
) -> None:
    """Scheduled terminal parts retain provider-native parent surfacing intent."""
    binding = SimpleNamespace(id="binding-1")
    resource = SimpleNamespace(id="resource-1", labels=labels)
    route = SimpleNamespace(id="route-1")
    connection = SimpleNamespace(id="connection-1", provider=provider)
    result = MagicMock()
    result.one_or_none.return_value = (binding, resource, route, connection)
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=result)
    repository = ExternalChannelWorkRepository()
    prepared = make_provider_effect_plan("scheduled-terminal")
    repository.prepare_direct_control = AsyncMock(return_value=prepared)

    plans = await repository.prepare_binding_reply_effects(
        session,
        agent_id="agent-1",
        session_id="session-1",
        binding_id=binding.id,
        text="Completed.",
        files=(),
        operation_seed="scheduled-terminal:cycle-1",
        slack_reply_broadcast=True,
        discord_forward_to_parent=True,
    )

    assert plans == (prepared,)
    prepare_call = repository.prepare_direct_control.await_args
    assert prepare_call is not None
    payload = prepare_call.kwargs["request_payload"]
    assert payload[flag_name] is True
    if provider is ExternalChannelProvider.DISCORD:
        assert payload["parent_channel_id"] == "222"
    execute_call = session.execute.await_args
    assert execute_call is not None
    where_sql = _where_sql(execute_call.args[0])
    assert "external_channel_bindings.id" in where_sql
    assert "external_channel_bindings.agent_session_id" in where_sql
    assert "external_channel_agent_routes.agent_id" in where_sql


async def test_binding_effect_revalidation_rejects_changed_agent_authority() -> None:
    """A live Binding cannot silently move one captured effect to another Agent."""
    plan = make_provider_effect_plan("scheduled-effect")
    changed = replace(
        plan,
        target=replace(plan.target, agent_id="agent-2"),
    )
    repository = ExternalChannelWorkRepository()
    repository.revalidate_direct_control = AsyncMock(return_value=changed)

    current = await repository.revalidate_binding_effect(
        MagicMock(spec=AsyncSession),
        plan=plan,
    )

    assert current is None


async def test_slack_binding_reply_effects_split_oversized_terminal_text() -> None:
    """Scheduled Slack terminal text is lowered into ordered bounded parts."""
    binding = SimpleNamespace(id="binding-1")
    resource = SimpleNamespace(
        id="resource-1",
        labels={
            "channel_id": "channel-1",
            "thread_ts": "1.000001",
            "conversation_scope": "thread",
        },
    )
    route = SimpleNamespace(id="route-1")
    connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.SLACK,
    )
    result = MagicMock()
    result.one_or_none.return_value = (binding, resource, route, connection)
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=result)
    repository = ExternalChannelWorkRepository()
    repository.prepare_direct_control = AsyncMock(
        side_effect=[
            make_provider_effect_plan("scheduled-terminal:0"),
            make_provider_effect_plan("scheduled-terminal:1"),
        ]
    )

    plans = await repository.prepare_binding_reply_effects(
        session,
        agent_id="agent-1",
        session_id="session-1",
        binding_id=binding.id,
        text=("x" * 12_000) + "\ncontinued",
        files=(),
        operation_seed="scheduled-terminal:cycle-1",
        slack_reply_broadcast=True,
        discord_forward_to_parent=True,
    )

    assert len(plans) == 2
    payloads = [
        awaited.kwargs["request_payload"]
        for awaited in repository.prepare_direct_control.await_args_list
    ]
    assert "".join(_string(payload["text"]) for payload in payloads) == (
        ("x" * 12_000) + "\ncontinued"
    )
    assert all(
        len(_string(payload["text"])) <= SLACK_MARKDOWN_TEXT_MAX_LENGTH - 512
        for payload in payloads
    )
    assert all(payload["reply_broadcast"] is True for payload in payloads)


@pytest.mark.parametrize(
    "existing_status",
    list(ExternalChannelWorkProjectionStatus),
)
async def test_initial_progress_is_claimed_once_per_active_work(
    existing_status: ExternalChannelWorkProjectionStatus,
) -> None:
    """Repeated admissions cannot create another Tracker for the same active Work."""
    work = ChannelWorkState(
        schema_version=4,
        binding_id="binding-1",
        work_cycle_id="work-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        tracker_visibility="visible",
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
        title=None,
        tasks=[],
        state_revision=1,
        desired_progress_revision=1,
        desired_progress=checking_progress(),
        awaiting_input_run_id=None,
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
        session,
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
        session,
        agent_id="agent-1",
        session_id="session-1",
        binding_id=binding.id,
        work_cycle_id=work.work_cycle_id,
    )

    assert repeated is None
    repository.prepare_direct_control.assert_awaited_once()


async def test_ensure_active_work_promotes_hidden_work_monotonically() -> None:
    """A later invocation promotes one active hidden Work without replacing it."""
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)
    current: ChannelWorkState | None = None

    async def update(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        default_factory: Callable[[], ChannelWorkState],
        mutator: Callable[
            [ChannelWorkState],
            ChannelWorkStateMutation[ChannelWorkState],
        ],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[ChannelWorkState]:
        nonlocal current
        del _session, agent_id, session_id, binding_id, max_retries
        mutation = mutator(default_factory() if current is None else current)
        current = mutation.state
        return mutation

    state_store.update = AsyncMock(side_effect=update)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)
    progress = checking_progress()

    hidden = await repository.ensure_active_work(
        MagicMock(spec=AsyncSession),
        agent_id="agent-1",
        session_id="session-1",
        binding_id="binding-1",
        desired_progress=progress,
        tracker_visibility="hidden",
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
    )
    hidden_work_cycle_id = hidden.work_cycle_id
    hidden_state_revision = hidden.state_revision
    assert hidden.tracker_visibility == "hidden"

    repeated_hidden = await repository.ensure_active_work(
        MagicMock(spec=AsyncSession),
        agent_id="agent-1",
        session_id="session-1",
        binding_id="binding-1",
        desired_progress=progress,
        tracker_visibility="hidden",
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
    )
    assert repeated_hidden == hidden

    promoted = await repository.ensure_active_work(
        MagicMock(spec=AsyncSession),
        agent_id="agent-1",
        session_id="session-1",
        binding_id="binding-1",
        desired_progress=progress,
        tracker_visibility="visible",
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
    )
    assert promoted.work_cycle_id == hidden_work_cycle_id
    assert promoted.tracker_visibility == "visible"
    assert promoted.state_revision == hidden_state_revision + 1
    assert promoted.desired_progress == hidden.desired_progress
    assert promoted.desired_progress_revision == hidden.desired_progress_revision

    repeated_visible = await repository.ensure_active_work(
        MagicMock(spec=AsyncSession),
        agent_id="agent-1",
        session_id="session-1",
        binding_id="binding-1",
        desired_progress=progress,
        tracker_visibility="hidden",
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
    )
    assert repeated_visible == promoted
    state_store.update.assert_awaited()


async def test_ensure_active_work_uses_requested_visibility_for_new_cycle() -> None:
    """Reactivation gets one fresh visibility classification from its new trigger."""
    finished = _work(desired=False)
    finished.status = ExternalChannelWorkStatus.FINISHED
    finished.finished_at = datetime.datetime(2026, 8, 3, tzinfo=datetime.UTC)
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)
    current = finished

    async def update(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        default_factory: Callable[[], ChannelWorkState],
        mutator: Callable[
            [ChannelWorkState],
            ChannelWorkStateMutation[ChannelWorkState],
        ],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[ChannelWorkState]:
        nonlocal current
        del _session, agent_id, session_id, binding_id, default_factory, max_retries
        mutation = mutator(current)
        current = mutation.state
        return mutation

    state_store.update = AsyncMock(side_effect=update)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)

    replacement = await repository.ensure_active_work(
        MagicMock(spec=AsyncSession),
        agent_id="agent-1",
        session_id="session-1",
        binding_id="binding-1",
        desired_progress=checking_progress(),
        tracker_visibility="hidden",
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
    )

    assert replacement.work_cycle_id != finished.work_cycle_id
    assert replacement.tracker_visibility == "hidden"
    assert replacement.projection_parts == []
    assert replacement.desired_progress_revision == 1


async def test_initial_progress_hidden_work_plans_no_tracker() -> None:
    """A hidden Work retains desired progress without claiming provider projection."""
    work = _work(desired=True, tracker_visibility="hidden")
    binding = SimpleNamespace(id="binding-1")
    resource = SimpleNamespace(id="resource-1", labels={"guild_id": "111"})
    route = SimpleNamespace(id="route-1")
    connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
    )
    result = MagicMock()
    result.one_or_none.return_value = (binding, resource, route, connection)
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)
    state_store.load = AsyncMock(return_value=work)
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=result)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)
    repository.prepare_direct_control = AsyncMock()

    plan = await repository.prepare_initial_progress(
        session,
        agent_id="agent-1",
        session_id="session-1",
        binding_id=binding.id,
        work_cycle_id=work.work_cycle_id,
    )

    assert plan is None
    assert work.projection_parts == []
    repository.prepare_direct_control.assert_not_awaited()
    state_store.update_existing.assert_not_awaited()


async def test_initial_progress_rerenders_latest_progress_after_claim_race() -> None:
    """A late promotion claims one Tracker from the latest complete snapshot."""
    initial = _work(desired=True)
    latest_task = ChannelWorkTask(
        id="task-1",
        title="Latest task",
        status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
        details=None,
        output=None,
        sources=[],
    )
    latest_progress = ExternalChannelDesiredProgress(
        schema_version=2,
        state="working",
        title="Latest work…",
        tasks=[latest_task],
    )
    latest = initial.model_copy(deep=True)
    latest.title = latest_progress.title
    latest.tasks = list(latest_progress.tasks)
    latest.state_revision += 1
    latest.desired_progress_revision += 1
    latest.desired_progress = latest_progress
    binding = SimpleNamespace(id="binding-1")
    resource = SimpleNamespace(
        id="resource-1",
        labels={
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
    result.one_or_none.return_value = (binding, resource, route, connection)
    current = initial
    update_attempts = 0
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)

    async def load_state(*args: object, **kwargs: object) -> ChannelWorkState:
        del args, kwargs
        return current

    async def update_existing(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        mutator: Callable[
            [ChannelWorkState],
            ChannelWorkStateMutation[Literal["claimed", "retry", "stop"]],
        ],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[Literal["claimed", "retry", "stop"]]:
        nonlocal current, update_attempts
        del _session, agent_id, session_id, binding_id, max_retries
        if update_attempts == 0:
            current = latest
        update_attempts += 1
        mutation = mutator(current)
        current = mutation.state
        return mutation

    state_store.load = AsyncMock(side_effect=load_state)
    state_store.update_existing = AsyncMock(side_effect=update_existing)
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=result)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)
    initial_plan = make_provider_effect_plan("initial-progress:initial")
    latest_plan = make_provider_effect_plan("initial-progress:latest")
    repository.prepare_direct_control = AsyncMock(
        side_effect=[initial_plan, latest_plan]
    )

    plan = await repository.prepare_initial_progress(
        session,
        agent_id="agent-1",
        session_id="session-1",
        binding_id=binding.id,
        work_cycle_id=initial.work_cycle_id,
    )

    assert plan == latest_plan
    assert len(current.projection_parts) == 1
    claimed = current.projection_parts[0]
    assert claimed.part_ordinal == 0
    assert claimed.desired_progress_revision == latest.desired_progress_revision
    assert state_store.update_existing.await_count == 2
    assert repository.prepare_direct_control.await_count == 2
    first_payload = repository.prepare_direct_control.await_args_list[0].kwargs[
        "request_payload"
    ]
    latest_payload = repository.prepare_direct_control.await_args_list[1].kwargs[
        "request_payload"
    ]
    assert (
        first_payload["desired_progress_revision"] == initial.desired_progress_revision
    )
    assert (
        latest_payload["desired_progress_revision"] == latest.desired_progress_revision
    )
    assert latest_progress.title in latest_payload["text"]


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
            session,
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


async def test_request_input_requires_participant_visible_message() -> None:
    """Repository validation rejects a request that cannot reach the participant."""
    repository = ExternalChannelWorkRepository()

    with pytest.raises(ValueError, match="Request input requires"):
        await repository.commit_direct_action(
            MagicMock(spec=AsyncSession),
            session_id="session-1",
            agent_id="agent-1",
            run_id="run-1",
            client_tool_call_id="tool-call-request",
            binding_id="binding-1",
            mode=ExternalChannelActionMode.REQUEST_INPUT,
            message=None,
            title=None,
            tasks=None,
            files=(),
            now=datetime.datetime(2026, 8, 31, tzinfo=datetime.UTC),
        )


async def test_awaiting_settlement_uses_exact_cycle_and_state_revision() -> None:
    """Only the unchanged requesting Work revision can become awaiting."""
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)
    current = _work(desired=False)

    async def update_existing(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        mutator: Callable[[ChannelWorkState], ChannelWorkStateMutation[object]],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[object]:
        nonlocal current
        del _session, agent_id, session_id, binding_id, max_retries
        mutation = mutator(current)
        current = mutation.state
        return mutation

    state_store.update_existing = AsyncMock(side_effect=update_existing)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)

    settled = await repository.settle_awaiting_input(
        MagicMock(spec=AsyncSession),
        session_id="session-1",
        agent_id="agent-1",
        binding_id="binding-1",
        run_id="run-request",
        work_cycle_id=current.work_cycle_id,
        expected_state_revision=current.state_revision,
    )

    assert settled.established is True
    assert settled.state_revision == 3
    assert current.awaiting_input_run_id == "run-request"
    assert current.state_revision == 3


async def test_newer_transition_rejects_stale_awaiting_settlement() -> None:
    """A newer same-binding revision fences an older delivery result."""
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)
    current = _work(desired=False)
    current.state_revision = 4

    async def update_existing(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        mutator: Callable[[ChannelWorkState], ChannelWorkStateMutation[object]],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[object]:
        del _session, agent_id, session_id, binding_id, max_retries
        return mutator(current)

    state_store.update_existing = AsyncMock(side_effect=update_existing)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)

    settled = await repository.settle_awaiting_input(
        MagicMock(spec=AsyncSession),
        session_id="session-1",
        agent_id="agent-1",
        binding_id="binding-1",
        run_id="run-request",
        work_cycle_id=current.work_cycle_id,
        expected_state_revision=3,
    )

    assert settled.established is False
    assert settled.state_revision == 4
    assert current.awaiting_input_run_id is None


@pytest.mark.parametrize("awaiting_run_id", [None, "run-request"])
async def test_created_human_input_always_invalidates_older_settlement(
    awaiting_run_id: str | None,
) -> None:
    """Canonical same-binding input advances revision even when Work was ready."""
    state_store = MagicMock(spec=ExternalChannelWorkStateStore)
    current = _work(desired=False)
    current.awaiting_input_run_id = awaiting_run_id

    async def update_existing(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        mutator: Callable[[ChannelWorkState], ChannelWorkStateMutation[object]],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[object]:
        nonlocal current
        del _session, agent_id, session_id, binding_id, max_retries
        mutation = mutator(current)
        current = mutation.state
        return mutation

    state_store.update_existing = AsyncMock(side_effect=update_existing)
    repository = ExternalChannelWorkRepository(work_state_store=state_store)

    resumed = await repository.resume_from_human_input(
        MagicMock(spec=AsyncSession),
        session_id="session-1",
        agent_id="agent-1",
        binding_id="binding-1",
    )

    assert resumed is current
    assert current.awaiting_input_run_id is None
    assert current.state_revision == 3


async def test_hidden_continue_with_unfinished_tasks_creates_tracker() -> None:
    """Canonical unfinished tasks promote hidden Work and create its Tracker."""
    work = _work(desired=True, tracker_visibility="hidden")
    work.awaiting_input_run_id = "run-request"
    initial_state_revision = work.state_revision
    binding = SimpleNamespace(
        id="binding-1",
        route_id="route-1",
        resource_id="resource-1",
    )
    route = SimpleNamespace(id="route-1", connection_id="connection-1")
    connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        app_mode=ExternalChannelAppMode.SINGLE,
        encrypted_credentials="ciphertext",
        provider_tenant_id="111",
        capabilities={},
        provider_config={
            "provider": "discord",
            "target_guild_id": "111",
            "thread_auto_archive_duration_minutes": 1440,
        },
    )
    agent = SimpleNamespace(
        id="agent-1",
        workspace_id="workspace-1",
        name="Agent",
        avatar=None,
    )
    resource = SimpleNamespace(
        id="resource-1",
        labels={
            "guild_id": "111",
            "parent_channel_id": "333",
            "conversation_scope": "parent_channel",
        },
    )
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
            ChannelWorkStateMutation[ChannelActionTransition],
        ],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[ChannelActionTransition]:
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
    tasks = [
        ChannelWorkTask(
            id="task-1",
            title="Latest task",
            status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
            details=None,
            output=None,
            sources=[],
        )
    ]

    transition = await repository.commit_direct_action(
        session,
        session_id="session-1",
        agent_id="agent-1",
        run_id="run-1",
        client_tool_call_id="tool-call-hidden-continue",
        binding_id=binding.id,
        mode=ExternalChannelActionMode.CONTINUE,
        message=None,
        title="Latest work…",
        tasks=tasks,
        files=(),
        now=datetime.datetime(2026, 8, 3, tzinfo=datetime.UTC),
    )

    assert transition.work_status is ExternalChannelWorkStatus.ACTIVE
    assert len(transition.effects) == 1
    assert (
        transition.effects[0].provider.target.operation
        is ExternalChannelDeliveryOperation.PROGRESS_CREATE
    )
    assert current.tracker_visibility == "visible"
    assert current.desired_progress is not None
    assert current.desired_progress.title == "Latest work…"
    assert current.desired_progress.tasks == tasks
    assert current.awaiting_input_run_id is None
    assert current.state_revision == initial_state_revision + 1
    assert current.projection_parts == []


@pytest.mark.parametrize(
    "tracker_visibility",
    ["visible", "hidden"],
)
async def test_continue_after_finished_work_with_tasks_is_visible(
    tracker_visibility: Literal["hidden", "visible"],
) -> None:
    """A replacement cycle with unfinished tasks has a visible Tracker."""
    finished = _work(
        desired=False,
        tracker_visibility=tracker_visibility,
        projection_parts=[
            _part(
                status=ExternalChannelWorkProjectionStatus.DELETED,
                provider_message_key=None,
            )
        ],
    )
    finished.status = ExternalChannelWorkStatus.FINISHED
    finished.finished_at = datetime.datetime(2026, 8, 3, tzinfo=datetime.UTC)
    binding = SimpleNamespace(
        id="binding-1",
        route_id="route-1",
        resource_id="resource-1",
    )
    route = SimpleNamespace(id="route-1", connection_id="connection-1")
    connection = SimpleNamespace(
        id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        app_mode=ExternalChannelAppMode.SINGLE,
        encrypted_credentials="ciphertext",
        provider_tenant_id="tenant-1",
        capabilities={},
        provider_config=None,
    )
    agent = SimpleNamespace(
        id="agent-1",
        workspace_id="workspace-1",
        name="Agent",
        avatar=None,
    )
    resource = SimpleNamespace(
        id="resource-1",
        resource_type=ExternalChannelResourceType.THREAD,
        labels={
            "channel_id": "channel-1",
            "thread_ts": "1.000001",
        },
    )
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
    current = finished

    async def update(
        _session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        default_factory: Callable[[], ChannelWorkState],
        mutator: Callable[
            [ChannelWorkState],
            ChannelWorkStateMutation[ChannelActionTransition],
        ],
        max_retries: int = 3,
    ) -> ChannelWorkStateMutation[ChannelActionTransition]:
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
        session,
        session_id="session-1",
        agent_id="agent-1",
        run_id="run-1",
        client_tool_call_id="tool-call-reactivate",
        binding_id=binding.id,
        mode=ExternalChannelActionMode.CONTINUE,
        message=None,
        title="Working…",
        tasks=[
            ChannelWorkTask(
                id="task-1",
                title="Follow-up task",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                details=None,
                output=None,
                sources=[],
            )
        ],
        files=(),
        now=datetime.datetime(2026, 8, 3, tzinfo=datetime.UTC),
    )

    assert transition.work_status is ExternalChannelWorkStatus.ACTIVE
    assert transition.work_id != finished.work_cycle_id
    assert current.tracker_visibility == "visible"
    assert len(transition.effects) == 1
    assert (
        transition.effects[0].provider.target.operation
        is ExternalChannelDeliveryOperation.PROGRESS_CREATE
    )
    assert current.projection_parts == []


async def _commit_ignore(
    work: ChannelWorkState,
    *,
    provider: ExternalChannelProvider,
) -> _CommitIgnoreResult:
    """Execute the canonical ignore mutator through repository authority checks."""
    binding = SimpleNamespace(
        id="binding-1",
        route_id="route-1",
        resource_id="resource-1",
    )
    route = SimpleNamespace(id="route-1", connection_id="connection-1")
    connection = SimpleNamespace(
        id="connection-1",
        provider=provider,
        app_mode=ExternalChannelAppMode.SINGLE,
        encrypted_credentials="ciphertext",
        provider_tenant_id=(
            "T1" if provider is ExternalChannelProvider.SLACK else "111"
        ),
        capabilities=None,
        provider_config=(
            None
            if provider is ExternalChannelProvider.SLACK
            else {
                "provider": "discord",
                "target_guild_id": "111",
                "thread_auto_archive_duration_minutes": 1440,
            }
        ),
    )
    agent = SimpleNamespace(
        id="agent-1",
        workspace_id="workspace-1",
        name="Agent",
        avatar=None,
    )
    resource = SimpleNamespace(
        id="resource-1",
        labels=(
            {
                "channel_id": "C1",
                "conversation_scope": "parent_channel",
            }
            if provider is ExternalChannelProvider.SLACK
            else {
                "guild_id": "111",
                "parent_channel_id": "333",
                "conversation_scope": "parent_channel",
            }
        ),
    )
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
        session,
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
    return _CommitIgnoreResult(
        transition=transition,
        work=current,
        update=state_store.update,
    )


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
@pytest.mark.parametrize(
    "provider",
    [ExternalChannelProvider.SLACK, ExternalChannelProvider.DISCORD],
)
async def test_ignore_finishes_active_work_and_deletes_present_tracker(
    statuses: tuple[ExternalChannelWorkTaskStatus, ...],
    provider: ExternalChannelProvider,
) -> None:
    """Ignore finishes Work and deletes only this binding's visible Tracker."""
    provider_message_key = (
        "slack:C1:123.456"
        if provider is ExternalChannelProvider.SLACK
        else "discord:111:555"
    )
    projection = _part(
        status=ExternalChannelWorkProjectionStatus.PRESENT,
        provider_message_key=provider_message_key,
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

    transition, updated, update = await _commit_ignore(work, provider=provider)

    assert transition.work_status is ExternalChannelWorkStatus.FINISHED
    assert len(transition.effects) == 1
    effect = transition.effects[0]
    assert (
        effect.provider.target.operation
        is ExternalChannelDeliveryOperation.PROGRESS_DELETE
    )
    assert effect.provider.target.binding_id == "binding-1"
    assert effect.provider.target.provider is provider
    assert effect.provider.target.request_payload["provider_message_key"] == (
        provider_message_key
    )
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


@pytest.mark.parametrize(
    "provider",
    [ExternalChannelProvider.SLACK, ExternalChannelProvider.DISCORD],
)
async def test_ignore_without_present_tracker_has_no_provider_effect(
    provider: ExternalChannelProvider,
) -> None:
    """Missing or terminal projection state creates no cleanup attempt."""
    work = _work(
        desired=True,
        projection_parts=[
            _part(
                status=ExternalChannelWorkProjectionStatus.DELETED,
                provider_message_key=None,
            ),
            _part(
                status=ExternalChannelWorkProjectionStatus.FAILED,
                provider_message_key="stale-provider-key",
                part_ordinal=1,
            ),
        ],
    )

    transition, updated, update = await _commit_ignore(work, provider=provider)

    assert transition.work_status is ExternalChannelWorkStatus.FINISHED
    assert transition.effects == ()
    assert updated.desired_progress is None
    update.assert_awaited_once()


async def test_direct_effect_revalidation_ignores_connection_health_status() -> None:
    """Post-commit effect authority is independent from ingress health."""

    class QueryCaptured(Exception):
        pass

    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=QueryCaptured())
    repository = ExternalChannelWorkRepository()
    effect = ChannelActionEffectPlan(
        provider=make_provider_effect_plan("direct-effect"),
        part=0,
        work_cycle_id="work-1",
        expected_desired_progress_revision=None,
    )

    with pytest.raises(QueryCaptured):
        await repository.revalidate_direct_effect(
            session,
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
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=request)
    session.flush = AsyncMock()
    repository = ExternalChannelWorkRepository()
    plan = make_provider_effect_plan("access-control")
    repository.prepare_direct_control = AsyncMock(return_value=plan)

    first = await repository.prepare_access_control_create(
        session,
        access_request_id="access-request-1",
        connection_id="connection-1",
        resource_id="resource-1",
        route_id="route-1",
        binding_id=None,
        request_payload={"access_request_id": "access-request-1"},
        operation_seed="access-request:access-request-1",
    )
    second = await repository.prepare_access_control_create(
        session,
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
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=resource)
    session.flush = AsyncMock()
    repository = ExternalChannelWorkRepository()

    first = await repository.record_discord_delivery_channel(
        session,
        resource_id="resource-1",
        delivery_channel_id="444",
        initial_thread_title="Test agent",
    )
    second = await repository.record_discord_delivery_channel(
        session,
        resource_id="resource-1",
        delivery_channel_id="555",
        initial_thread_title="Another title",
    )

    assert first == "444"
    assert second == "444"
    assert resource.labels["delivery_channel_id"] == "444"
    assert resource.labels[DISCORD_INITIAL_THREAD_TITLE_LABEL] == "Test agent"
    session.flush.assert_awaited_once()
