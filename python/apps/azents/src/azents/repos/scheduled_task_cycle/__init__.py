"""Scheduled Task cycle Toolkit State repository."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.repos.toolkit_state import ToolkitStateConflictError, ToolkitStateRepository
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert

from .data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleSnapshot,
    ScheduledTaskCycleState,
    ScheduledTrackerProjectionPart,
)


@dataclasses.dataclass(frozen=True)
class ScheduledTaskCycleRepository:
    """Persist and transition one Session-scoped Scheduled Task cycle."""

    toolkit_state_repository: Annotated[
        ToolkitStateRepository, Depends(ToolkitStateRepository)
    ]

    NAMESPACE = "scheduled"

    @classmethod
    def state_name(cls, cycle_id: str) -> str:
        """Return canonical Toolkit State identity name."""
        return f"cycle:{cycle_id}"

    async def get(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> ScheduledTaskCycleRecord | None:
        """Read one cycle state without locking."""
        record = await self.toolkit_state_repository.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=self.NAMESPACE,
            state_name=self.state_name(cycle_id),
        )
        return self._build(record) if record is not None else None

    async def lock(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> ScheduledTaskCycleRecord | None:
        """Lock one cycle row for an admission/deletion transaction."""
        result = await session.execute(
            sa.select(RDBToolkitState)
            .where(
                RDBToolkitState.agent_id == agent_id,
                RDBToolkitState.session_id == session_id,
                RDBToolkitState.toolkit_namespace == self.NAMESPACE,
                RDBToolkitState.state_name == self.state_name(cycle_id),
            )
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        return self._build_rdb(rdb) if rdb is not None else None

    async def create_admitted(
        self,
        session: AsyncSession,
        snapshot: ScheduledTaskCycleSnapshot,
    ) -> ScheduledTaskCycleRecord:
        """Create an immutable admitted occurrence snapshot."""
        state = ScheduledTaskCycleState(
            cycle_id=snapshot.cycle_id,
            task_id=snapshot.task_id,
            phase="admitted",
            workspace_id=snapshot.workspace_id,
            agent_id=snapshot.agent_id,
            session_id=snapshot.session_id,
            binding_id=snapshot.binding_id,
            title=snapshot.title,
            objective=snapshot.objective,
            schedule_type=snapshot.schedule_type,
            scheduled_at=snapshot.scheduled_at,
            cron_expression=snapshot.cron_expression,
            timezone=snapshot.timezone,
            scheduled_for=snapshot.scheduled_for,
            current_run_id=None,
            started_at=None,
            progress_title=None,
            ordered_tasks=[],
            tracker_desired_revision=0,
            tracker_current_projection_parts=[],
        )
        record = await self.toolkit_state_repository.save(
            session,
            ToolkitStateUpsert(
                agent_id=state.agent_id,
                session_id=state.session_id,
                toolkit_namespace=self.NAMESPACE,
                state_name=self.state_name(state.cycle_id),
                state_json=state.model_dump(mode="json"),
                schema_version=1,
                expected_version=None,
            ),
        )
        return self._build(record)

    async def start(
        self,
        session: AsyncSession,
        *,
        record: ScheduledTaskCycleRecord,
        run_id: str,
        started_at: datetime.datetime,
    ) -> ScheduledTaskCycleRecord:
        """Transition an admitted cycle to started exactly once."""
        if record.state.phase != "admitted":
            raise ValueError("Scheduled Task cycle is not admitted")
        state = record.state.model_copy(
            update={
                "phase": "started",
                "current_run_id": run_id,
                "started_at": started_at,
            }
        )
        updated = await self.toolkit_state_repository.save(
            session,
            ToolkitStateUpsert(
                agent_id=state.agent_id,
                session_id=state.session_id,
                toolkit_namespace=self.NAMESPACE,
                state_name=self.state_name(state.cycle_id),
                state_json=state.model_dump(mode="json"),
                schema_version=1,
                expected_version=record.version,
            ),
        )
        return self._build(updated)

    async def delete_if_admitted(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> bool:
        """Delete only an admitted cycle; started cycles are preserved."""
        record = await self.lock(
            session,
            agent_id=agent_id,
            session_id=session_id,
            cycle_id=cycle_id,
        )
        if record is None or record.state.phase != "admitted":
            return False
        result = await session.execute(
            sa.delete(RDBToolkitState)
            .where(RDBToolkitState.id == record.toolkit_state_id)
            .returning(RDBToolkitState.id)
        )
        return result.scalar_one_or_none() is not None

    async def bind_run(
        self,
        session: AsyncSession,
        *,
        record: ScheduledTaskCycleRecord,
        run_id: str,
    ) -> ScheduledTaskCycleRecord:
        """Record the latest continuation Run while preserving started state."""
        if record.state.phase != "started":
            raise ValueError("Scheduled Task cycle is not started")
        state = record.state.model_copy(update={"current_run_id": run_id})
        updated = await self.toolkit_state_repository.save(
            session,
            ToolkitStateUpsert(
                agent_id=state.agent_id,
                session_id=state.session_id,
                toolkit_namespace=self.NAMESPACE,
                state_name=self.state_name(state.cycle_id),
                state_json=state.model_dump(mode="json"),
                schema_version=1,
                expected_version=record.version,
            ),
        )
        return self._build(updated)

    async def get_started(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> ScheduledTaskCycleRecord | None:
        """Read a started cycle, returning none for admitted/missing state."""
        record = await self.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            cycle_id=cycle_id,
        )
        if record is None or record.state.phase != "started":
            return None
        return record

    async def list_started(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
    ) -> list[ScheduledTaskCycleRecord]:
        """List current started cycles in deterministic occurrence order."""
        result = await session.execute(
            sa.select(RDBToolkitState).where(
                RDBToolkitState.agent_id == agent_id,
                RDBToolkitState.session_id == session_id,
                RDBToolkitState.toolkit_namespace == self.NAMESPACE,
            )
        )
        records = [
            self._build_rdb(rdb)
            for rdb in result.scalars()
            if rdb.state_name.startswith("cycle:")
        ]
        started = [record for record in records if record.state.phase == "started"]
        return sorted(
            started,
            key=lambda record: (
                record.state.scheduled_for,
                record.state.cycle_id,
            ),
        )

    async def delete_started(
        self,
        session: AsyncSession,
        *,
        record: ScheduledTaskCycleRecord,
    ) -> bool:
        """Delete one exact locked started cycle after terminal commit."""
        if record.state.phase != "started":
            raise ValueError("Scheduled Task cycle is not started")
        result = await session.execute(
            sa.delete(RDBToolkitState)
            .where(
                RDBToolkitState.id == record.toolkit_state_id,
                RDBToolkitState.version == record.version,
            )
            .returning(RDBToolkitState.id)
        )
        return result.scalar_one_or_none() is not None

    def _build(self, record: ToolkitStateRecord) -> ScheduledTaskCycleRecord:
        return ScheduledTaskCycleRecord(
            state=ScheduledTaskCycleState.model_validate(record.state_json),
            version=record.version,
            toolkit_state_id=record.id,
        )

    def _build_rdb(self, record: RDBToolkitState) -> ScheduledTaskCycleRecord:
        return ScheduledTaskCycleRecord(
            state=ScheduledTaskCycleState.model_validate(record.state_json),
            version=record.version,
            toolkit_state_id=record.id,
        )


__all__ = [
    "ScheduledTaskCycleRecord",
    "ScheduledTaskCycleRepository",
    "ScheduledTaskCycleSnapshot",
    "ScheduledTaskCycleState",
    "ScheduledTrackerProjectionPart",
    "ToolkitStateConflictError",
]
