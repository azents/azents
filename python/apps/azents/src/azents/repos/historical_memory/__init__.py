"""Historical Memory source persistence operations."""

import datetime
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
from azents.core.model_operation import ModelOperationSnapshot
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager


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

    async def admit_eligible_sources(
        self,
        *,
        now: datetime.datetime,
        oldest_activity_at: datetime.datetime,
        inactive_before: datetime.datetime,
        limit: int,
    ) -> list[str]:
        """Admit a bounded set of never-prepared eligible root Sessions."""
        async with self.session_manager() as session:
            admitted = await self.admit_eligible_sources_in_session(
                session,
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

    async def begin_preparation(
        self,
        *,
        source_session_id: str,
        attempted_at: datetime.datetime,
        inactive_before: datetime.datetime,
        operation: ModelOperationSnapshot | None,
    ) -> HistoricalMemoryDueSource | None:
        """Reauthorize and capture one source boundary before evidence loading."""
        async with self.session_manager() as session:
            source = await self.begin_preparation_in_session(
                session,
                source_session_id=source_session_id,
                attempted_at=attempted_at,
                inactive_before=inactive_before,
                operation=operation,
            )
            await session.commit()
            return source

    async def begin_preparation_in_session(
        self,
        session: AsyncSession,
        *,
        source_session_id: str,
        attempted_at: datetime.datetime,
        inactive_before: datetime.datetime,
        operation: ModelOperationSnapshot | None,
    ) -> HistoricalMemoryDueSource | None:
        """Lock current authority and capture one preparation boundary."""
        tail_event_id = (
            sa.select(sa.func.max(RDBEvent.id))
            .where(
                RDBEvent.session_id == RDBHistoricalMemorySource.source_session_id,
                RDBEvent.reverted.is_(False),
            )
            .correlate(RDBHistoricalMemorySource)
            .scalar_subquery()
        )
        locked = (
            await session.execute(
                sa.select(
                    RDBHistoricalMemorySource,
                    RDBAgentSession,
                    RDBAgent,
                    tail_event_id.label("source_tail_event_id"),
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
                    RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                    RDBAgentSession.last_activity_at <= inactive_before,
                    RDBAgent.memory_enabled.is_(True),
                    self._authorized_source(),
                    sa.or_(
                        RDBHistoricalMemorySource.next_retry_at.is_(None),
                        RDBHistoricalMemorySource.next_retry_at <= attempted_at,
                    ),
                    sa.or_(
                        RDBHistoricalMemorySource.prepared_at.is_(None),
                        RDBHistoricalMemorySource.completed_source_activity_at.is_(
                            None
                        ),
                        RDBAgentSession.last_activity_at
                        > RDBHistoricalMemorySource.completed_source_activity_at,
                    ),
                    tail_event_id.is_not(None),
                )
                .with_for_update(
                    of=(
                        RDBHistoricalMemorySource,
                        RDBAgentSession,
                        RDBAgent,
                    )
                )
            )
        ).one_or_none()
        if locked is None:
            return None
        row, source, _agent, source_tail_event_id = locked
        if not await self._lock_associated_user_membership(session, source):
            return None
        row.last_attempt_at = attempted_at
        row.model_operation_state = self._operation_json(operation)
        await session.flush()
        return HistoricalMemoryDueSource(
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
            model_operation_state=operation,
        )

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
    ) -> dict[str, object] | None:
        return None if value is None else value.model_dump(mode="json")
