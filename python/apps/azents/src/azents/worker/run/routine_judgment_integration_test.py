"""Routine judgments enter the ordinary Run-loop action boundary without a turn."""

import asyncio
import dataclasses
import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon.result import Success

import azents.worker.run.executor as executor_module
from azents.core.action_execution_data import ActionExecution
from azents.core.enums import AgentRunStatus, MailboxItemKind, MailboxSchedulingMode
from azents.core.inference_profile import (
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.mailbox_data import MailboxItem
from azents.core.routine import RoutineScope
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.tools import TurnContext
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.engine.events.routine_judgment_test import _observation
from azents.engine.events.types import RoutineJudgmentPayload
from azents.engine.routine_judgment_context import (
    PrepareRoutineJudgmentContext,
    RoutineJudgmentContext,
    RoutineJudgmentHost,
)
from azents.engine.routine_judgment_context_test import request
from azents.engine.run.model_transport import InMemoryModelTransportState
from azents.engine.run.resolve import ResolvedInvokeInputProfile
from azents.repos.routine.judgment_inbox import RoutineJudgmentSettlement
from azents.services.mailbox import (
    OperationActionInput,
    PendingInputInferenceProfile,
    PromotedMailboxItems,
    TurnEffect,
)
from azents.services.routine.judgment import RoutineJudgmentService
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.worker.run.executor_test import (
    _action_execution,
    _executor,
    _message,
    _noop_dispatch_event,
    _PendingRun,
    _SessionLifecycle,
)
from azents.worker.session.supervisor import ToolAdmissionBarrier


class _ContextCaptured(RuntimeError):
    """Stop this fixture after the resumed-context boundary has been observed."""


def _judgment_buffer(
    execution: ActionExecution, action: RoutineJudgmentAction
) -> MailboxItem:
    return MailboxItem(
        id=execution.mailbox_item_id,
        session_id=execution.session_id,
        kind=MailboxItemKind.ACTION_MESSAGE,
        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
        sender_user_id=None,
        order_group="1" * 32,
        order_sequence=0,
        content="",
        idempotency_key="routine-judgment:neutral-test",
        metadata={},
        action=action.model_dump(mode="json"),
        attachments=[],
        file_parts=[],
        created_at=datetime.datetime.now(datetime.UTC),
    )


@pytest.mark.parametrize(
    "capture_context,resumed", [(False, False), (True, False), (True, True)]
)
async def test_no_action_judgment_completes_host_without_foreground_preparation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    capture_context: bool,
    resumed: bool,
) -> None:
    selection = make_test_model_selection(
        model_identifier="frozen-ordinary-candidate" if resumed else "gpt-test"
    )
    recoverable = (
        _PendingRun(
            status=AgentRunStatus.RUNNING,
            resolved_model_selection=selection,
            effective_context_window_tokens=128_000,
            effective_auto_compaction_threshold_tokens=102_400,
        )
        if resumed
        else None
    )
    lifecycle = _SessionLifecycle(recoverable_run=recoverable)
    executor = _executor(session_lifecycle=lifecycle)
    broadcast = Mock(spec=executor_module.BaseWebSocketBroadcast)
    executor.broadcast = broadcast
    original_inference = executor.test_session_state.inference_state
    observation = _observation().model_copy(update={"session_id": "session-001"})
    assert isinstance(observation.payload, RoutineJudgmentPayload)
    action = RoutineJudgmentAction(judgment_id=observation.payload.judgment_id)
    execution = _action_execution().model_copy(
        update={"action_type": action.type, "action": action.model_dump(mode="json")}
    )
    buffer = _judgment_buffer(execution, action)
    available = True

    async def peek(session_id: str) -> PendingInputInferenceProfile:
        assert session_id == execution.session_id
        return PendingInputInferenceProfile(
            mailbox_item_id=buffer.id if available else None,
            requires_inference=False,
            exists=available,
            requested_inference_profile=None,
        )

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        nonlocal available
        assert available
        available = False
        return PromotedMailboxItems(
            operation_action=OperationActionInput(
                buffer=buffer, action=action, execution=execution
            ),
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[buffer.id],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=0,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        )

    resolved_request = dataclasses.replace(
        request(selection),
        session_id="session-001",
        agent_id="agent-001",
        workspace_id="workspace-001",
        toolkits=[],
    )
    pure_resolution = AsyncMock(
        return_value=Success(
            ResolvedInvokeInputProfile(
                run_request=resolved_request,
                model_selection=selection,
                model_settings=make_test_model_settings(),
                reasoning_effort=None,
            )
        )
    )
    monkeypatch.setattr(
        executor_module, "resolve_invoke_input_with_profile", pure_resolution
    )
    resolved_resolution = AsyncMock(return_value=Success(resolved_request))
    monkeypatch.setattr(
        executor_module,
        "resolve_invoke_input_with_resolved_profile",
        resolved_resolution,
    )
    monkeypatch.setattr(
        executor_module, "resolve_agent_tools", AsyncMock(return_value=[])
    )
    captured: list[RoutineJudgmentContext] = []

    async def execute_judgment(
        *,
        scope: RoutineScope,
        action: RoutineJudgmentAction,
        execution: ActionExecution,
        owner: SessionExecutionOwner,
        prepare_context: PrepareRoutineJudgmentContext,
    ) -> RoutineJudgmentSettlement:
        assert scope.session_id == owner.session_id == execution.session_id
        assert action.type == execution.action_type
        if capture_context:
            context = await prepare_context()
            await context.admit_dispatch()
            assert context.request.inference_state is None
            assert context.model_selection == selection
            captured.append(context)
            if resumed:
                raise _ContextCaptured(
                    "Resumed context captured before any ordinary turn."
                )
        return RoutineJudgmentSettlement(observation, None)

    service = Mock(spec=RoutineJudgmentService)
    service.execute = AsyncMock(side_effect=execute_judgment)
    executor.operation_action_executor = dataclasses.replace(
        executor.operation_action_executor, routine_judgment_service=service
    )
    ordinary_prepare = AsyncMock(
        side_effect=AssertionError("No foreground preparation is permitted.")
    )
    ordinary_inference = Mock(
        side_effect=AssertionError("No ordinary inference is permitted.")
    )
    monkeypatch.setattr(executor, "_prepare_fresh_main_model_turn", ordinary_prepare)
    monkeypatch.setattr(executor.engine, "run", ordinary_inference)
    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
    monkeypatch.setattr(
        executor.mailbox_item_service, "peek_pending_inference_profile", peek
    )
    monkeypatch.setattr(
        executor, "_has_actionable_model_input", AsyncMock(return_value=False)
    )
    call = executor.execute(
        _message(recoverable_run=recoverable),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=_noop_dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )
    if resumed:
        with pytest.raises(_ContextCaptured):
            await call
        pure_resolution.assert_not_awaited()
        resolved_resolution.assert_awaited_once()
        assert captured[0].model_selection == selection
        assert executor.test_session_state.inference_state is original_inference
        assert lifecycle.cancelled_pending_run_ids == []
        assert recoverable is not None and recoverable.status is AgentRunStatus.RUNNING
        ordinary_prepare.assert_not_awaited()
        ordinary_inference.assert_not_called()
        assert all(
            call.args[1]["type"]
            not in {
                "action_execution_updated",
                "action_execution_removed",
            }
            for call in broadcast.publish.await_args_list
        )
        return
    result = await call
    service.execute.assert_awaited_once()
    ordinary_prepare.assert_not_awaited()
    ordinary_inference.assert_not_called()
    assert result.no_actionable_work
    assert not result.terminal_event_observed
    assert all(
        call.args[1]["type"]
        not in {
            "action_execution_updated",
            "action_execution_removed",
        }
        for call in broadcast.publish.await_args_list
    )
    assert len(lifecycle.cancelled_pending_run_ids) == 1
    if capture_context:
        pure_resolution.assert_awaited_once()
        assert lifecycle.cancelled_pending_run_ids == [captured[0].turn.run_id]
    else:
        pure_resolution.assert_not_awaited()
    assert not available


async def test_later_poll_runs_judgment_in_the_existing_host_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = make_test_model_selection()
    run = _PendingRun(
        status=AgentRunStatus.RUNNING,
        resolved_model_selection=selection,
        effective_context_window_tokens=128_000,
        effective_auto_compaction_threshold_tokens=102_400,
    )
    lifecycle = _SessionLifecycle(recoverable_run=run)
    executor = _executor(session_lifecycle=lifecycle)
    snapshot = _message(recoverable_run=run)
    scope = RoutineScope(snapshot.workspace_id, snapshot.agent_id, snapshot.session_id)
    profile = RequestedInferenceProfile(
        model_target_label="default",
        reasoning_effort=None,
        enabled_execution_options=[],
    )
    inference = executor.test_session_state.inference_state
    assert isinstance(inference, SessionInferenceState)
    action = RoutineJudgmentAction(judgment_id="later-judgment")
    execution = _action_execution().model_copy(
        update={"action_type": action.type, "action": action.model_dump(mode="json")}
    )
    buffer = _judgment_buffer(execution, action)
    available = False
    trace: list[str] = []

    async def peek(session_id: str) -> PendingInputInferenceProfile:
        assert session_id == snapshot.session_id
        return PendingInputInferenceProfile(
            mailbox_item_id=buffer.id if available else None,
            requires_inference=False,
            exists=available,
            requested_inference_profile=None,
        )

    async def promote(*args: object, **kwargs: object) -> PromotedMailboxItems:
        nonlocal available
        assert available
        available = False
        trace.append("promote")
        return PromotedMailboxItems(
            operation_action=OperationActionInput(buffer, action, execution),
            turn_effect=TurnEffect.NEUTRAL,
            requested_inference_profile=None,
            promoted_event_ids=[],
            user_messages=[],
            events=[],
            deleted_buffer_ids=[buffer.id],
            changed_session_agent_ids=[],
            claimed_count=1,
            inserted_count=0,
            deduped_count=0,
            complete_run=False,
            suppress_parent_result=False,
        )

    async def prepare(current: RequestedInferenceProfile) -> RoutineJudgmentContext:
        assert current == profile
        trace.append("context")
        return RoutineJudgmentContext(
            request=request(selection),
            model_selection=selection,
            model_target_label=current.model_target_label,
            turn=TurnContext(
                workspace_id=scope.workspace_id,
                model=selection.model_identifier,
                session_id=scope.session_id,
                run_id=run.id,
                publish_event=AsyncMock(),
            ),
            admit_dispatch=AsyncMock(),
        )

    async def execute_judgment(
        *,
        scope: RoutineScope,
        action: RoutineJudgmentAction,
        execution: ActionExecution,
        owner: SessionExecutionOwner,
        prepare_context: PrepareRoutineJudgmentContext,
    ) -> RoutineJudgmentSettlement:
        assert scope.session_id == owner.session_id == execution.session_id
        assert action.type == execution.action_type
        context = await prepare_context()
        assert context.turn.run_id == run.id
        trace.append("judgment")
        return RoutineJudgmentSettlement(None, None)

    service = Mock(spec=RoutineJudgmentService)
    service.execute = AsyncMock(side_effect=execute_judgment)
    executor.operation_action_executor = dataclasses.replace(
        executor.operation_action_executor, routine_judgment_service=service
    )
    monkeypatch.setattr(
        executor.mailbox_item_service, "peek_pending_inference_profile", peek
    )
    monkeypatch.setattr(executor, "_promote_mailbox_items", promote)
    monkeypatch.setattr(
        executor, "_has_actionable_model_input", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        executor, "_has_model_configuration_drift", AsyncMock(return_value=False)
    )
    invalidated = Mock()
    poll = executor.make_boundary_poll(
        snapshot=snapshot,
        model=selection.model_identifier,
        requested_inference_profile=profile,
        prepared_inference_state=inference,
        run_id=run.id,
        poll_fn=None,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        routine_host=RoutineJudgmentHost(scope, prepare),
        mark_context_invalidated=invalidated,
        dispatch_event=_noop_dispatch_event,
    )
    first = await poll()
    assert not first.complete_run and not first.context_invalidated
    assert trace == []
    available = True
    second = await poll()
    assert trace == ["promote", "context", "judgment"]
    assert second.user_messages == []
    assert not second.complete_run and not second.context_invalidated
    invalidated.assert_not_called()
    assert run.status is AgentRunStatus.RUNNING
    assert executor.test_session_state.inference_state is inference
    assert lifecycle.cancelled_pending_run_ids == []
    service.execute.assert_awaited_once()
