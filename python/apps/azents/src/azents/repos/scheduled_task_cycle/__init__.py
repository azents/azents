"""Scheduled Task cycle Toolkit State repository."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelWorkProjectionStatus
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

    async def update_progress(
        self,
        session: AsyncSession,
        *,
        record: ScheduledTaskCycleRecord,
        progress_title: str,
        ordered_tasks: list[str],
    ) -> ScheduledTaskCycleRecord:
        """Replace Scheduled progress and advance its independent desired revision."""
        if record.state.phase != "started":
            raise ValueError("Scheduled Task cycle is not started")
        normalized_title = progress_title.strip()
        if not normalized_title:
            raise ValueError("Scheduled Task progress title must not be empty")
        normalized_tasks = [task.strip() for task in ordered_tasks]
        if not normalized_tasks or any(not task for task in normalized_tasks):
            raise ValueError("Scheduled Task progress requires non-empty ordered tasks")
        state = record.state.model_copy(
            update={
                "progress_title": normalized_title,
                "ordered_tasks": normalized_tasks,
                "tracker_desired_revision": (record.state.tracker_desired_revision + 1),
            }
        )
        return await self._save_state(
            session,
            state=state,
            expected_version=record.version,
        )

    async def claim_tracker_projection(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
        expected_desired_revision: int,
        part_ordinal: int,
    ) -> ScheduledTaskCycleRecord | None:
        """Preclaim one current Tracker mutation without sharing Channel Work state."""
        if expected_desired_revision < 0 or part_ordinal < 0:
            raise ValueError(
                "Scheduled Tracker revisions and ordinals must be non-negative"
            )
        for _ in range(3):
            record = await self.get(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if (
                record is None
                or record.state.phase != "started"
                or record.state.tracker_desired_revision != expected_desired_revision
            ):
                return None
            existing = next(
                (
                    part
                    for part in record.state.tracker_current_projection_parts
                    if part.part_ordinal == part_ordinal
                ),
                None,
            )
            if (
                existing is not None
                and existing.desired_revision == expected_desired_revision
            ):
                return None
            claimed = ScheduledTrackerProjectionPart(
                part_ordinal=part_ordinal,
                desired_revision=expected_desired_revision,
                status=ExternalChannelWorkProjectionStatus.UNKNOWN,
                provider_message_key=(
                    None if existing is None else existing.provider_message_key
                ),
            )
            projection_parts = [
                part
                for part in record.state.tracker_current_projection_parts
                if part.part_ordinal != part_ordinal
            ]
            projection_parts.append(claimed)
            projection_parts.sort(key=lambda part: part.part_ordinal)
            state = record.state.model_copy(
                update={"tracker_current_projection_parts": projection_parts}
            )
            try:
                return await self._save_state(
                    session,
                    state=state,
                    expected_version=record.version,
                )
            except ToolkitStateConflictError:
                continue
        raise ToolkitStateConflictError(
            "Scheduled Tracker projection claim version conflict"
        )

    async def settle_tracker_projection(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
        expected_desired_revision: int,
        part_ordinal: int,
        status: ExternalChannelWorkProjectionStatus,
        provider_message_key: str | None,
    ) -> bool:
        """Compare-and-set one current Scheduled Tracker provider outcome."""
        if expected_desired_revision < 0 or part_ordinal < 0:
            raise ValueError(
                "Scheduled Tracker revisions and ordinals must be non-negative"
            )
        if (
            status is ExternalChannelWorkProjectionStatus.PRESENT
            and provider_message_key is None
        ):
            raise ValueError(
                "Present Scheduled Tracker projection requires a message key"
            )
        for _ in range(3):
            record = await self.get(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if (
                record is None
                or record.state.phase != "started"
                or record.state.tracker_desired_revision != expected_desired_revision
            ):
                return False
            existing = next(
                (
                    part
                    for part in record.state.tracker_current_projection_parts
                    if part.part_ordinal == part_ordinal
                ),
                None,
            )
            if (
                existing is None
                or existing.desired_revision != expected_desired_revision
            ):
                return False
            if status is ExternalChannelWorkProjectionStatus.DELETED:
                settled_message_key = None
            elif provider_message_key is None:
                settled_message_key = existing.provider_message_key
            else:
                settled_message_key = provider_message_key
            settled = existing.model_copy(
                update={
                    "status": status,
                    "provider_message_key": settled_message_key,
                }
            )
            projection_parts = [
                settled if part.part_ordinal == part_ordinal else part
                for part in record.state.tracker_current_projection_parts
            ]
            state = record.state.model_copy(
                update={"tracker_current_projection_parts": projection_parts}
            )
            try:
                await self._save_state(
                    session,
                    state=state,
                    expected_version=record.version,
                )
            except ToolkitStateConflictError:
                continue
            return True
        raise ToolkitStateConflictError(
            "Scheduled Tracker projection settlement version conflict"
        )

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

    async def _save_state(
        self,
        session: AsyncSession,
        *,
        state: ScheduledTaskCycleState,
        expected_version: int,
    ) -> ScheduledTaskCycleRecord:
        """Persist one exact whole-cycle state replacement."""
        updated = await self.toolkit_state_repository.save(
            session,
            ToolkitStateUpsert(
                agent_id=state.agent_id,
                session_id=state.session_id,
                toolkit_namespace=self.NAMESPACE,
                state_name=self.state_name(state.cycle_id),
                state_json=state.model_dump(mode="json"),
                schema_version=state.schema_version,
                expected_version=expected_version,
            ),
        )
        return self._build(updated)


__all__ = [
    "ScheduledTaskCycleRecord",
    "ScheduledTaskCycleRepository",
    "ScheduledTaskCycleSnapshot",
    "ScheduledTaskCycleState",
    "ScheduledTrackerProjectionPart",
    "ToolkitStateConflictError",
]
