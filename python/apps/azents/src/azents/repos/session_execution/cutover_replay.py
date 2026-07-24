"""Bounded durable-work projection for the Team Session cutover replay."""

import dataclasses

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    AgentSessionStatus,
    InputBufferSchedulingMode,
)
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.input_buffer import RDBInputBuffer

_MAX_BATCH_SIZE = 500


@dataclasses.dataclass(frozen=True)
class CutoverReplayCandidate:
    """One content-free durable Session work projection."""

    session_id: str
    owner_generation: int
    run_state: AgentSessionRunState
    wake_input_present: bool
    fifo_input_buffer_id: str | None
    pending_command_present: bool
    pending_command_id: str | None
    pending_command_complete: bool
    recoverable_run_id: str | None
    recoverable_run_count: int
    pending_idle_continuation_run_id: str | None
    stop_request_present: bool
    stop_request_id: str | None
    stop_request_complete: bool

    @property
    def has_pending_input(self) -> bool:
        """Return whether wake-producing FIFO input exists."""
        return self.wake_input_present

    @property
    def has_pending_command(self) -> bool:
        """Return whether any pending command state exists."""
        return self.pending_command_present

    @property
    def has_recoverable_run(self) -> bool:
        """Return whether a pending or running Run exists."""
        return self.recoverable_run_count > 0

    @property
    def has_pending_idle_continuation(self) -> bool:
        """Return whether an idle continuation is pending."""
        return self.pending_idle_continuation_run_id is not None

    @property
    def has_stop_request(self) -> bool:
        """Return whether any stop request state exists."""
        return self.stop_request_present

    def invariant_failure_codes(self) -> tuple[str, ...]:
        """Return local durable-state failures without exposing row contents."""
        failures: list[str] = []
        if self.has_pending_command and not self.pending_command_complete:
            failures.append("pending_command_incomplete")
        if self.has_stop_request and not self.stop_request_complete:
            failures.append("stop_request_incomplete")
        if self.recoverable_run_count > 1:
            failures.append("multiple_recoverable_runs")
        if (
            self.run_state is AgentSessionRunState.RUNNING
            and not self.has_pending_input
            and not self.has_pending_command
            and not self.has_recoverable_run
            and not self.has_pending_idle_continuation
            and not self.has_stop_request
        ):
            failures.append("running_without_durable_work")
        return tuple(failures)


@dataclasses.dataclass(frozen=True)
class CutoverReplayCandidateBatch:
    """One deterministic bounded page of durable replay candidates."""

    candidates: tuple[CutoverReplayCandidate, ...]
    next_session_cursor: str | None


class SessionCutoverReplayRepository:
    """Read replay candidates from PostgreSQL durable work state only."""

    async def fence_owner_generation(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        expected_owner_generation: int,
    ) -> int:
        """Invalidate the exact preflight owner generation before broker replay."""
        generation = await session.scalar(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.owner_generation == expected_owner_generation,
            )
            .values(owner_generation=RDBAgentSession.owner_generation + 1)
            .returning(RDBAgentSession.owner_generation)
        )
        if generation is None:
            raise ValueError("Session owner generation changed before replay")
        await session.flush()
        return generation

    async def read_candidate(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> CutoverReplayCandidate | None:
        """Read the current exact durable work identity for one Session."""
        row = (
            await session.execute(
                self._candidate_statement().where(RDBAgentSession.id == session_id)
            )
        ).one_or_none()
        return self._candidate(row) if row is not None else None

    async def read_candidate_batch(
        self,
        session: AsyncSession,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> CutoverReplayCandidateBatch:
        """Return one deterministic bounded page of Sessions with durable work."""
        if not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {_MAX_BATCH_SIZE}")

        statement = self._candidate_statement()
        if after_session_id is not None:
            statement = statement.where(RDBAgentSession.id > after_session_id)
        rows = (
            await session.execute(
                statement.order_by(RDBAgentSession.id).limit(batch_size + 1)
            )
        ).all()
        has_more = len(rows) > batch_size
        selected_rows = rows[:batch_size]
        candidates = tuple(self._candidate(row) for row in selected_rows)
        return CutoverReplayCandidateBatch(
            candidates=candidates,
            next_session_cursor=(
                candidates[-1].session_id if has_more and candidates else None
            ),
        )

    def _candidate_statement(self) -> sa.Select[tuple[object, ...]]:
        """Build the content-free exact durable-work projection."""
        fifo_input_buffer_id = (
            sa.select(RDBInputBuffer.id)
            .where(RDBInputBuffer.session_id == RDBAgentSession.id)
            .order_by(RDBInputBuffer.id)
            .limit(1)
            .correlate(RDBAgentSession)
            .scalar_subquery()
        )
        wake_input_present = sa.exists(
            sa.select(sa.literal(1)).where(
                RDBInputBuffer.session_id == RDBAgentSession.id,
                RDBInputBuffer.scheduling_mode
                == InputBufferSchedulingMode.WAKE_SESSION,
            )
        )
        recoverable_run_id = (
            sa.select(RDBAgentRun.id)
            .where(
                RDBAgentRun.session_id == RDBAgentSession.id,
                RDBAgentRun.status.in_(
                    (AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
                ),
            )
            .order_by(RDBAgentRun.created_at, RDBAgentRun.id)
            .limit(1)
            .correlate(RDBAgentSession)
            .scalar_subquery()
        )
        recoverable_run_count = (
            sa.select(sa.func.count())
            .select_from(RDBAgentRun)
            .where(
                RDBAgentRun.session_id == RDBAgentSession.id,
                RDBAgentRun.status.in_(
                    (AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
                ),
            )
            .correlate(RDBAgentSession)
            .scalar_subquery()
        )
        pending_command_columns = (
            RDBAgentSession.pending_command_id,
            RDBAgentSession.pending_command_name,
            RDBAgentSession.pending_command_payload,
            RDBAgentSession.pending_command_created_at,
        )
        stop_request_columns = (
            RDBAgentSession.stop_requested_at,
            RDBAgentSession.stop_request_id,
            RDBAgentSession.stop_requester_user_id,
        )
        has_pending_command = sa.or_(
            *(column.is_not(None) for column in pending_command_columns)
        )
        has_stop_request = sa.or_(
            *(column.is_not(None) for column in stop_request_columns)
        )
        return sa.select(
            RDBAgentSession.id,
            RDBAgentSession.owner_generation,
            RDBAgentSession.run_state,
            wake_input_present.label("wake_input_present"),
            fifo_input_buffer_id.label("fifo_input_buffer_id"),
            has_pending_command.label("pending_command_present"),
            RDBAgentSession.pending_command_id,
            sa.and_(*(column.is_not(None) for column in pending_command_columns)).label(
                "pending_command_complete"
            ),
            recoverable_run_id.label("recoverable_run_id"),
            recoverable_run_count.label("recoverable_run_count"),
            RDBAgentSession.pending_idle_continuation_run_id,
            has_stop_request.label("stop_request_present"),
            RDBAgentSession.stop_request_id,
            sa.and_(
                RDBAgentSession.stop_requested_at.is_not(None),
                RDBAgentSession.stop_request_id.is_not(None),
            ).label("stop_request_complete"),
        ).where(
            sa.or_(
                wake_input_present,
                has_pending_command,
                recoverable_run_count > 0,
                RDBAgentSession.pending_idle_continuation_run_id.is_not(None),
                has_stop_request,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
            )
        )

    def _candidate(self, row: object) -> CutoverReplayCandidate:
        """Build one typed content-free candidate row."""
        return CutoverReplayCandidate(
            session_id=row.id,  # type: ignore[attr-defined]
            owner_generation=row.owner_generation,  # type: ignore[attr-defined]
            run_state=row.run_state,  # type: ignore[attr-defined]
            wake_input_present=row.wake_input_present,  # type: ignore[attr-defined]
            fifo_input_buffer_id=row.fifo_input_buffer_id,  # type: ignore[attr-defined]
            pending_command_present=row.pending_command_present,  # type: ignore[attr-defined]
            pending_command_id=row.pending_command_id,  # type: ignore[attr-defined]
            pending_command_complete=row.pending_command_complete,  # type: ignore[attr-defined]
            recoverable_run_id=row.recoverable_run_id,  # type: ignore[attr-defined]
            recoverable_run_count=row.recoverable_run_count,  # type: ignore[attr-defined]
            pending_idle_continuation_run_id=row.pending_idle_continuation_run_id,  # type: ignore[attr-defined]
            stop_request_present=row.stop_request_present,  # type: ignore[attr-defined]
            stop_request_id=row.stop_request_id,  # type: ignore[attr-defined]
            stop_request_complete=row.stop_request_complete,  # type: ignore[attr-defined]
        )
