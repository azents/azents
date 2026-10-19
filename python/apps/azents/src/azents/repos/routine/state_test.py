"""Real Toolkit State persistence preserves nullable checks and admitted identity."""

import dataclasses

import pytest

from azents.core.routine import RoutineUnavailable
from azents.core.routine_execution import RoutineCheckState
from azents.core.routine_execution_test import execution
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.persistence_test import _subject
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.toolkit_state import ToolkitStateConflictError, ToolkitStateRepository


async def test_check_and_execution_use_separate_cas_fences_in_existing_storage(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    repository = RoutineStateRepository(toolkit_states=ToolkitStateRepository())
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        empty = RoutineCheckState(
            last_tick_at=None,
            last_action_at=None,
            source_inputs=(),
            queued_judgment_id=None,
        )
        assert await repository.get_check(session, scope=scope) is None
        check = await repository.save_check(
            session, scope=scope, state=empty, expected_version=None
        )
        item = await repository.save_execution(
            session, scope=scope, state=execution(scope), expected_version=None
        )
        assert check.toolkit_state_id != item.toolkit_state_id
        assert await repository.get_check(session, scope=scope) == check
        assert (
            await repository.get_execution(session, scope=scope, routine_id="routine-a")
            == item
        )
        updated = await repository.save_check(
            session, scope=scope, state=empty, expected_version=check.version
        )
        assert updated.version == check.version + 1
        assert await repository.list_executions(session, scope=scope) == [item]
        with pytest.raises(ToolkitStateConflictError):
            await repository.save_check(
                session, scope=scope, state=empty, expected_version=check.version
            )
        assert (
            await repository.get_execution(session, scope=scope, routine_id="routine-a")
            == item
        )


async def test_admitted_snapshot_cannot_be_read_or_rewritten_under_another_owner(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    repository = RoutineStateRepository(toolkit_states=ToolkitStateRepository())
    async with rdb_session_manager() as session:
        scope = await _subject(session)
        item = execution(scope)
        await repository.save_execution(
            session, scope=scope, state=item, expected_version=None
        )
        foreign_session = dataclasses.replace(scope, session_id="foreign-session")
        assert (
            await repository.get_execution(
                session, scope=foreign_session, routine_id="routine-a"
            )
            is None
        )
        foreign_workspace = dataclasses.replace(scope, workspace_id="foreign-workspace")
        with pytest.raises(RoutineUnavailable, match="does not match"):
            await repository.get_execution(
                session, scope=foreign_workspace, routine_id="routine-a"
            )
        with pytest.raises(RoutineUnavailable, match="does not match"):
            await repository.save_execution(
                session, scope=foreign_workspace, state=item, expected_version=None
            )
