"""Real database checks for judgment inside the ordinary inbox/action boundary."""

import datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from azents.core.action_execution_data import ActionExecution
from azents.core.enums import ActionExecutionStatus, EventKind
from azents.core.routine import RoutineScope, RoutineUnavailable
from azents.core.routine_execution import RoutineCheckState
from azents.core.routine_judgment import (
    RoutineActionDecision,
    RoutineJudgmentConsidered,
    RoutineJudgmentDecision,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.action_messages import (
    ChatAction,
    PersistedChatAction,
    RoutineJudgmentAction,
)
from azents.engine.events.types import RoutineJudgmentPayload, UserMessagePayload
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.promotion import (
    MailboxActionExecutionCreate,
    MailboxPromotionPlan,
)
from azents.repos.routine.definition import RoutineDefinitionRepository
from azents.repos.routine.judgment_inbox import (
    RoutineJudgmentInboxRepository,
    RoutineJudgmentInput,
)
from azents.repos.routine.persistence_test import _content, _operations, _subject
from azents.repos.routine.records import RoutineWorkRecordRepository
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.testing.turn_action import (
    make_test_mailbox_promotion_repository,
)

NOW = datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC)


def repository(manager: SessionManager[WriteSession]) -> RoutineJudgmentInboxRepository:
    return RoutineJudgmentInboxRepository(
        session_manager=manager,
        definitions=RoutineDefinitionRepository(),
        records=RoutineWorkRecordRepository(),
        states=RoutineStateRepository(toolkit_states=ToolkitStateRepository()),
        admission=MailboxAdmissionRepository(
            session_manager=manager,
            mailbox_item_repository=MailboxRepository(),
            agent_session_repository=AgentSessionRepository(),
        ),
        actions=ActionExecutionRepository(),
        events=EventTranscriptRepository(),
    )


async def subject(manager: SessionManager[WriteSession]) -> RoutineScope:
    async with manager() as session:
        scope = await _subject(session)
    await _operations(manager).create(scope=scope, content=_content(), owner=None)
    return scope


def outcome(
    captured: RoutineJudgmentInput, *, act: bool, failed: bool
) -> RoutineJudgmentPayload:
    return RoutineJudgmentPayload(
        judgment_id=captured.action.judgment_id,
        considered=tuple(
            RoutineJudgmentConsidered(
                routine_id=item.routine_id, slug=item.slug, title=item.content.title
            )
            for item in captured.candidates
        ),
        status="failed" if failed else "completed",
        decision=None
        if failed
        else RoutineJudgmentDecision(
            decisions=tuple(
                RoutineActionDecision(routine_id=item.routine_id, act=act)
                for item in captured.candidates
            )
        ),
        error="Invalid Structured output." if failed else None,
        usage=None,
    )


async def promote(
    manager: SessionManager[WriteSession],
    *,
    scope: RoutineScope,
    action: RoutineJudgmentAction,
    buffer_id: str,
) -> ActionExecution:
    promoted = await make_test_mailbox_promotion_repository(manager).promote(
        MailboxPromotionPlan(
            session_id=scope.session_id,
            owner_generation=0,
            expected_buffer_id=buffer_id,
            active_run_id=None,
            consume_buffer=True,
            success_events=[],
            failure_events=[],
            goal_create=None,
            skill_revalidation=None,
            action_execution=MailboxActionExecutionCreate(
                action_type=action.type, action=action.model_dump(mode="json")
            ),
            continuation_predecessor_run_id=None,
        )
    )
    execution = promoted.action_execution
    assert execution is not None and execution.status is ActionExecutionStatus.PENDING
    return execution


def test_judgment_action_is_persisted_but_not_public_input() -> None:
    action = RoutineJudgmentAction(judgment_id="check-a")
    assert (
        TypeAdapter(PersistedChatAction).validate_python(action.model_dump(mode="json"))
        == action
    )
    with pytest.raises(ValidationError):
        TypeAdapter(ChatAction).validate_python(action.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        RoutineJudgmentAction.model_validate(
            {**action.model_dump(), "objective": "override"}
        )


@pytest.mark.parametrize("act,failed", [(False, False), (True, False), (False, True)])
async def test_action_promotion_capture_and_atomic_settlement(
    rdb_session_manager: SessionManager[WriteSession], *, act: bool, failed: bool
) -> None:
    manager = rdb_session_manager
    scope = await subject(manager)
    repo = repository(manager)
    admitted = await repo.admit_tick(scope=scope, now=NOW)
    assert admitted is not None and admitted.created
    assert await repo.admit_tick(scope=scope, now=NOW) is None
    action = RoutineJudgmentAction.model_validate(admitted.mailbox_item.action)
    execution = await promote(
        manager, scope=scope, action=action, buffer_id=admitted.mailbox_item.id
    )
    owner = SessionExecutionOwner(session_id=scope.session_id, owner_generation=0)
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await repo.capture(
            scope=scope,
            action=action,
            execution=execution,
            owner=SessionExecutionOwner(
                session_id=scope.session_id, owner_generation=99
            ),
            now=NOW,
        )
    captured = await repo.capture(
        scope=scope, action=action, execution=execution, owner=owner, now=NOW
    )
    assert len(captured.candidates) == 1
    # Definition and conversation advancement do not rewrite captured action input.
    await _operations(manager).update(
        scope=scope,
        slug=captured.candidates[0].slug,
        expected=captured.candidates[0].content,
        changes={"objective": "A new objective for future occurrences."},
        owner=owner,
    )
    async with manager() as session:
        await repo.events.append(
            session,
            EventCreate(
                session_id=scope.session_id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(
                    sender_user_id=None, content="Continue the ordinary investigation."
                ).model_dump(mode="json"),
            ),
        )
    # Input received after capture belongs to a future checking opportunity.
    assert (
        await repo.admit_tick(scope=scope, now=NOW + datetime.timedelta(minutes=30))
        is None
    )
    final = await repo.settle(
        scope=scope,
        captured=captured,
        execution=execution,
        owner=owner,
        outcome=outcome(captured, act=act, failed=failed),
        provider="openai",
        model="synthetic-model",
        now=NOW + datetime.timedelta(minutes=31),
    )
    assert final.observation is not None
    assert final.observation.kind is EventKind.ROUTINE_JUDGMENT
    assert (final.admission is not None) == act
    async with manager() as session:
        check = await repo.states.get_check(session, scope=scope)
        assert check is not None and check.state.queued_judgment_id is None
        assert check.state.last_action_at == (
            NOW + datetime.timedelta(minutes=31) if act else None
        )
        assert len(check.state.source_inputs[0].events) == (2 if failed else 1)
        assert (
            await repo.actions.get_by_id(session, action_execution_id=execution.id)
            is None
        )
        items = await repo.states.list_executions(session, scope=scope)
        assert len(items) == (1 if act else 0)
        if act:
            assert items[0].state.context.candidate == captured.candidates[0]
            assert items[0].state.phase == "admitted"
    repeated = await repo.settle(
        scope=scope,
        captured=captured,
        execution=execution,
        owner=owner,
        outcome=outcome(captured, act=act, failed=failed),
        provider="openai",
        model="synthetic-model",
        now=NOW + datetime.timedelta(minutes=31),
    )
    assert repeated.observation == final.observation and repeated.admission is None


async def test_delay_preserves_source_without_creating_an_exact_threshold_job(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    scope = await subject(rdb_session_manager)
    repo = repository(rdb_session_manager)
    async with rdb_session_manager() as session:
        await repo.states.save_check(
            session,
            scope=scope,
            state=RoutineCheckState(
                last_tick_at=None,
                last_action_at=NOW - datetime.timedelta(minutes=1),
                source_inputs=(),
                queued_judgment_id=None,
            ),
            expected_version=None,
        )
    assert await repo.admit_tick(scope=scope, now=NOW) is None
    async with rdb_session_manager() as session:
        saved = await repo.states.get_check(session, scope=scope)
        assert saved is not None and len(saved.state.source_inputs) == 1
        assert saved.state.queued_judgment_id is None
    admitted = await repo.admit_tick(
        scope=scope, now=NOW + datetime.timedelta(minutes=30)
    )
    assert admitted is not None


@pytest.mark.parametrize("clear_stop_flag", [False, True])
async def test_stop_fences_old_action_even_after_flag_clears(
    rdb_session_manager: SessionManager[WriteSession], *, clear_stop_flag: bool
) -> None:
    scope = await subject(rdb_session_manager)
    repo = repository(rdb_session_manager)
    admitted = await repo.admit_tick(scope=scope, now=NOW)
    assert admitted is not None
    action = RoutineJudgmentAction.model_validate(admitted.mailbox_item.action)
    execution = await promote(
        rdb_session_manager,
        scope=scope,
        action=action,
        buffer_id=admitted.mailbox_item.id,
    )
    owner = SessionExecutionOwner(session_id=scope.session_id, owner_generation=0)
    captured = await repo.capture(
        scope=scope, action=action, execution=execution, owner=owner, now=NOW
    )
    async with rdb_session_manager() as session:
        target = await session.write_session.get(RDBAgentSession, scope.session_id)
        assert target is not None
        target.stop_requested_at = NOW
        await repo.states.cancel_for_stop(session, scope=scope, now=NOW)
        if clear_stop_flag:
            target.stop_requested_at = None
    with pytest.raises(RoutineUnavailable):
        await repo.settle(
            scope=scope,
            captured=captured,
            execution=execution,
            owner=owner,
            outcome=outcome(captured, act=True, failed=False),
            provider="openai",
            model="synthetic-model",
            now=NOW,
        )
    async with rdb_session_manager() as session:
        assert await repo.states.list_executions(session, scope=scope) == []
        assert (
            await repo.events.list_recent_by_session_id(
                session, scope.session_id, limit=10
            )
            == []
        )


async def test_normal_owner_recovery_clears_only_its_old_action_identity(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    scope = await subject(rdb_session_manager)
    repo = repository(rdb_session_manager)
    admitted = await repo.admit_tick(scope=scope, now=NOW)
    assert admitted is not None
    action = RoutineJudgmentAction.model_validate(admitted.mailbox_item.action)
    execution = await promote(
        rdb_session_manager,
        scope=scope,
        action=action,
        buffer_id=admitted.mailbox_item.id,
    )
    async with rdb_session_manager() as session:
        target = await session.write_session.get(RDBAgentSession, scope.session_id)
        assert target is not None
        target.owner_generation = 1
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await repo.cancel_action(
            execution=execution,
            owner=SessionExecutionOwner(
                session_id=scope.session_id, owner_generation=0
            ),
        )
    owner = SessionExecutionOwner(session_id=scope.session_id, owner_generation=1)
    await repo.cancel_action(execution=execution, owner=owner)
    replacement = await repo.admit_tick(
        scope=scope, now=NOW + datetime.timedelta(minutes=30)
    )
    assert replacement is not None
    next_action = RoutineJudgmentAction.model_validate(replacement.mailbox_item.action)
    assert next_action.judgment_id != action.judgment_id
    await repo.cancel_action(execution=execution, owner=owner)
    async with rdb_session_manager() as session:
        check = await repo.states.get_check(session, scope=scope)
        assert check is not None
        assert check.state.queued_judgment_id == next_action.judgment_id
        assert len(check.state.source_inputs[0].events) == 2
        assert check.state.last_action_at is None
