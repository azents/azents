"""Historical Memory source persistence operations."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated

import sqlalchemy as sa
from azcommon.types import JSONValue
from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.core.historical_memory import (
    HistoricalMemoryCompletion,
    HistoricalMemoryDueSource,
    HistoricalMemoryFailure,
    HistoricalMemorySource,
)
from azents.core.historical_memory_consolidation import (
    ConsolidationWorkKind,
    prepared_source_evidence_hash,
)
from azents.core.historical_memory_snapshot import (
    HistoricalMemorySnapshotCandidate,
    MemorySnapshotConsumer,
)
from azents.core.model_operation import ModelOperationSnapshot
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.enrollment import (
    enroll_source_in_session,
)


@dataclasses.dataclass(frozen=True)
class HistoricalMemoryPreparationAdmission:
    """Historical and Session rows locked for one preparation attempt."""

    source: HistoricalMemoryDueSource
    product_mode: AgentSessionProductMode
    associated_user_id: str | None


class HistoricalMemoryRepository:
    """Own Historical Memory source result and progress transactions."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession],
            Depends(get_session_manager),
        ],
    ) -> None:
        """Create the repository."""
        self.session_manager = session_manager

    async def get_snapshot_consumer_in_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> MemorySnapshotConsumer | None:
        """Return one currently authorized Memory-enabled root consumer."""
        locked = (
            await session.execute(
                sa.select(RDBAgentSession, RDBAgent)
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .where(
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgent.memory_enabled.is_(True),
                    self._authorized_source(),
                )
                .with_for_update(of=(RDBAgentSession, RDBAgent))
            )
        ).one_or_none()
        if locked is None:
            return None
        row, _agent = locked
        if row.product_mode is None or not await self._lock_associated_user_membership(
            session, row
        ):
            return None
        return MemorySnapshotConsumer(
            session_id=row.id,
            agent_id=row.agent_id,
            workspace_id=row.workspace_id,
            product_mode=row.product_mode,
            associated_user_id=row.associated_user_id,
            model_input_head_event_id=row.model_input_head_event_id,
        )

    async def admit_eligible_sources(
        self,
        *,
        agent_id: str | None,
        now: datetime.datetime,
        oldest_activity_at: datetime.datetime,
        inactive_before: datetime.datetime,
        limit: int,
    ) -> list[str]:
        """Admit a bounded set of never-prepared eligible root Sessions."""
        async with self.session_manager() as session:
            admitted = await self.admit_eligible_sources_in_session(
                session,
                agent_id=agent_id,
                now=now,
                oldest_activity_at=oldest_activity_at,
                inactive_before=inactive_before,
                limit=limit,
            )
            await session.commit()
            return admitted

    async def admit_eligible_sources_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str | None,
        now: datetime.datetime,
        oldest_activity_at: datetime.datetime,
        inactive_before: datetime.datetime,
        limit: int,
    ) -> list[str]:
        """Admit eligible sources inside one caller-owned transaction."""
        if limit < 1:
            raise ValueError("Historical Memory admission limit must be positive.")
        authorized_source = self._authorized_source()
        candidates = (
            sa.select(RDBAgentSession.id)
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                RDBAgentSession.last_activity_at >= oldest_activity_at,
                RDBAgentSession.last_activity_at <= inactive_before,
                RDBAgent.memory_enabled.is_(True),
                authorized_source,
                ~sa.exists(
                    sa.select(RDBHistoricalMemorySource.source_session_id).where(
                        RDBHistoricalMemorySource.source_session_id
                        == RDBAgentSession.id
                    )
                ),
            )
            .order_by(
                RDBAgentSession.last_activity_at,
                RDBAgentSession.id,
            )
            .limit(limit)
            .with_for_update(of=RDBAgentSession, skip_locked=True)
        )
        if agent_id is not None:
            candidates = candidates.where(RDBAgentSession.agent_id == agent_id)
        source_ids = list((await session.execute(candidates)).scalars())
        if not source_ids:
            return []
        result = await session.execute(
            insert(RDBHistoricalMemorySource)
            .values(
                [
                    {
                        "source_session_id": source_id,
                        "admitted_at": now,
                    }
                    for source_id in source_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[RDBHistoricalMemorySource.source_session_id]
            )
            .returning(RDBHistoricalMemorySource.source_session_id)
        )
        await session.flush()
        return list(result.scalars())

    async def get(self, source_session_id: str) -> HistoricalMemorySource | None:
        """Return one source record."""
        async with self.session_manager() as session:
            return await self.get_in_session(session, source_session_id)

    async def get_in_session(
        self,
        session: AsyncSession,
        source_session_id: str,
    ) -> HistoricalMemorySource | None:
        """Return one source record inside a caller-owned transaction."""
        row = await session.get(RDBHistoricalMemorySource, source_session_id)
        return None if row is None else self._build(row)

    async def lock_in_session(
        self,
        session: AsyncSession,
        source_session_id: str,
    ) -> HistoricalMemorySource | None:
        """Lock and return one source record."""
        row = (
            await session.execute(
                sa.select(RDBHistoricalMemorySource)
                .where(RDBHistoricalMemorySource.source_session_id == source_session_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        return None if row is None else self._build(row)

    async def list_due_for_agent(
        self,
        *,
        agent_id: str,
        now: datetime.datetime,
        inactive_before: datetime.datetime,
        limit: int,
    ) -> list[HistoricalMemoryDueSource]:
        """Return admitted source work currently due for one Agent."""
        async with self.session_manager() as session:
            return await self.list_due_for_agent_in_session(
                session,
                agent_id=agent_id,
                now=now,
                inactive_before=inactive_before,
                limit=limit,
            )

    async def list_due_agent_ids(
        self,
        *,
        now: datetime.datetime,
        inactive_before: datetime.datetime,
        limit: int,
    ) -> list[str]:
        """Return a bounded set of Agents with currently due source work."""
        async with self.session_manager() as session:
            return await self.list_due_agent_ids_in_session(
                session,
                now=now,
                inactive_before=inactive_before,
                limit=limit,
            )

    async def list_due_agent_ids_in_session(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        inactive_before: datetime.datetime,
        limit: int,
    ) -> list[str]:
        """Return due Agent IDs inside one caller-owned transaction."""
        if limit < 1:
            raise ValueError("Historical Memory due-Agent limit must be positive.")
        visible_event_exists = sa.exists(
            sa.select(RDBEvent.id).where(
                RDBEvent.session_id == RDBHistoricalMemorySource.source_session_id,
                RDBEvent.reverted.is_(False),
            )
        )
        due_at = sa.func.min(
            sa.func.coalesce(
                RDBHistoricalMemorySource.next_retry_at,
                RDBHistoricalMemorySource.admitted_at,
            )
        )
        statement = (
            sa.select(RDBAgentSession.agent_id)
            .select_from(RDBHistoricalMemorySource)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                RDBAgentSession.last_activity_at <= inactive_before,
                RDBAgent.memory_enabled.is_(True),
                self._authorized_source(),
                sa.or_(
                    RDBHistoricalMemorySource.next_retry_at.is_(None),
                    RDBHistoricalMemorySource.next_retry_at <= now,
                ),
                sa.or_(
                    RDBHistoricalMemorySource.prepared_at.is_(None),
                    RDBHistoricalMemorySource.completed_source_activity_at.is_(None),
                    RDBAgentSession.last_activity_at
                    > RDBHistoricalMemorySource.completed_source_activity_at,
                ),
                visible_event_exists,
            )
            .group_by(RDBAgentSession.agent_id)
            .order_by(due_at, RDBAgentSession.agent_id)
            .limit(limit)
        )
        return list((await session.execute(statement)).scalars())

    async def list_due_for_agent_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        now: datetime.datetime,
        inactive_before: datetime.datetime,
        limit: int,
    ) -> list[HistoricalMemoryDueSource]:
        """Return due source work inside a caller-owned transaction."""
        if limit < 1:
            raise ValueError("Historical Memory due-source limit must be positive.")
        authorized_source = self._authorized_source()
        tail_event_id = (
            sa.select(sa.func.max(RDBEvent.id))
            .where(
                RDBEvent.session_id == RDBHistoricalMemorySource.source_session_id,
                RDBEvent.reverted.is_(False),
            )
            .correlate(RDBHistoricalMemorySource)
            .scalar_subquery()
        )
        statement = (
            sa.select(
                RDBHistoricalMemorySource,
                RDBAgentSession.agent_id,
                RDBAgentSession.workspace_id,
                RDBAgentSession.last_activity_at,
                RDBAgentSession.title,
                tail_event_id.label("source_tail_event_id"),
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                RDBAgentSession.last_activity_at <= inactive_before,
                RDBAgent.memory_enabled.is_(True),
                authorized_source,
                sa.or_(
                    RDBHistoricalMemorySource.next_retry_at.is_(None),
                    RDBHistoricalMemorySource.next_retry_at <= now,
                ),
                sa.or_(
                    RDBHistoricalMemorySource.prepared_at.is_(None),
                    RDBHistoricalMemorySource.completed_source_activity_at.is_(None),
                    RDBAgentSession.last_activity_at
                    > RDBHistoricalMemorySource.completed_source_activity_at,
                ),
                tail_event_id.is_not(None),
            )
            .order_by(
                sa.func.coalesce(
                    RDBHistoricalMemorySource.next_retry_at,
                    RDBHistoricalMemorySource.admitted_at,
                ),
                RDBAgentSession.last_activity_at,
                RDBAgentSession.id,
            )
            .limit(limit)
        )
        rows = (await session.execute(statement)).all()
        return [
            HistoricalMemoryDueSource(
                source_session_id=source.source_session_id,
                agent_id=row_agent_id,
                workspace_id=workspace_id,
                source_activity_at=source_activity_at,
                source_tail_event_id=source_tail_event_id,
                source_title=source_title,
                admitted_at=source.admitted_at,
                prepared_at=source.prepared_at,
                completed_source_activity_at=source.completed_source_activity_at,
                next_retry_at=source.next_retry_at,
                failure_count=source.failure_count,
                model_operation_state=self._operation(source.model_operation_state),
            )
            for (
                source,
                row_agent_id,
                workspace_id,
                source_activity_at,
                source_title,
                source_tail_event_id,
            ) in rows
        ]

    async def list_available_snapshot_candidates_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        workspace_id: str,
        consumer_product_mode: AgentSessionProductMode,
        associated_user_id: str | None,
        source_session_ids: Sequence[str] | None,
        limit: int,
    ) -> list[HistoricalMemorySnapshotCandidate]:
        """Return currently authorized prepared summaries for one root consumer."""
        if limit < 1:
            raise ValueError("Historical Memory snapshot limit must be positive.")
        if source_session_ids is not None and not source_session_ids:
            return []
        personal_scope = sa.false()
        if (
            consumer_product_mode is AgentSessionProductMode.USER
            and associated_user_id is not None
        ):
            personal_scope = sa.and_(
                RDBAgentSession.product_mode == AgentSessionProductMode.USER,
                RDBAgentSession.associated_user_id == associated_user_id,
            )
        statement = (
            sa.select(
                RDBHistoricalMemorySource.source_session_id,
                RDBAgentSession.product_mode,
                RDBAgentSession.title,
                RDBHistoricalMemorySource.completed_source_activity_at,
                RDBHistoricalMemorySource.prepared_at,
                RDBHistoricalMemorySource.summary,
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgent.memory_enabled.is_(True),
                self._authorized_source(),
                sa.or_(
                    RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
                    personal_scope,
                ),
                RDBHistoricalMemorySource.prepared_at.is_not(None),
                RDBHistoricalMemorySource.completed_source_activity_at.is_not(None),
                RDBHistoricalMemorySource.summary.is_not(None),
                RDBHistoricalMemorySource.summary != "",
            )
            .order_by(
                RDBHistoricalMemorySource.completed_source_activity_at.desc(),
                RDBHistoricalMemorySource.prepared_at.desc(),
                RDBHistoricalMemorySource.source_session_id,
            )
            .limit(limit)
        )
        if source_session_ids is not None:
            statement = statement.where(
                RDBHistoricalMemorySource.source_session_id.in_(source_session_ids)
            )
        rows = (await session.execute(statement)).all()
        return [
            HistoricalMemorySnapshotCandidate(
                source_session_id=source_session_id,
                source_scope=(
                    "team" if product_mode is AgentSessionProductMode.TEAM else "user"
                ),
                source_title=source_title,
                source_activity_through=source_activity_through,
                prepared_at=prepared_at,
                summary=summary,
            )
            for (
                source_session_id,
                product_mode,
                source_title,
                source_activity_through,
                prepared_at,
                summary,
            ) in rows
        ]

    async def lock_preparation_admission_in_session(
        self,
        session: AsyncSession,
        *,
        source_session_id: str,
        attempted_at: datetime.datetime,
        inactive_before: datetime.datetime,
    ) -> HistoricalMemoryPreparationAdmission | None:
        """Lock Historical then Session authority and capture the source boundary."""
        row = (
            await session.execute(
                sa.select(RDBHistoricalMemorySource)
                .where(
                    RDBHistoricalMemorySource.source_session_id == source_session_id,
                    sa.or_(
                        RDBHistoricalMemorySource.next_retry_at.is_(None),
                        RDBHistoricalMemorySource.next_retry_at <= attempted_at,
                    ),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        source = (
            await session.execute(
                sa.select(RDBAgentSession)
                .where(
                    RDBAgentSession.id == source_session_id,
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                    RDBAgentSession.last_activity_at <= inactive_before,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if source is None:
            return None
        if (
            row.prepared_at is not None
            and row.completed_source_activity_at is not None
            and source.last_activity_at <= row.completed_source_activity_at
        ):
            return None
        source_tail_event_id = await session.scalar(
            sa.select(sa.func.max(RDBEvent.id)).where(
                RDBEvent.session_id == source_session_id,
                RDBEvent.reverted.is_(False),
            )
        )
        if source_tail_event_id is None or source.product_mode is None:
            return None
        return HistoricalMemoryPreparationAdmission(
            source=HistoricalMemoryDueSource(
                source_session_id=row.source_session_id,
                agent_id=source.agent_id,
                workspace_id=source.workspace_id,
                source_activity_at=source.last_activity_at,
                source_tail_event_id=source_tail_event_id,
                source_title=source.title,
                admitted_at=row.admitted_at,
                prepared_at=row.prepared_at,
                completed_source_activity_at=row.completed_source_activity_at,
                next_retry_at=row.next_retry_at,
                failure_count=row.failure_count,
                model_operation_state=self._operation(row.model_operation_state),
            ),
            product_mode=source.product_mode,
            associated_user_id=source.associated_user_id,
        )

    async def lock_preparation_membership_in_session(
        self,
        session: AsyncSession,
        admission: HistoricalMemoryPreparationAdmission,
    ) -> bool:
        """Lock current User membership after the Agent lock is held."""
        if admission.product_mode is AgentSessionProductMode.TEAM:
            return True
        if (
            admission.product_mode is not AgentSessionProductMode.USER
            or admission.associated_user_id is None
        ):
            return False
        membership_id = await session.scalar(
            sa.select(RDBWorkspaceUser.id)
            .where(
                RDBWorkspaceUser.workspace_id == admission.source.workspace_id,
                RDBWorkspaceUser.user_id == admission.associated_user_id,
            )
            .with_for_update()
        )
        return membership_id is not None

    async def persist_preparation_operation_in_session(
        self,
        session: AsyncSession,
        admission: HistoricalMemoryPreparationAdmission,
        *,
        attempted_at: datetime.datetime,
        operation: ModelOperationSnapshot,
    ) -> HistoricalMemoryDueSource:
        """Persist the selected operation while all admission locks remain held."""
        row = await session.get(
            RDBHistoricalMemorySource,
            admission.source.source_session_id,
        )
        if row is None:
            raise RuntimeError("Locked Historical Memory source disappeared.")
        row.last_attempt_at = attempted_at
        row.model_operation_state = self._operation_json(operation)
        await session.flush()
        return admission.source.model_copy(update={"model_operation_state": operation})

    async def record_failure(
        self,
        *,
        source_session_id: str,
        failure: HistoricalMemoryFailure,
    ) -> HistoricalMemorySource | None:
        """Persist bounded failure and retry progress."""
        async with self.session_manager() as session:
            record = await self.record_failure_in_session(
                session,
                source_session_id=source_session_id,
                failure=failure,
            )
            await session.commit()
            return record

    async def record_failure_in_session(
        self,
        session: AsyncSession,
        *,
        source_session_id: str,
        failure: HistoricalMemoryFailure,
    ) -> HistoricalMemorySource | None:
        """Persist failure progress inside a caller-owned transaction."""
        row = (
            await session.execute(
                sa.update(RDBHistoricalMemorySource)
                .where(RDBHistoricalMemorySource.source_session_id == source_session_id)
                .values(
                    last_attempt_at=failure.attempted_at,
                    next_retry_at=failure.next_retry_at,
                    failure_count=RDBHistoricalMemorySource.failure_count + 1,
                    last_failure_code=failure.failure_code,
                    model_operation_state=self._operation_json(
                        failure.model_operation_state
                    ),
                )
                .returning(RDBHistoricalMemorySource)
            )
        ).scalar_one_or_none()
        await session.flush()
        return None if row is None else self._build(row)

    async def publish_completed(
        self,
        *,
        source_session_id: str,
        completion: HistoricalMemoryCompletion,
    ) -> HistoricalMemorySource | None:
        """Publish one successful empty or non-empty source result."""
        async with self.session_manager() as session:
            record = await self.publish_completed_in_session(
                session,
                source_session_id=source_session_id,
                completion=completion,
            )
            await session.commit()
            return record

    async def publish_completed_in_session(
        self,
        session: AsyncSession,
        *,
        source_session_id: str,
        completion: HistoricalMemoryCompletion,
    ) -> HistoricalMemorySource | None:
        """Publish one completed result inside a caller-owned transaction."""
        locked = (
            await session.execute(
                sa.select(
                    RDBHistoricalMemorySource,
                    RDBAgentSession,
                    RDBAgent,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
                )
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .where(
                    RDBHistoricalMemorySource.source_session_id == source_session_id,
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgent.memory_enabled.is_(True),
                    self._authorized_source(),
                )
                .with_for_update(
                    of=(
                        RDBHistoricalMemorySource,
                        RDBAgentSession,
                        RDBAgent,
                    ),
                )
            )
        ).one_or_none()
        if locked is None:
            return None
        row, source, _agent = locked
        if not await self._lock_associated_user_membership(session, source):
            return None
        row.last_attempt_at = completion.prepared_at
        row.next_retry_at = None
        row.failure_count = 0
        row.last_failure_code = None
        row.model_operation_state = None
        row.completed_source_activity_at = completion.source_activity_at
        row.completed_source_tail_event_id = completion.source_tail_event_id
        row.prepared_at = completion.prepared_at
        row.source_title_snapshot = completion.source_title_snapshot
        row.summary = completion.summary or None
        row.summary_generation += 1
        row.evidence_hash = prepared_source_evidence_hash(completion)
        await enroll_source_in_session(
            session,
            source=row,
            root=source,
            kind=ConsolidationWorkKind.PREPARED,
        )
        await session.flush()
        await session.refresh(row)
        return self._build(row)

    @staticmethod
    async def _lock_associated_user_membership(
        session: AsyncSession,
        source: RDBAgentSession,
    ) -> bool:
        """Lock the current User-source membership authority when required."""
        if source.product_mode is AgentSessionProductMode.TEAM:
            return True
        if (
            source.product_mode is not AgentSessionProductMode.USER
            or source.associated_user_id is None
        ):
            return False
        membership_id = await session.scalar(
            sa.select(RDBWorkspaceUser.id)
            .where(
                RDBWorkspaceUser.workspace_id == source.workspace_id,
                RDBWorkspaceUser.user_id == source.associated_user_id,
            )
            .with_for_update()
        )
        return membership_id is not None

    @staticmethod
    def _authorized_source() -> sa.ColumnElement[bool]:
        membership_exists = sa.exists(
            sa.select(RDBWorkspaceUser.id).where(
                RDBWorkspaceUser.workspace_id == RDBAgentSession.workspace_id,
                RDBWorkspaceUser.user_id == RDBAgentSession.associated_user_id,
            )
        )
        return sa.and_(
            RDBAgent.workspace_id == RDBAgentSession.workspace_id,
            sa.or_(
                RDBAgentSession.product_mode == AgentSessionProductMode.TEAM,
                sa.and_(
                    RDBAgentSession.product_mode == AgentSessionProductMode.USER,
                    membership_exists,
                ),
            ),
        )

    @classmethod
    def _build(cls, row: RDBHistoricalMemorySource) -> HistoricalMemorySource:
        return HistoricalMemorySource(
            source_session_id=row.source_session_id,
            admitted_at=row.admitted_at,
            last_attempt_at=row.last_attempt_at,
            next_retry_at=row.next_retry_at,
            failure_count=row.failure_count,
            last_failure_code=row.last_failure_code,
            model_operation_state=cls._operation(row.model_operation_state),
            completed_source_activity_at=row.completed_source_activity_at,
            completed_source_tail_event_id=row.completed_source_tail_event_id,
            prepared_at=row.prepared_at,
            source_title_snapshot=row.source_title_snapshot,
            summary=row.summary,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _operation(
        value: dict[str, JSONValue] | None,
    ) -> ModelOperationSnapshot | None:
        return None if value is None else ModelOperationSnapshot.model_validate(value)

    @staticmethod
    def _operation_json(
        value: ModelOperationSnapshot | None,
    ) -> dict[str, JSONValue] | None:
        return None if value is None else value.model_dump(mode="json")
