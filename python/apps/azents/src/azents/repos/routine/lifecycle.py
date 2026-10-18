"""Routine lifecycle participation inside existing root-tree transactions."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import AgentRunStatus, MailboxItemKind
from azents.core.mailbox_data import (
    RoutineContinuationMailboxPayload,
    RoutineTriggerMailboxPayload,
    TurnActionMailboxPayload,
)
from azents.core.routine import RoutineScope
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.models.routine import RDBRoutine, RDBRoutineWorkRecord
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.routine.authority import RoutineExecutionAuthorityRepository
from azents.repos.routine.preserved import preserved_routine_work_exists
from azents.repos.routine.state import ROUTINE_STATE_NAMESPACE, RoutineStateRepository


@dataclass(frozen=True)
class RoutineLifecycleCleanup:
    """Deleted future authority and exact remaining started-work count."""

    deleted_definition_count: int
    deleted_state_count: int
    deleted_input_count: int
    preserved_started_count: int


@dataclass(frozen=True)
class RoutineLifecycleVerification:
    """Canonical absence projection, including the owned Toolkit namespace."""

    definition_count: int
    work_record_count: int
    state_count: int
    started_count: int
    pending_input_count: int


@dataclass(frozen=True)
class RoutineLifecycleRepository:
    """Preserve only started work with canonical Routine-only Run provenance."""

    states: Annotated[RoutineStateRepository, Depends()]
    authority: Annotated[RoutineExecutionAuthorityRepository, Depends()]

    async def preserved_running_session_ids(
        self, session: ReadSession, *, session_ids: Sequence[str]
    ) -> tuple[str, ...]:
        """Keep the ordinary Worker recovery target for preserved work."""
        return tuple(
            (
                await session.read_session.scalars(
                    sa.select(RDBAgentSession.id).where(
                        RDBAgentSession.id.in_(session_ids),
                        preserved_routine_work_exists(),
                    )
                )
            ).all()
        )

    @staticmethod
    async def scopes(
        session: ReadSession, session_ids: Sequence[str]
    ) -> tuple[RoutineScope, ...]:
        rows = (
            await session.read_session.execute(
                sa.select(
                    RDBAgentSession.id,
                    RDBAgentSession.workspace_id,
                    RDBAgentSession.agent_id,
                ).where(RDBAgentSession.id.in_(session_ids))
            )
        ).all()
        return tuple(
            RoutineScope(
                workspace_id=row.workspace_id, agent_id=row.agent_id, session_id=row.id
            )
            for row in rows
        )

    @staticmethod
    def input_predicate(session_ids: Sequence[str]) -> sa.ColumnElement[bool]:
        return sa.and_(
            RDBMailboxItem.session_id.in_(session_ids),
            sa.or_(
                RDBMailboxItem.kind.in_(
                    (
                        MailboxItemKind.ROUTINE_TRIGGER,
                        MailboxItemKind.ROUTINE_CONTINUATION,
                    )
                ),
                sa.and_(
                    RDBMailboxItem.kind == MailboxItemKind.ACTION_MESSAGE,
                    sa.func.jsonb_array_length(RDBMailboxItem.payload["items"]) == 1,
                    RDBMailboxItem.payload["items"][0]["action"]["type"].astext
                    == "routine_judgment",
                ),
            ),
        )

    async def archive_allows_active_runs(
        self,
        session: ReadSession,
        *,
        session_ids: Sequence[str],
        running_session_ids: Sequence[str],
    ) -> bool:
        """Reject any unrelated input or active Run, even beside started Routines."""
        scopes = {
            scope.session_id: scope for scope in await self.scopes(session, session_ids)
        }
        permitted: set[str] = set()
        runs = (
            await session.read_session.scalars(
                sa.select(RDBAgentRun).where(
                    RDBAgentRun.session_id.in_(session_ids),
                    RDBAgentRun.status.in_(
                        (AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
                    ),
                )
            )
        ).all()
        for run in runs:
            scope = scopes[run.session_id]
            started = [
                item.state
                for item in await self.states.list_executions(session, scope=scope)
                if item.state.phase == "started" and item.state.current_run_id == run.id
            ]
            if not started or not await self.authority.run_is_routine_only(
                session, scope=scope, run_id=run.id
            ):
                return False
            permitted.add(run.session_id)
        for scope in scopes.values():
            conversation = await session.read_session.get(
                RDBConversation, scope.session_id
            )
            predecessor_id = (
                None
                if conversation is None
                else conversation.pending_idle_continuation_run_id
            )
            if predecessor_id is None:
                continue
            predecessor = await session.read_session.get(RDBAgentRun, predecessor_id)
            if (
                predecessor is not None
                and predecessor.session_id == scope.session_id
                and predecessor.status is AgentRunStatus.COMPLETED
                and any(
                    item.state.phase == "started"
                    and item.state.current_run_id == predecessor_id
                    for item in await self.states.list_executions(session, scope=scope)
                )
            ):
                permitted.add(scope.session_id)
        inputs = (
            await session.read_session.scalars(
                sa.select(RDBMailboxItem).where(
                    RDBMailboxItem.session_id.in_(session_ids),
                )
            )
        ).all()
        for item in inputs:
            scope = scopes[item.session_id]
            match item.kind:
                case MailboxItemKind.ROUTINE_TRIGGER:
                    payload = RoutineTriggerMailboxPayload.model_validate(item.payload)
                    valid = await self.authority.refs_are_current(
                        session, scope=scope, refs=payload.executions, phase="admitted"
                    )
                case MailboxItemKind.ROUTINE_CONTINUATION:
                    payload = RoutineContinuationMailboxPayload.model_validate(
                        item.payload
                    )
                    valid = await self.authority.refs_are_current(
                        session, scope=scope, refs=payload.executions, phase="started"
                    )
                case MailboxItemKind.ACTION_MESSAGE:
                    envelope = TurnActionMailboxPayload.model_validate(item.payload)
                    if (
                        len(envelope.items) != 1
                        or envelope.items[0].action_identity.action_type
                        != "routine_judgment"
                    ):
                        return False
                    action = RoutineJudgmentAction.model_validate(
                        envelope.items[0].action
                    )
                    check = await self.states.get_check(session, scope=scope)
                    valid = (
                        check is not None
                        and check.state.queued_judgment_id == action.judgment_id
                    )
                case _:
                    return False
            if not valid:
                return False
            permitted.add(item.session_id)
        return set(running_session_ids).issubset(permitted)

    async def terminate_session_tree(
        self, session: WriteSession, *, session_ids: Sequence[str]
    ) -> RoutineLifecycleCleanup:
        """Remove future/pre-start authority; deletion never resurrects records."""
        preserved: list[str] = []
        for scope in await self.scopes(session, session_ids):
            for item in await self.states.list_executions(session, scope=scope):
                state = item.state
                if state.phase != "started" or state.current_run_id is None:
                    continue
                run = await session.read_session.get(RDBAgentRun, state.current_run_id)
                if run is not None and (
                    run.status is AgentRunStatus.COMPLETED
                    or (
                        run.status in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
                        and await self.authority.run_is_routine_only(
                            session, scope=scope, run_id=run.id
                        )
                    )
                ):
                    preserved.append(item.toolkit_state_id)
        deleted_definitions = (
            (
                await session.write_session.execute(
                    sa.delete(RDBRoutine)
                    .where(
                        RDBRoutine.session_id.in_(session_ids),
                    )
                    .returning(RDBRoutine.id)
                )
            )
            .scalars()
            .all()
        )
        deleted_states = (
            (
                await session.write_session.execute(
                    sa.delete(RDBToolkitState)
                    .where(
                        RDBToolkitState.session_id.in_(session_ids),
                        RDBToolkitState.toolkit_namespace == ROUTINE_STATE_NAMESPACE,
                        RDBToolkitState.id.not_in(preserved),
                    )
                    .returning(RDBToolkitState.id)
                )
            )
            .scalars()
            .all()
        )
        # Continuations for preserved started work remain eligible; all other
        # Routine input and source-only judgment authority is pre-start work.
        pending = (
            await session.read_session.scalars(
                sa.select(RDBMailboxItem).where(
                    self.input_predicate(session_ids),
                )
            )
        ).all()
        retained_ids: set[str] = set()
        for item in pending:
            if item.kind is not MailboxItemKind.ROUTINE_CONTINUATION:
                continue
            payload = RoutineContinuationMailboxPayload.model_validate(item.payload)
            scope = next(
                scope for scope in await self.scopes(session, (item.session_id,))
            )
            if await self.authority.refs_are_current(
                session, scope=scope, refs=payload.executions, phase="started"
            ):
                retained_ids.add(item.id)
        deleted_inputs = (
            (
                await session.write_session.execute(
                    sa.delete(RDBMailboxItem)
                    .where(
                        self.input_predicate(session_ids),
                        RDBMailboxItem.id.not_in(retained_ids),
                    )
                    .returning(RDBMailboxItem.id)
                )
            )
            .scalars()
            .all()
        )
        return RoutineLifecycleCleanup(
            len(deleted_definitions),
            len(deleted_states),
            len(deleted_inputs),
            len(preserved),
        )

    async def verify_session_tree(
        self, session: ReadSession, *, session_ids: Sequence[str]
    ) -> RoutineLifecycleVerification:
        """Read all owned roots and state, including definitions already deleted."""
        definitions = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBRoutine)
            .where(RDBRoutine.session_id.in_(session_ids))
        )
        records = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBRoutineWorkRecord)
            .where(RDBRoutineWorkRecord.session_id.in_(session_ids))
        )
        states = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBToolkitState)
            .where(
                RDBToolkitState.session_id.in_(session_ids),
                RDBToolkitState.toolkit_namespace == ROUTINE_STATE_NAMESPACE,
            )
        )
        inputs = await session.read_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBMailboxItem)
            .where(self.input_predicate(session_ids))
        )
        started = 0
        for scope in await self.scopes(session, session_ids):
            started += sum(
                item.state.phase == "started"
                for item in await self.states.list_executions(session, scope=scope)
            )
        return RoutineLifecycleVerification(
            definitions or 0, records or 0, states or 0, started, inputs or 0
        )

    async def validate_restore_session_tree(
        self, session: WriteSession, *, session_ids: Sequence[str]
    ) -> RoutineLifecycleVerification:
        """Restore does not recreate definitions, source checks or pre-start work."""
        result = await self.verify_session_tree(session, session_ids=session_ids)
        if result.definition_count or result.work_record_count:
            raise RuntimeError(
                "Archived Session retains Routine definitions or records."
            )
        for scope in await self.scopes(session, session_ids):
            if await self.states.get_check(session, scope=scope) is not None:
                raise RuntimeError("Archived Session retains Routine check authority.")
            if any(
                item.state.phase == "admitted"
                for item in await self.states.list_executions(session, scope=scope)
            ):
                raise RuntimeError("Archived Session retains pre-start Routine work.")
        return result

    async def has_preservable_started_work(
        self, session: ReadSession, *, session_ids: Sequence[str]
    ) -> bool:
        """A terminal failed/stopped host has no authority to settle its attempt."""
        for scope in await self.scopes(session, session_ids):
            for item in await self.states.list_executions(session, scope=scope):
                state = item.state
                if state.phase != "started" or state.current_run_id is None:
                    continue
                run = await session.read_session.get(RDBAgentRun, state.current_run_id)
                if (
                    run is not None
                    and run.session_id == scope.session_id
                    and run.status
                    in {
                        AgentRunStatus.PENDING,
                        AgentRunStatus.RUNNING,
                        AgentRunStatus.COMPLETED,
                    }
                ):
                    return True
        return False

    async def require_purge_ready(
        self, session: WriteSession, *, session_ids: Sequence[str]
    ) -> RoutineLifecycleVerification:
        result = await self.verify_session_tree(session, session_ids=session_ids)
        if await self.has_preservable_started_work(session, session_ids=session_ids):
            raise RuntimeError("Preserved Routine work has not finished.")
        return result

    async def purge_session_tree(
        self, session: WriteSession, *, session_ids: Sequence[str]
    ) -> RoutineLifecycleCleanup:
        await self.require_purge_ready(session, session_ids=session_ids)
        return await self.terminate_session_tree(session, session_ids=session_ids)
