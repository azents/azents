"""Bounded subagent coordination projection repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    MailboxSchedulingMode,
    SessionAgentKind,
)
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.repos.subagent_coordination.data import (
    SubagentCoordinationSnapshot,
    SubagentCoordinationSnapshotRow,
)


class SubagentCoordinationRepository:
    """Read bounded model-facing coordination snapshots."""

    async def project_root_tree(
        self,
        session: AsyncSession,
        *,
        current_session_id: str,
        configured_capacity: int,
    ) -> SubagentCoordinationSnapshot | None:
        """Project one bounded root tree from current durable state."""
        current_root_id = (
            sa.select(RDBSessionAgent.root_session_agent_id)
            .where(RDBSessionAgent.agent_session_id == current_session_id)
            .scalar_subquery()
        )
        root_tree = (
            sa.select(
                RDBSessionAgent.id.label("session_agent_id"),
                RDBSessionAgent.agent_session_id.label("agent_session_id"),
                RDBSessionAgent.kind.label("kind"),
                RDBSessionAgent.path.label("path"),
                RDBSessionAgent.last_message_at.label("last_message_at"),
                RDBSessionAgent.created_at.label("created_at"),
                RDBAgentSession.run_state.label("session_run_state"),
            )
            .select_from(RDBSessionAgent)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBSessionAgent.agent_session_id,
            )
            .where(RDBSessionAgent.root_session_agent_id == current_root_id)
            .cte("root_tree")
        )
        latest_run = (
            sa.select(RDBAgentRun.status.label("status"))
            .where(RDBAgentRun.session_id == root_tree.c.agent_session_id)
            .order_by(RDBAgentRun.run_index.desc())
            .limit(1)
            .lateral("latest_run")
        )
        wake_pending = sa.exists().where(
            RDBMailboxItem.session_id == root_tree.c.agent_session_id,
            RDBMailboxItem.scheduling_mode == MailboxSchedulingMode.WAKE_SESSION,
        )
        root = root_tree.c.kind == SessionAgentKind.ROOT
        required = sa.and_(
            sa.not_(root),
            sa.or_(
                root_tree.c.session_run_state == AgentSessionRunState.RUNNING,
                sa.func.coalesce(
                    latest_run.c.status.in_(
                        [AgentRunStatus.PENDING, AgentRunStatus.RUNNING]
                    ),
                    False,
                ),
                wake_pending,
            ),
        )
        classified = (
            sa.select(
                root_tree.c.session_agent_id,
                root_tree.c.agent_session_id,
                root_tree.c.kind,
                root_tree.c.path,
                root_tree.c.last_message_at,
                root_tree.c.created_at,
                root_tree.c.session_run_state,
                latest_run.c.status.label("latest_run_status"),
                wake_pending.label("wake_pending"),
                root.label("root"),
                required.label("required"),
            )
            .select_from(root_tree)
            .outerjoin(latest_run, sa.true())
            .cte("classified_agents")
        )
        inactive = sa.and_(
            sa.not_(classified.c.root),
            sa.not_(classified.c.required),
        )
        ranked = sa.select(
            *classified.c,
            inactive.label("inactive"),
            sa.func.row_number()
            .over(
                partition_by=inactive,
                order_by=(
                    classified.c.last_message_at.desc().nulls_last(),
                    classified.c.created_at.desc(),
                    classified.c.path.asc(),
                ),
            )
            .label("inactive_rank"),
        ).cte("ranked_agents")
        counts = sa.select(
            sa.func.count().filter(classified.c.required).label("required_count"),
            sa.func.count().filter(inactive).label("inactive_count"),
        ).cte("coordination_counts")
        configured = sa.literal(configured_capacity, type_=sa.Integer())
        inactive_slots = sa.func.greatest(
            configured - counts.c.required_count,
            0,
        )
        selected_inactive_count = sa.func.least(
            counts.c.inactive_count,
            inactive_slots,
        )
        omitted_inactive_count = sa.func.greatest(
            counts.c.inactive_count - inactive_slots,
            0,
        )
        statement = (
            sa.select(
                ranked.c.session_agent_id,
                ranked.c.agent_session_id,
                ranked.c.kind,
                ranked.c.path,
                ranked.c.last_message_at,
                ranked.c.created_at,
                ranked.c.session_run_state,
                ranked.c.latest_run_status,
                ranked.c.wake_pending,
                ranked.c.required,
                counts.c.required_count,
                selected_inactive_count.label("selected_inactive_count"),
                omitted_inactive_count.label("omitted_inactive_count"),
            )
            .select_from(ranked)
            .join(counts, sa.true())
            .where(
                sa.or_(
                    ranked.c.root,
                    ranked.c.required,
                    sa.and_(
                        ranked.c.inactive,
                        ranked.c.inactive_rank <= inactive_slots,
                    ),
                )
            )
            .order_by(
                sa.case((ranked.c.root, 0), else_=1),
                ranked.c.path.asc(),
            )
        )
        result = await session.execute(statement)
        mappings = result.mappings().all()
        if not mappings:
            return None
        first = mappings[0]
        return SubagentCoordinationSnapshot(
            rows=tuple(
                SubagentCoordinationSnapshotRow(
                    session_agent_id=row["session_agent_id"],
                    agent_session_id=row["agent_session_id"],
                    kind=row["kind"],
                    path=row["path"],
                    last_message_at=row["last_message_at"],
                    created_at=row["created_at"],
                    session_run_state=row["session_run_state"],
                    latest_run_status=row["latest_run_status"],
                    wake_pending=bool(row["wake_pending"]),
                    required=bool(row["required"]),
                )
                for row in mappings
            ),
            configured_capacity=configured_capacity,
            required_count=int(first["required_count"]),
            selected_inactive_count=int(first["selected_inactive_count"]),
            omitted_inactive_count=int(first["omitted_inactive_count"]),
        )
