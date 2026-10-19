"""Internal judgment action state never becomes a public chat action projection."""

import pytest
from azcommon.result import Success
from pydantic import ValidationError

from azents.api.public.chat.v1.data import ActionExecutionResponse
from azents.core.enums import WorkspaceUserRole
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.routine.judgment_inbox_test import NOW, promote, repository, subject
from azents.services.chat.team_session_test import _service
from azents.services.chat_write_test import _create_user


async def test_internal_execution_is_retained_but_absent_from_public_live_state(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    scope = await subject(rdb_session_manager)
    admitted = await repository(rdb_session_manager).admit_tick(scope=scope, now=NOW)
    assert admitted is not None
    action = RoutineJudgmentAction.model_validate(admitted.mailbox_item.action)
    execution = await promote(
        rdb_session_manager,
        scope=scope,
        action=action,
        buffer_id=admitted.mailbox_item.id,
    )
    assert not execution.chat_visible
    async with rdb_session_manager() as session:
        user_id = await _create_user(
            session, f"routine-visibility-{scope.session_id}@example.com"
        )
        session.write_session.add(
            RDBWorkspaceUser(
                workspace_id=scope.workspace_id,
                user_id=user_id,
                name="Routine visibility fixture",
                role=WorkspaceUserRole.OWNER,
            )
        )
        await session.write_session.flush()
        persisted = await ActionExecutionRepository().list_projections_by_session_id(
            session,
            session_id=scope.session_id,
        )
        assert len(persisted) == 1 and persisted[0].execution.id == execution.id
    result = await _service(rdb_session_manager).operations.capture_live_state(
        scope.session_id,
        user_id=user_id,
    )
    assert isinstance(result, Success)
    assert result.value.action_executions == ()
    with pytest.raises(ValidationError):
        ActionExecutionResponse.from_domain(execution)
    schema = ActionExecutionResponse.model_json_schema()
    assert "routine_judgment" not in str(schema)
    assert "RoutineJudgmentAction" not in str(schema)
