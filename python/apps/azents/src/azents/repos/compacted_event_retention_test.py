"""PostgreSQL integration coverage for first-displacement event retention."""

import dataclasses
import datetime

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from azents.api.admin.system.v1.data import CompactedEventRetentionUpdateRequest
from azents.core.archived_session_retention_data import RetentionRevisionConflict
from azents.core.enums import AgentRunStatus, EventKind
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_run_input_event import RDBAgentRunInputEvent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.compacted_event_retention import CompactedEventRetentionOperations
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.services.archived_session_retention_test import _create_root, _create_user

NOW = datetime.datetime(2026, 10, 13, 12, tzinfo=datetime.UTC)
FIRST_COMPACTION = NOW - datetime.timedelta(days=70)
SECOND_COMPACTION = NOW - datetime.timedelta(days=1)


@dataclasses.dataclass(frozen=True)
class _History:
    session_id: str
    user_id: str
    old_id: str
    first_summary_id: str
    recent_id: str
    head_id: str
    tail_id: str


async def _create_history(manager: SessionManager[WriteSession]) -> _History:
    async with manager() as session:
        session_id = await _create_root(session, suffix="compacted")
        user_id = await _create_user(session, "compacted")
        rows: list[RDBEvent] = []
        for kind, created_at in (
            (EventKind.USER_MESSAGE, NOW - datetime.timedelta(days=120)),
            (EventKind.COMPACTION_SUMMARY, FIRST_COMPACTION),
            (EventKind.USER_MESSAGE, NOW - datetime.timedelta(days=90)),
            (EventKind.COMPACTION_SUMMARY, SECOND_COMPACTION),
            (EventKind.USER_MESSAGE, NOW),
        ):
            row = RDBEvent(session_id=session_id, kind=kind, payload={})
            row.created_at = created_at
            session.write_session.add(row)
            await session.write_session.flush()
            rows.append(row)
        repository = SessionExecutionRecordRepository()
        await repository.move_model_input_head(session, session_id, rows[1].id)
        await repository.move_model_input_head(session, session_id, rows[3].id)
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(model_file_gc_cursor_event_id=rows[3].id)
        )
        return _History(
            session_id,
            user_id,
            rows[0].id,
            rows[1].id,
            rows[2].id,
            rows[3].id,
            rows[4].id,
        )


def _operations(
    manager: SessionManager[WriteSession],
) -> CompactedEventRetentionOperations:
    return CompactedEventRetentionOperations(
        session_manager=manager,
        settings_repository=ArchivedSessionRetentionRepository(),
    )


async def _set_policy(
    manager: SessionManager[WriteSession], *, user_id: str, days: int | None
) -> None:
    async with manager() as session:
        current = await ArchivedSessionRetentionRepository().get_settings(session)
    await _operations(manager).update_settings(
        expected_revision=current.revision, retention_days=days, user_id=user_id
    )


async def _ids(manager: SessionManager[WriteSession], session_id: str) -> list[str]:
    async with manager() as session:
        return list(
            await session.read_session.scalars(
                sa.select(RDBEvent.id)
                .where(RDBEvent.session_id == session_id)
                .order_by(RDBEvent.id)
            )
        )


async def test_first_displacement_survives_repeated_compaction(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    history = await _create_history(rdb_session_manager)
    async with rdb_session_manager() as session:
        rows = (
            await session.read_session.execute(
                sa.select(RDBEvent.id, RDBEvent.compacted_at).where(
                    RDBEvent.session_id == history.session_id
                )
            )
        ).all()
        timestamps = {event_id: compacted_at for event_id, compacted_at in rows}
        assert timestamps[history.old_id] == FIRST_COMPACTION
        assert timestamps[history.first_summary_id] == SECOND_COMPACTION
        assert timestamps[history.recent_id] == SECOND_COMPACTION
        assert timestamps[history.head_id] is None
        assert timestamps[history.tail_id] is None


async def test_unlimited_default_and_independent_policy_cas(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    history = await _create_history(rdb_session_manager)
    operations = _operations(rdb_session_manager)
    async with rdb_session_manager() as session:
        initial = await ArchivedSessionRetentionRepository().get_settings(session)
    assert initial.compacted_event_retention_days is None
    result = await operations.cleanup_once(now=NOW, limit=100)
    assert result.unlimited and result.deleted_count == 0
    updated = await operations.update_settings(
        expected_revision=initial.revision, retention_days=60, user_id=history.user_id
    )
    assert (
        updated.archived_session_retention_days
        == initial.archived_session_retention_days
    )
    assert updated.compacted_event_retention_days == 60
    assert updated.revision == initial.revision + 1
    with pytest.raises(RetentionRevisionConflict):
        await operations.update_settings(
            expected_revision=initial.revision,
            retention_days=0,
            user_id=history.user_id,
        )
    assert len(await _ids(rdb_session_manager, history.session_id)) == 5


async def test_ttl_uses_compaction_age_and_preserves_current_context(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    history = await _create_history(rdb_session_manager)
    await _set_policy(rdb_session_manager, user_id=history.user_id, days=60)
    result = await _operations(rdb_session_manager).cleanup_once(now=NOW, limit=100)
    assert result.deleted_count == 1
    assert await _ids(rdb_session_manager, history.session_id) == [
        history.first_summary_id,
        history.recent_id,
        history.head_id,
        history.tail_id,
    ]
    again = await _operations(rdb_session_manager).cleanup_once(now=NOW, limit=100)
    assert again.deleted_count == 0


async def test_zero_ttl_is_bounded_and_waits_for_file_gc(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    history = await _create_history(rdb_session_manager)
    await _set_policy(rdb_session_manager, user_id=history.user_id, days=0)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == history.session_id)
            .values(model_file_gc_cursor_event_id=None)
        )
    operations = _operations(rdb_session_manager)
    blocked = await operations.cleanup_once(now=NOW, limit=1)
    assert blocked.deleted_count == 0
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == history.session_id)
            .values(model_file_gc_cursor_event_id=history.head_id)
        )
    first = await operations.cleanup_once(now=NOW, limit=1)
    assert first.deleted_count == 1 and first.limit_reached
    second = await operations.cleanup_once(now=NOW, limit=100)
    assert second.deleted_count == 2 and not second.limit_reached
    assert await _ids(rdb_session_manager, history.session_id) == [
        history.head_id,
        history.tail_id,
    ]


@pytest.mark.parametrize("run_status", [AgentRunStatus.PENDING, AgentRunStatus.RUNNING])
async def test_active_run_inputs_are_protected(
    rdb_session_manager: SessionManager[WriteSession], run_status: AgentRunStatus
) -> None:
    history = await _create_history(rdb_session_manager)
    await _set_policy(rdb_session_manager, user_id=history.user_id, days=60)
    async with rdb_session_manager() as session:
        run = await AgentRunRepository().create(
            session,
            AgentRunCreate(
                session_id=history.session_id,
                scheduled_task_cycle_id=None,
                parent_agent_run_id=None,
                status=run_status,
            ),
        )
        session.write_session.add(
            RDBAgentRunInputEvent(
                agent_run_id=run.id, event_id=history.old_id, input_order=0
            )
        )
    operations = _operations(rdb_session_manager)
    assert (await operations.cleanup_once(now=NOW, limit=100)).deleted_count == 0
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRun)
            .where(RDBAgentRun.id == run.id)
            .values(status=AgentRunStatus.COMPLETED)
        )
    assert (await operations.cleanup_once(now=NOW, limit=100)).deleted_count == 1


@pytest.mark.parametrize("value", [-1, 1.5, True, "60", 2_147_483_648])
def test_invalid_policy_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        CompactedEventRetentionUpdateRequest.model_validate(
            {"expected_revision": 1, "compacted_event_retention_days": value}
        )


async def test_exact_expiration_boundary_and_switch_back_to_unlimited(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    history = await _create_history(rdb_session_manager)
    await _set_policy(rdb_session_manager, user_id=history.user_id, days=60)
    operations = _operations(rdb_session_manager)
    expires_at = FIRST_COMPACTION + datetime.timedelta(days=60)
    before = await operations.cleanup_once(
        now=expires_at - datetime.timedelta(microseconds=1), limit=100
    )
    assert before.deleted_count == 0
    exact = await operations.cleanup_once(now=expires_at, limit=100)
    assert exact.deleted_count == 1
    await _set_policy(rdb_session_manager, user_id=history.user_id, days=None)
    later = await operations.cleanup_once(
        now=NOW + datetime.timedelta(days=200), limit=100
    )
    assert later.unlimited and later.deleted_count == 0
    assert len(await _ids(rdb_session_manager, history.session_id)) == 4


@pytest.mark.parametrize("head_id", [None, "f" * 32])
async def test_missing_current_head_preserves_history(
    rdb_session_manager: SessionManager[WriteSession],
    head_id: str | None,
) -> None:
    history = await _create_history(rdb_session_manager)
    await _set_policy(rdb_session_manager, user_id=history.user_id, days=0)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == history.session_id)
            .values(model_input_head_event_id=head_id)
        )
    result = await _operations(rdb_session_manager).cleanup_once(now=NOW, limit=100)
    assert result.deleted_count == 0
