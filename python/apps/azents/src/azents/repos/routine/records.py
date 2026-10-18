"""Bounded work-record persistence composed with admitted-item settlement."""

import datetime
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa

from azents.core.routine import (
    MAX_ROUTINE_WORK_RECORDS,
    RoutineDeliveryStatus,
    RoutineScope,
    RoutineWorkRecord,
    RoutineWorkResult,
)
from azents.rdb.models.routine import RDBRoutine, RDBRoutineWorkRecord
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.routine.definition import RoutineDefinitionRepository


@dataclass(frozen=True)
class RoutineRecordAppendResult:
    """A deleted definition has no record; duplicate recording is not creation."""

    record: RoutineWorkRecord | None
    created: bool


def _record(row: RDBRoutineWorkRecord) -> RoutineWorkRecord:
    """Decode typed work and transport outcome without interpreting success."""
    return RoutineWorkRecord(
        id=row.id,
        routine_id=row.routine_id,
        execution_id=row.execution_id,
        started_at=row.started_at,
        completed_at=row.completed_at,
        work=RoutineWorkResult(
            objective_outcome=row.objective_outcome,
            result=row.result,
            next_hint=row.next_hint,
            notify=row.notify,
            message=row.message,
        ),
        delivery_status=row.delivery_status,
        delivery_error=row.delivery_error,
    )


class RoutineWorkRecordRepository:
    """Own records only; no provider invocation, pending send, or Run terminal."""

    async def list_recent(
        self,
        session: ReadSession,
        *,
        scope: RoutineScope,
        routine_id: str,
        limit: int,
    ) -> list[RoutineWorkRecord]:
        """Read newest records within the exact owning Session boundary."""
        if not 1 <= limit <= MAX_ROUTINE_WORK_RECORDS:
            raise ValueError("Routine record limit must be between 1 and 100.")
        rows = await session.read_session.scalars(
            sa.select(RDBRoutineWorkRecord)
            .join(RDBRoutine, RDBRoutine.id == RDBRoutineWorkRecord.routine_id)
            .where(
                RDBRoutine.id == routine_id,
                RDBRoutine.workspace_id == scope.workspace_id,
                RDBRoutine.agent_id == scope.agent_id,
                RDBRoutine.session_id == scope.session_id,
                RDBRoutineWorkRecord.session_id == scope.session_id,
            )
            .order_by(
                RDBRoutineWorkRecord.completed_at.desc(), RDBRoutineWorkRecord.id.desc()
            )
            .limit(limit)
        )
        return [_record(row) for row in rows]

    async def append(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        routine_id: str,
        execution_id: str,
        started_at: datetime.datetime,
        work: RoutineWorkResult,
    ) -> RoutineRecordAppendResult:
        """Record once and trim atomically; never resurrect a deleted definition."""
        definition = await session.write_session.scalar(
            RoutineDefinitionRepository()
            .query(scope)
            .where(RDBRoutine.id == routine_id)
            .with_for_update()
        )
        if definition is None:
            return RoutineRecordAppendResult(record=None, created=False)
        existing = await session.write_session.scalar(
            sa.select(RDBRoutineWorkRecord).where(
                RDBRoutineWorkRecord.execution_id == execution_id,
                RDBRoutineWorkRecord.routine_id == routine_id,
                RDBRoutineWorkRecord.session_id == scope.session_id,
            )
        )
        if existing is not None:
            return RoutineRecordAppendResult(record=_record(existing), created=False)
        row = RDBRoutineWorkRecord(
            routine_id=definition.id,
            session_id=scope.session_id,
            execution_id=execution_id,
            started_at=started_at,
            objective_outcome=work.objective_outcome,
            result=work.result,
            next_hint=work.next_hint,
            notify=work.notify,
            message=work.message,
            delivery_status=(
                RoutineDeliveryStatus.UNOBSERVED
                if work.notify
                else RoutineDeliveryStatus.NOT_REQUESTED
            ),
            delivery_error=None,
        )
        session.write_session.add(row)
        await session.write_session.flush()
        saved = _record(row)
        oldest = (
            sa.select(RDBRoutineWorkRecord.id)
            .where(RDBRoutineWorkRecord.routine_id == routine_id)
            .order_by(
                RDBRoutineWorkRecord.completed_at.desc(), RDBRoutineWorkRecord.id.desc()
            )
            .offset(MAX_ROUTINE_WORK_RECORDS)
        )
        await session.write_session.execute(
            sa.delete(RDBRoutineWorkRecord).where(RDBRoutineWorkRecord.id.in_(oldest))
        )
        return RoutineRecordAppendResult(record=saved, created=True)

    async def observe_delivery(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        record_id: str,
        status: Literal[RoutineDeliveryStatus.DELIVERED, RoutineDeliveryStatus.FAILED],
        error: str | None,
    ) -> bool:
        """Record one observed effect, without resending or recreating records."""
        authorized_definitions = (
            RoutineDefinitionRepository().query(scope).with_only_columns(RDBRoutine.id)
        )
        result = await session.write_session.execute(
            sa.update(RDBRoutineWorkRecord)
            .where(
                RDBRoutineWorkRecord.id == record_id,
                RDBRoutineWorkRecord.session_id == scope.session_id,
                RDBRoutineWorkRecord.routine_id.in_(authorized_definitions),
                RDBRoutineWorkRecord.notify.is_(True),
                RDBRoutineWorkRecord.delivery_status
                == RoutineDeliveryStatus.UNOBSERVED,
            )
            .values(delivery_status=status, delivery_error=error)
            .returning(RDBRoutineWorkRecord.id)
        )
        return result.scalar_one_or_none() is not None
