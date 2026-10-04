"""Historical Memory source repository tests."""

import dataclasses
import datetime
import hashlib

import pytest
import sqlalchemy as sa
from pydantic import TypeAdapter, ValidationError

from azents.core.agent import SelectableModelCandidate, SelectableModelOption
from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
    EventKind,
    WorkspaceUserRole,
)
from azents.core.historical_memory import (
    HistoricalMemoryCompletion,
    HistoricalMemoryFailure,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.json_value import JSONValue
from azents.core.model_operation import (
    ModelOperationKind,
    ModelOperationSnapshot,
    build_model_operation,
)
from azents.engine.events.types import UserMessagePayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.session_lifecycle_finalizer import (
    SessionLifecycleFinalizerRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_selection_dict,
    make_test_model_settings,
    make_test_selectable_model_option_dicts,
)

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
_PAYLOAD_ADAPTER: TypeAdapter[dict[str, JSONValue]] = TypeAdapter(dict[str, JSONValue])


@dataclasses.dataclass(frozen=True)
class _SourceFixture:
    """Persisted source identities used by repository tests."""

    workspace_id: str
    agent_id: str
    session_id: str
    event_id: str
    associated_user_id: str | None


async def _create_source(
    session: WriteSession,
    *,
    slug: str,
    activity_at: datetime.datetime,
    product_mode: AgentSessionProductMode = AgentSessionProductMode.TEAM,
    membership: bool = True,
    memory_enabled: bool = True,
    run_state: AgentSessionRunState = AgentSessionRunState.IDLE,
) -> _SourceFixture:
    """Persist one root Session and a visible source event."""
    workspace = RDBWorkspace(name=slug, handle=slug)
    session.write_session.add(workspace)
    await session.write_session.flush()

    model_selection = make_test_model_selection_dict()
    agent = RDBAgent(
        workspace_id=workspace.id,
        name=slug,
        model_selection=model_selection,
        lightweight_model_selection=model_selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
        memory_enabled=memory_enabled,
    )
    session.write_session.add(agent)
    await session.write_session.flush()
    runtime = RDBAgentRuntime(workspace_id=workspace.id, agent_id=agent.id)
    runtime.workspace_path = "/workspace/agent"
    session.write_session.add(runtime)
    await session.write_session.flush()

    associated_user_id: str | None = None
    if product_mode is AgentSessionProductMode.USER:
        user = await UserRepository().create(
            session,
            UserCreate(email=f"{slug}@example.test"),
        )
        associated_user_id = user.id
        if membership:
            session.write_session.add(
                RDBWorkspaceUser(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    name=slug,
                    role=WorkspaceUserRole.MEMBER,
                )
            )
            await session.write_session.flush()

    source = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace.id,
            product_mode=product_mode,
            associated_user_id=associated_user_id,
            agent_id=agent.id,
            title=f"{slug} title",
        ),
    )
    source_row = await session.read_session.get(RDBAgentSession, source.id)
    assert source_row is not None
    source_row.last_activity_at = activity_at
    source_row.run_state = run_state

    event = RDBEvent(
        session_id=source.id,
        kind=EventKind.USER_MESSAGE,
        payload=_PAYLOAD_ADAPTER.validate_python(
            UserMessagePayload(
                sender_user_id=associated_user_id,
                content=f"{slug} source",
            ).model_dump(mode="json")
        ),
    )
    event.id = hashlib.sha256(slug.encode()).hexdigest()[:32]
    session.write_session.add(event)
    await session.write_session.flush()
    return _SourceFixture(
        workspace_id=workspace.id,
        agent_id=agent.id,
        session_id=source.id,
        event_id=event.id,
        associated_user_id=associated_user_id,
    )


def _operation() -> ModelOperationSnapshot:
    """Build one persisted Historical Memory Lightweight operation."""
    selection = make_test_model_selection(integration_id="i" * 32)
    option = SelectableModelOption(
        label="lightweight",
        candidates=[
            SelectableModelCandidate(
                model_selection=selection,
                settings=make_test_model_settings(),
            )
        ],
        subagent_enabled=True,
        subagent_guidance=None,
    )
    return build_model_operation(
        option=option,
        profile=RequestedInferenceProfile(
            model_target_label="lightweight",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        kind=ModelOperationKind.HISTORICAL_MEMORY,
        operation_id="o" * 32,
        recorded_at=_NOW,
    )


def test_failure_progress_rejects_non_historical_model_operation() -> None:
    """Source-owned progress cannot persist another model-operation kind."""
    foreground = _operation().model_copy(update={"kind": ModelOperationKind.FOREGROUND})

    with pytest.raises(ValidationError, match="historical_memory operation"):
        HistoricalMemoryFailure(
            attempted_at=_NOW,
            next_retry_at=_NOW + datetime.timedelta(minutes=5),
            failure_code="provider_unavailable",
            model_operation_state=foreground,
        )


async def test_explicit_agent_admission_leaves_other_agents_unmodified(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A scoped sampler executes production admission without cross-test writes."""
    async with rdb_session_manager() as session:
        selected = await _create_source(
            session,
            slug="historical-sample-selected",
            activity_at=_NOW - datetime.timedelta(hours=8),
        )
        unrelated = await _create_source(
            session,
            slug="historical-sample-unrelated",
            activity_at=_NOW - datetime.timedelta(hours=8),
        )
        await session.write_session.commit()
    repository = HistoricalMemoryRepository(session_manager=rdb_session_manager)
    admitted = await repository.admit_eligible_sources(
        agent_id=selected.agent_id,
        now=_NOW,
        oldest_activity_at=_NOW - datetime.timedelta(days=10),
        inactive_before=_NOW - datetime.timedelta(hours=6),
        limit=500,
    )
    assert admitted == [selected.session_id]
    assert await repository.get(unrelated.session_id) is None


async def test_admission_applies_window_execution_and_user_membership_authority(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """First admission accepts only inactive authorized idle roots in the window."""
    async with rdb_session_manager() as session:
        eligible = await _create_source(
            session,
            slug="hm-eligible",
            activity_at=_NOW - datetime.timedelta(hours=7),
        )
        member = await _create_source(
            session,
            slug="hm-user-member",
            activity_at=_NOW - datetime.timedelta(hours=8),
            product_mode=AgentSessionProductMode.USER,
        )
        await _create_source(
            session,
            slug="hm-too-recent",
            activity_at=_NOW - datetime.timedelta(hours=5),
        )
        await _create_source(
            session,
            slug="hm-too-old",
            activity_at=_NOW - datetime.timedelta(days=11),
        )
        await _create_source(
            session,
            slug="hm-running",
            activity_at=_NOW - datetime.timedelta(hours=7),
            run_state=AgentSessionRunState.RUNNING,
        )
        await _create_source(
            session,
            slug="hm-disabled",
            activity_at=_NOW - datetime.timedelta(hours=7),
            memory_enabled=False,
        )
        await _create_source(
            session,
            slug="hm-user-removed",
            activity_at=_NOW - datetime.timedelta(hours=7),
            product_mode=AgentSessionProductMode.USER,
            membership=False,
        )

    repository = HistoricalMemoryRepository(
        session_manager=rdb_session_manager,
    )
    admitted = await repository.admit_eligible_sources(
        agent_id=None,
        now=_NOW,
        oldest_activity_at=_NOW - datetime.timedelta(days=10),
        inactive_before=_NOW - datetime.timedelta(hours=6),
        limit=20,
    )

    assert admitted == [member.session_id, eligible.session_id]
    assert (
        await repository.admit_eligible_sources(
            agent_id=None,
            now=_NOW,
            oldest_activity_at=_NOW - datetime.timedelta(days=10),
            inactive_before=_NOW - datetime.timedelta(hours=6),
            limit=20,
        )
        == []
    )
    eligible_due = await repository.list_due_for_agent(
        agent_id=eligible.agent_id,
        now=_NOW,
        inactive_before=_NOW - datetime.timedelta(hours=6),
        limit=10,
    )
    assert len(eligible_due) == 1
    assert eligible_due[0].source_session_id == eligible.session_id
    assert eligible_due[0].source_tail_event_id == eligible.event_id


async def test_admitted_source_remains_due_beyond_first_admission_age_window(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """An admitted retry or first result is not dropped after ten days."""
    async with rdb_session_manager() as session:
        source = await _create_source(
            session,
            slug="hm-age-free",
            activity_at=_NOW - datetime.timedelta(days=20),
        )
        session.write_session.add(
            RDBHistoricalMemorySource(
                source_session_id=source.session_id,
                admitted_at=_NOW - datetime.timedelta(days=12),
            )
        )

    repository = HistoricalMemoryRepository(
        session_manager=rdb_session_manager,
    )
    due = await repository.list_due_for_agent(
        agent_id=source.agent_id,
        now=_NOW,
        inactive_before=_NOW - datetime.timedelta(hours=6),
        limit=10,
    )

    assert [item.source_session_id for item in due] == [source.session_id]


async def test_failure_retains_prior_result_and_publish_resets_progress(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Refresh failure is bounded progress while empty success is still complete."""
    async with rdb_session_manager() as session:
        source = await _create_source(
            session,
            slug="hm-progress",
            activity_at=_NOW - datetime.timedelta(hours=7),
        )
        session.write_session.add(
            RDBHistoricalMemorySource(
                source_session_id=source.session_id,
                admitted_at=_NOW - datetime.timedelta(hours=1),
            )
        )

    repository = HistoricalMemoryRepository(
        session_manager=rdb_session_manager,
    )
    operation = _operation()
    async with rdb_session_manager() as session:
        admission = await repository.lock_preparation_admission_in_session(
            session,
            source_session_id=source.session_id,
            attempted_at=_NOW,
            inactive_before=_NOW - datetime.timedelta(hours=6),
        )
        assert admission is not None
        assert await repository.lock_preparation_membership_in_session(
            session,
            admission,
        )
        started = await repository.persist_preparation_operation_in_session(
            session,
            admission,
            attempted_at=_NOW,
            operation=operation,
        )
        await session.write_session.commit()
    assert started is not None
    assert started.model_operation_state == operation
    assert started.source_activity_at == _NOW - datetime.timedelta(hours=7)
    assert started.source_tail_event_id == source.event_id

    failed = await repository.record_failure(
        source_session_id=source.session_id,
        failure=HistoricalMemoryFailure(
            attempted_at=_NOW,
            next_retry_at=_NOW + datetime.timedelta(minutes=5),
            failure_code="provider_unavailable",
            model_operation_state=operation,
        ),
    )
    assert failed is not None
    assert failed.failure_count == 1
    assert failed.next_retry_at == _NOW + datetime.timedelta(minutes=5)

    first = await repository.publish_completed(
        source_session_id=source.session_id,
        completion=HistoricalMemoryCompletion(
            source_activity_at=_NOW - datetime.timedelta(hours=7),
            source_tail_event_id=source.event_id,
            prepared_at=_NOW + datetime.timedelta(minutes=1),
            source_title_snapshot="First title",
            summary="Prior useful result",
        ),
    )
    assert first is not None
    assert first.summary == "Prior useful result"
    assert first.failure_count == 0
    assert first.next_retry_at is None
    assert first.model_operation_state is None

    refresh_failure = await repository.record_failure(
        source_session_id=source.session_id,
        failure=HistoricalMemoryFailure(
            attempted_at=_NOW + datetime.timedelta(hours=8),
            next_retry_at=_NOW + datetime.timedelta(hours=9),
            failure_code="invalid_output",
            model_operation_state=operation,
        ),
    )
    assert refresh_failure is not None
    assert refresh_failure.summary == "Prior useful result"
    assert refresh_failure.completed_source_tail_event_id == source.event_id

    empty = await repository.publish_completed(
        source_session_id=source.session_id,
        completion=HistoricalMemoryCompletion(
            source_activity_at=_NOW + datetime.timedelta(hours=1),
            source_tail_event_id=source.event_id,
            prepared_at=_NOW + datetime.timedelta(hours=10),
            source_title_snapshot=None,
            summary="",
        ),
    )
    assert empty is not None
    assert empty.summary is None
    assert empty.failure_count == 0
    assert empty.last_failure_code is None
    assert empty.next_retry_at is None
    assert empty.model_operation_state is None


async def test_preparation_admission_rechecks_current_source_state_and_membership(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Preparation lock stages reject stale Session state and User membership."""
    async with rdb_session_manager() as session:
        running = await _create_source(
            session,
            slug="hm-begin-running",
            activity_at=_NOW - datetime.timedelta(hours=7),
            run_state=AgentSessionRunState.RUNNING,
        )
        recent = await _create_source(
            session,
            slug="hm-begin-recent",
            activity_at=_NOW - datetime.timedelta(hours=1),
        )
        disabled = await _create_source(
            session,
            slug="hm-begin-disabled",
            activity_at=_NOW - datetime.timedelta(hours=7),
            memory_enabled=False,
        )
        archived = await _create_source(
            session,
            slug="hm-begin-archived",
            activity_at=_NOW - datetime.timedelta(hours=7),
        )
        private = await _create_source(
            session,
            slug="hm-begin-private",
            activity_at=_NOW - datetime.timedelta(hours=7),
            product_mode=AgentSessionProductMode.USER,
            membership=False,
        )
        archived_row = await session.read_session.get(
            RDBAgentSession, archived.session_id
        )
        assert archived_row is not None
        archived_row.status = AgentSessionStatus.ARCHIVED
        for source in (running, recent, disabled, archived, private):
            session.write_session.add(
                RDBHistoricalMemorySource(
                    source_session_id=source.session_id,
                    admitted_at=_NOW,
                )
            )

    repository = HistoricalMemoryRepository(session_manager=rdb_session_manager)
    for source in (running, recent, archived):
        async with rdb_session_manager() as session:
            assert (
                await repository.lock_preparation_admission_in_session(
                    session,
                    source_session_id=source.session_id,
                    attempted_at=_NOW,
                    inactive_before=_NOW - datetime.timedelta(hours=6),
                )
                is None
            )
        stored = await repository.get(source.session_id)
        assert stored is not None
        assert stored.last_attempt_at is None
        assert stored.model_operation_state is None

    async with rdb_session_manager() as session:
        disabled_admission = await repository.lock_preparation_admission_in_session(
            session,
            source_session_id=disabled.session_id,
            attempted_at=_NOW,
            inactive_before=_NOW - datetime.timedelta(hours=6),
        )
        assert disabled_admission is not None

    async with rdb_session_manager() as session:
        private_admission = await repository.lock_preparation_admission_in_session(
            session,
            source_session_id=private.session_id,
            attempted_at=_NOW,
            inactive_before=_NOW - datetime.timedelta(hours=6),
        )
        assert private_admission is not None
        assert not await repository.lock_preparation_membership_in_session(
            session,
            private_admission,
        )


async def test_publication_reauthorizes_source_and_session_delete_cascades(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Archived roots cannot publish and purging a root removes source state."""
    async with rdb_session_manager() as session:
        source = await _create_source(
            session,
            slug="hm-publish-authority",
            activity_at=_NOW - datetime.timedelta(hours=7),
        )
        session.write_session.add(
            RDBHistoricalMemorySource(
                source_session_id=source.session_id,
                admitted_at=_NOW,
            )
        )
        source_row = await session.read_session.get(RDBAgentSession, source.session_id)
        assert source_row is not None
        source_row.status = AgentSessionStatus.ARCHIVED

    repository = HistoricalMemoryRepository(
        session_manager=rdb_session_manager,
    )
    denied = await repository.publish_completed(
        source_session_id=source.session_id,
        completion=HistoricalMemoryCompletion(
            source_activity_at=_NOW - datetime.timedelta(hours=7),
            source_tail_event_id=source.event_id,
            prepared_at=_NOW,
            source_title_snapshot=None,
            summary="must not publish",
        ),
    )
    assert denied is None
    stored = await repository.get(source.session_id)
    assert stored is not None
    assert stored.prepared_at is None
    assert stored.summary is None

    async with rdb_session_manager() as session:
        await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
            session,
            root_session_id=source.session_id,
            session_ids=[source.session_id],
        )

    assert await repository.get(source.session_id) is None


async def test_user_membership_loss_prevents_publication(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A private source is unavailable immediately after membership removal."""
    async with rdb_session_manager() as session:
        source = await _create_source(
            session,
            slug="hm-user-publish",
            activity_at=_NOW - datetime.timedelta(hours=7),
            product_mode=AgentSessionProductMode.USER,
        )
        session.write_session.add(
            RDBHistoricalMemorySource(
                source_session_id=source.session_id,
                admitted_at=_NOW,
            )
        )
        assert source.associated_user_id is not None
        await session.write_session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == source.workspace_id,
                RDBWorkspaceUser.user_id == source.associated_user_id,
            )
        )

    repository = HistoricalMemoryRepository(
        session_manager=rdb_session_manager,
    )
    assert (
        await repository.publish_completed(
            source_session_id=source.session_id,
            completion=HistoricalMemoryCompletion(
                source_activity_at=_NOW - datetime.timedelta(hours=7),
                source_tail_event_id=source.event_id,
                prepared_at=_NOW,
                source_title_snapshot=None,
                summary="must not publish",
            ),
        )
        is None
    )
