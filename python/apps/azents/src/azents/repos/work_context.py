"""SQL selectors for execution-independent work associations."""

import sqlalchemy as sa
from pydantic import TypeAdapter

from azents.core.enums import AgentRunStatus
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
    if isinstance(payload, ContinuationMailboxPayload):
        source_run_id = payload.source_run_id
    elif isinstance(payload, TurnActionContinuationMailboxPayload):
        source_run_id = payload.predecessor_run_id
    else:
        return None
    source = await session.read_session.get(RDBAgentRun, source_run_id)
    if (
        source is None
        or source.session_id != item.session_id
        or source.status is not AgentRunStatus.COMPLETED
    ):
        return None
    return WorkContext.model_validate(source.work_context)


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
