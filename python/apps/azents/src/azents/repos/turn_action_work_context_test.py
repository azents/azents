"""Terminal operation coordinators cannot strand carried work or later input."""

from typing import Literal

import pytest
from azcommon.datetime import tznow

from azents.core.enums import (
    ActionExecutionStatus,
    AgentRunStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.mailbox_data import (
    AgentRemoveGitWorktreeContinuationResult,
    GoalContinuationMailboxPayload,
    MailboxItemCreate,
    MailboxPresentationItem,
    TurnActionContinuationMailboxPayload,
)
from azents.core.work_context import WorkContext
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.work_context import (
    continuation_work_context,
    resolve_continuation_work_context,
)
from azents.services.mailbox_test import (
    _create_buffer,
    _create_fixture,
    _mailbox_item_service,
)


def _continuation(
    origin: str, predecessor: str
) -> TurnActionContinuationMailboxPayload:
    return TurnActionContinuationMailboxPayload(
        type="turn_action_continuation",
        items=[
            MailboxPresentationItem(
                item_key="turn_action_continuation:0",
                presentation_kind="turn_action_continuation",
            )
        ],
        bridge_identity="bridge-exact-origin",
        action_execution_id="operation-completed",
        originating_run_id=origin,
        predecessor_run_id=predecessor,
        terminal_status=ActionExecutionStatus.COMPLETED,
        reason_code=None,
        failure_summary=None,
        cancellation_summary=None,
        result=AgentRemoveGitWorktreeContinuationResult(
            type="agent_remove_git_worktree",
            worktree_path="/workspace/completed",
            preserved_branch_name="preserved",
            force=False,
            dirty_content_discarded=False,
            retry_guidance=None,
        ),
    )


@pytest.mark.parametrize(
    "predecessor_status", [AgentRunStatus.CANCELLED, AgentRunStatus.COMPLETED]
)
async def test_operation_only_bridge_carries_origin_and_unblocks_following_input(
    rdb_session_manager: SessionManager[WriteSession],
    predecessor_status: AgentRunStatus,
) -> None:
    """An already-completed operation resumes without repeating its side effect."""
    session_id, user_id = await _create_fixture(
        rdb_session_manager, f"bridge-origin-{predecessor_status.value}"
    )
    runs = AgentRunRepository()
    context = WorkContext(
        scheduled_cycle_ids=(), routine_executions=(), unrelated_input=True
    )
    async with rdb_session_manager() as session:
        origin = await runs.create_pending(
            session,
            session_id=session_id,
            parent_agent_run_id=None,
            work_context=context,
        )
        await runs.mark_terminal(
            session, origin.id, AgentRunStatus.COMPLETED, ended_at=tznow()
        )
        predecessor = await runs.create_pending(
            session,
            session_id=session_id,
            parent_agent_run_id=None,
            work_context=WorkContext.empty(),
        )
        await runs.mark_terminal(
            session, predecessor.id, predecessor_status, ended_at=tznow()
        )
        target = await runs.create_pending(
            session,
            session_id=session_id,
            parent_agent_run_id=None,
            work_context=WorkContext.empty(),
        )
        payload = _continuation(origin.id, predecessor.id)
        item = await MailboxRepository().create(
            session,
            MailboxItemCreate(
                session_id=session_id,
                kind=MailboxItemKind.TURN_ACTION_CONTINUATION,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
                sender_user_id=None,
                order_group=None,
                order_sequence=0,
                content="",
                metadata={},
                idempotency_key="turn_action_continuation:operation-completed",
                action=None,
                attachments=[],
                file_parts=[],
                payload=payload,
            ),
        )
        stored = await session.read_session.get(RDBMailboxItem, item.id)
        assert stored is not None
        assert await continuation_work_context(session, item=stored) == context
    following = await _create_buffer(
        rdb_session_manager,
        session_id=session_id,
        user_id=user_id,
        content="Preserve the later request",
        model_target_label="default",
        reasoning_effort=None,
    )
    service = _mailbox_item_service(rdb_session_manager)
    promoted = await service.flush_session_mailbox_items(
        session_id=session_id,
        owner_generation=0,
        model="gpt-5.4",
        required_inference_profile=None,
        expected_buffer_id=item.id,
        prepared_inference_state=None,
        profile_resolution_failure=None,
        active_run_id=target.id,
    )
    assert promoted.deleted_buffer_ids == [item.id]
    async with rdb_session_manager() as session:
        current = await runs.get_by_id(session, target.id)
        assert current is not None and current.work_context == context
        assert await MailboxRepository().get_by_id(session, item.id) is None
        assert await MailboxRepository().get_by_id(session, following) is not None
    later = await service.flush_session_mailbox_items(
        session_id=session_id,
        owner_generation=0,
        model="gpt-5.4",
        required_inference_profile=None,
        expected_buffer_id=following,
        prepared_inference_state=None,
        profile_resolution_failure=None,
        active_run_id=target.id,
    )
    assert later.deleted_buffer_ids == [following]


async def test_cancelled_ordinary_continuation_does_not_gain_bridge_exception(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """The bridge coordinator exception never weakens ordinary source authority."""
    session_id, _ = await _create_fixture(
        rdb_session_manager, "ordinary-cancelled-source"
    )
    runs = AgentRunRepository()
    async with rdb_session_manager() as session:
        source = await runs.create_pending(
            session,
            session_id=session_id,
            parent_agent_run_id=None,
            work_context=WorkContext.empty(),
        )
        await runs.mark_terminal(
            session, source.id, AgentRunStatus.CANCELLED, ended_at=tznow()
        )
        item = RDBMailboxItem(
            session_id=session_id,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            sender_user_id=None,
            idempotency_key="cancelled-ordinary",
            kind=MailboxItemKind.GOAL_CONTINUATION,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            payload=GoalContinuationMailboxPayload(
                type="goal_continuation",
                source_run_id=source.id,
                items=[
                    MailboxPresentationItem(
                        item_key="goal", presentation_kind="goal_continuation"
                    )
                ],
            ).model_dump(mode="json"),
            requested_enabled_execution_options=[],
        )
        assert await continuation_work_context(session, item=item) is None


@pytest.mark.parametrize(
    "invalid",
    [
        "cancelled-origin",
        "foreign-origin",
        "missing-origin",
        "pending-predecessor",
        "running-predecessor",
        "started-cancelled-predecessor",
        "foreign-predecessor",
        "missing-predecessor",
        "reversed-order",
    ],
)
async def test_bridge_rejects_invalid_work_provenance(
    rdb_session_manager: SessionManager[WriteSession],
    invalid: Literal[
        "cancelled-origin",
        "foreign-origin",
        "missing-origin",
        "pending-predecessor",
        "running-predecessor",
        "started-cancelled-predecessor",
        "foreign-predecessor",
        "missing-predecessor",
        "reversed-order",
    ],
) -> None:
    """A cancelled coordinator does not authorize missing or unrelated work."""
    session_id, _ = await _create_fixture(rdb_session_manager, f"invalid-{invalid}")
    foreign_id, _ = await _create_fixture(rdb_session_manager, f"foreign-{invalid}")
    runs = AgentRunRepository()
    async with rdb_session_manager() as session:
        origin = await runs.create_pending(
            session,
            session_id=foreign_id if invalid == "foreign-origin" else session_id,
            parent_agent_run_id=None,
            work_context=WorkContext.empty(),
        )
        await runs.mark_terminal(
            session,
            origin.id,
            AgentRunStatus.CANCELLED
            if invalid == "cancelled-origin"
            else AgentRunStatus.COMPLETED,
            ended_at=tznow(),
        )
        predecessor = await runs.create_pending(
            session,
            session_id=foreign_id if invalid == "foreign-predecessor" else session_id,
            parent_agent_run_id=None,
            work_context=WorkContext.empty(),
        )
        if invalid in {"running-predecessor", "started-cancelled-predecessor"}:
            await runs.activate_pending(
                session,
                run_id=predecessor.id,
                activated_at=tznow(),
                requested_model_target_label="default",
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
            )
        if invalid not in {"pending-predecessor", "running-predecessor"}:
            await runs.mark_terminal(
                session, predecessor.id, AgentRunStatus.CANCELLED, ended_at=tznow()
            )
        payload = _continuation(
            "missing" if invalid == "missing-origin" else origin.id,
            "missing" if invalid == "missing-predecessor" else predecessor.id,
        )
        if invalid == "reversed-order":
            payload = _continuation(predecessor.id, origin.id)
            await runs.mark_terminal(
                session, predecessor.id, AgentRunStatus.COMPLETED, ended_at=tznow()
            )
        assert (
            await resolve_continuation_work_context(
                session, session_id=session_id, payload=payload
            )
            is None
        )
