"""SQL selectors for execution-independent work associations."""

import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy.orm import aliased

from azents.core.enums import AgentRunStatus, MailboxItemKind
from azents.core.goal import GOAL_TOOLKIT_NAMESPACE, GOAL_TOOLKIT_STATE_NAME
from azents.core.mailbox_data import (
    ContinuationMailboxPayload,
    MailboxEnvelopePayload,
    TurnActionContinuationMailboxPayload,
)
from azents.core.work_context import WorkContext
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session_capabilities import ReadSession

_MAILBOX_PAYLOAD = TypeAdapter(MailboxEnvelopePayload)


async def has_unfinished_work(
    session: ReadSession,
    *,
    session_id: str,
    context: WorkContext,
) -> bool:
    """Keep execution open for independent admitted or Session-owned obligations."""
    routine_refs = [
        sa.and_(
            RDBToolkitState.state_json["context"]["candidate"]["routine_id"].astext
            == ref.routine_id,
            RDBToolkitState.state_json["context"]["execution_id"].astext
            == ref.execution_id,
        )
        for ref in context.routine_executions
    ]
    return bool(
        await session.read_session.scalar(
            sa.select(
                sa.exists().where(
                    RDBToolkitState.agent_id
                    == sa.select(RDBAgentSession.agent_id)
                    .where(RDBAgentSession.id == session_id)
                    .scalar_subquery(),
                    RDBToolkitState.session_id == session_id,
                    sa.or_(
                        sa.and_(
                            RDBToolkitState.toolkit_namespace == "scheduled",
                            RDBToolkitState.state_name.in_(
                                tuple(
                                    f"cycle:{cycle_id}"
                                    for cycle_id in context.scheduled_cycle_ids
                                )
                            ),
                            RDBToolkitState.state_json["phase"].astext == "started",
                        ),
                        sa.and_(
                            RDBToolkitState.toolkit_namespace == "routines",
                            RDBToolkitState.state_json["phase"].astext == "started",
                            sa.or_(*routine_refs) if routine_refs else sa.false(),
                        ),
                        sa.and_(
                            RDBToolkitState.toolkit_namespace == GOAL_TOOLKIT_NAMESPACE,
                            RDBToolkitState.state_name == GOAL_TOOLKIT_STATE_NAME,
                            RDBToolkitState.state_json["status"].astext == "active",
                            RDBToolkitState.state_json["objective"].astext.is_not(None),
                        ),
                        sa.and_(
                            RDBToolkitState.toolkit_namespace == "external_channel",
                            RDBToolkitState.state_name.startswith("channel_work:"),
                            RDBToolkitState.state_json["status"].astext == "active",
                            RDBToolkitState.state_json[
                                "awaiting_input_run_id"
                            ].astext.is_(None),
                        ),
                    ),
                )
            )
        )
    )


async def continuation_work_context(
    session: ReadSession, *, item: RDBMailboxItem
) -> WorkContext | None:
    """Read exact same-Session continuation provenance for lifecycle admission."""
    payload = _MAILBOX_PAYLOAD.validate_python(item.payload)
    return await resolve_continuation_work_context(
        session, session_id=item.session_id, payload=payload
    )


async def resolve_continuation_work_context(
    session: ReadSession,
    *,
    session_id: str,
    payload: MailboxEnvelopePayload,
) -> WorkContext | None:
    """Separate completed work authority from a terminal bridge coordinator."""
    if isinstance(payload, ContinuationMailboxPayload):
        source_run_id = payload.source_run_id
    elif isinstance(payload, TurnActionContinuationMailboxPayload):
        source_run_id = payload.originating_run_id
    else:
        return None
    source = await session.read_session.get(RDBAgentRun, source_run_id)
    if (
        source is None
        or source.session_id != session_id
        or source.status is not AgentRunStatus.COMPLETED
    ):
        return None
    carried = WorkContext.model_validate(source.work_context)
    if isinstance(payload, TurnActionContinuationMailboxPayload):
        predecessor = await session.read_session.get(
            RDBAgentRun, payload.predecessor_run_id
        )
        if (
            predecessor is None
            or predecessor.session_id != session_id
            or predecessor.run_index < source.run_index
            or not (
                predecessor.status is AgentRunStatus.COMPLETED
                or predecessor.status is AgentRunStatus.CANCELLED
                and predecessor.started_at is None
            )
        ):
            return None
        carried = carried.merge(WorkContext.model_validate(predecessor.work_context))
    return carried


def queued_bridge_carries_run(*, require_routine_only: bool) -> sa.ColumnElement[bool]:
    """Correlate either exact source of a valid queued bridge with the outer Run."""
    origin = aliased(RDBAgentRun)
    predecessor = aliased(RDBAgentRun)
    context_constraints = (
        [
            sa.func.jsonb_array_length(run.work_context["scheduled_cycle_ids"]) == 0
            for run in (origin, predecessor)
        ]
        + [
            run.work_context["unrelated_input"].as_boolean().is_(False)
            for run in (origin, predecessor)
        ]
        if require_routine_only
        else []
    )
    return sa.exists(
        sa.select(1)
        .select_from(RDBMailboxItem)
        .join(
            origin,
            origin.id == RDBMailboxItem.payload["originating_run_id"].astext,
        )
        .join(
            predecessor,
            predecessor.id == RDBMailboxItem.payload["predecessor_run_id"].astext,
        )
        .where(
            RDBMailboxItem.kind == MailboxItemKind.TURN_ACTION_CONTINUATION,
            RDBMailboxItem.session_id == RDBAgentRun.session_id,
            origin.session_id == RDBAgentRun.session_id,
            predecessor.session_id == RDBAgentRun.session_id,
            origin.status == AgentRunStatus.COMPLETED,
            predecessor.run_index >= origin.run_index,
            sa.or_(
                predecessor.status == AgentRunStatus.COMPLETED,
                sa.and_(
                    predecessor.status == AgentRunStatus.CANCELLED,
                    predecessor.started_at.is_(None),
                ),
            ),
            sa.or_(origin.id == RDBAgentRun.id, predecessor.id == RDBAgentRun.id),
            *context_constraints,
        )
    ).correlate(RDBAgentRun)


async def run_has_queued_bridge(
    session: ReadSession, *, run_id: str, require_routine_only: bool
) -> bool:
    """Check exact retained lineage for one already-authorized execution."""
    return bool(
        await session.read_session.scalar(
            sa.select(
                queued_bridge_carries_run(require_routine_only=require_routine_only)
            )
            .select_from(RDBAgentRun)
            .where(RDBAgentRun.id == run_id)
        )
    )


def scheduled_work_predicate(cycle_id: str) -> sa.ColumnElement[bool]:
    """Match an explicit carried occurrence, never arbitrary active Session work."""
    return RDBAgentRun.work_context["scheduled_cycle_ids"].contains([cycle_id])


def routine_work_predicate(
    *, routine_id: str, execution_id: str
) -> sa.ColumnElement[bool]:
    """Match both definition and occurrence in the canonical context snapshot."""
    return RDBAgentRun.work_context["routine_executions"].contains(
        [{"routine_id": routine_id, "execution_id": execution_id}]
    )


async def latest_work_execution(
    session: ReadSession,
    *,
    session_id: str,
    predicate: sa.ColumnElement[bool],
) -> RDBAgentRun | None:
    """Read the latest actual execution association, not a domain current host."""
    return await session.read_session.scalar(
        sa.select(RDBAgentRun)
        .where(RDBAgentRun.session_id == session_id, predicate)
        .order_by(RDBAgentRun.run_index.desc())
        .limit(1)
    )
