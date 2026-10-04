"""Ordered PostgreSQL action projection regression for completed Worker reads."""

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.action_execution_data import (
    ActionExecutionCreate,
    ActionExecutionEventCreate,
)
from azents.core.enums import ActionExecutionEventKind, ActionExecutionStatus
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.live_projection_authority_test import _create_session
from azents.repos.worker_executor_read_test import _Boundary, _reads


async def test_action_projections_keep_pending_running_and_progress_order(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    session_id = await _create_session(
        rdb_session_manager, handle="executor-read-actions"
    )
    actions = ActionExecutionRepository()
    async with rdb_session_manager() as session:
        created = []
        for index, status in enumerate(
            [
                ActionExecutionStatus.PENDING,
                ActionExecutionStatus.RUNNING,
                ActionExecutionStatus.COMPLETED,
            ]
        ):
            created.append(
                await actions.create(
                    session,
                    ActionExecutionCreate(
                        id=str(index + 1) * 32,
                        session_id=session_id,
                        mailbox_item_id=str(index + 4) * 32,
                        sender_user_id=None,
                        action_type="test_action",
                        action={"kind": "test"},
                        status=status,
                        owner_generation=0,
                    ),
                )
            )
        for content in ["first", "second"]:
            await actions.append_event(
                session,
                ActionExecutionEventCreate(
                    action_execution_id=created[0].id,
                    session_id=session_id,
                    kind=ActionExecutionEventKind.INFO,
                    step_key=None,
                    command_argv=None,
                    content=content,
                    exit_code=None,
                ),
            )
    boundary = _Boundary(rdb_session_manager)
    result = await _reads(
        boundary, agents=AgentRepository()
    ).action_execution_projections(session_id)
    assert [item.execution.id for item in result] == [created[0].id, created[1].id]
    assert [event.content for event in result[0].events] == ["first", "second"]
    assert len(boundary.opened) == 1
    boundary.closed()
