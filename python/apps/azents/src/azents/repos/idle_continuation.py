"""Completed Session idle-continuation database operations."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import (
    MailboxEnvelopePayload,
    MailboxItem,
    MailboxItemCreate,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
)


class _IdleContinuationConsumptionRejected(RuntimeError):
    """Abort admissions when the durable idle boundary cannot be consumed."""


@dataclasses.dataclass(frozen=True)
class IdleBoundaryEligibility:
    """True-idle admission plus archived Scheduled exception identity."""

    eligible: bool
    archived_cycle_id: str | None


@dataclasses.dataclass(frozen=True)
class IdleContinuationInput:
    """One prepared hook continuation ready for transactional admission."""

    session_id: str
    kind: MailboxItemKind
    content: str
    idempotency_key: str
    metadata: dict[str, str]
    payload: MailboxEnvelopePayload | None
    scheduled_cycle_id: str | None


@dataclasses.dataclass(frozen=True)
class IdleContinuationAdmission:
    """One admitted idle continuation and whether it was newly created."""

    mailbox_item: MailboxItem
    created: bool


@dataclasses.dataclass(frozen=True)
class IdleContinuationFinalization:
    """Committed idle boundary result returned before publication."""

    consumed: bool
    admissions: list[IdleContinuationAdmission]
    continuation_count: int


@dataclasses.dataclass
class IdleContinuationRepository:
    """Own idle eligibility and atomic continuation finalization."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    agent_run_repository: Annotated[
        AgentRunRepository,
        Depends(AgentRunRepository),
    ]
    mailbox_repository: Annotated[
        MailboxRepository,
        Depends(MailboxRepository),
    ]
    scheduled_task_cycle_repository: Annotated[
        ScheduledTaskCycleRepository,
        Depends(ScheduledTaskCycleRepository),
    ]

    async def get_eligibility(
        self,
        session_id: str,
        run_id: str,
        *,
        owner_generation: int,
    ) -> IdleBoundaryEligibility:
        """Return completed pre-hook true-idle eligibility."""
        async with self.session_manager() as session:
            return await self._eligibility(
                session,
                session_id,
                run_id,
                owner_generation=owner_generation,
            )

    async def finalize(
        self,
        *,
        session_id: str,
        run_id: str,
        owner_generation: int,
        inputs: Sequence[IdleContinuationInput],
    ) -> IdleContinuationFinalization:
        """Revalidate, admit continuations, and consume the boundary atomically."""
        try:
            async with self.session_manager() as session:
                eligibility = await self._eligibility(
                    session,
                    session_id,
                    run_id,
                    owner_generation=owner_generation,
                )
                if not eligibility.eligible:
                    return IdleContinuationFinalization(
                        consumed=False,
                        admissions=[],
                        continuation_count=0,
                    )
                accepted = list(inputs)
                if eligibility.archived_cycle_id is not None:
                    accepted = [
                        candidate
                        for candidate in inputs
                        if candidate.scheduled_cycle_id == eligibility.archived_cycle_id
                    ]
                admissions = [
                    await self._enqueue(session, candidate) for candidate in accepted
                ]
                session_repository = self.agent_session_repository
                consumed = await session_repository.consume_pending_idle_continuation(
                    session,
                    session_id=session_id,
                    run_id=run_id,
                    continue_running=bool(accepted),
                    allow_archived_scheduled_continuation=(
                        eligibility.archived_cycle_id is not None
                    ),
                )
                if not consumed:
                    raise _IdleContinuationConsumptionRejected
                return IdleContinuationFinalization(
                    consumed=True,
                    admissions=admissions,
                    continuation_count=len(accepted),
                )
        except _IdleContinuationConsumptionRejected:
            return IdleContinuationFinalization(
                consumed=False,
                admissions=[],
                continuation_count=0,
            )

    async def _eligibility(
        self,
        session: AsyncSession,
        session_id: str,
        run_id: str,
        *,
        owner_generation: int,
    ) -> IdleBoundaryEligibility:
        """Evaluate the canonical true-idle fence in one transaction."""
        locked = await self.agent_session_repository.wait_for_execution_lock_by_id(
            session,
            session_id,
        )
        if locked is None:
            raise ValueError("AgentSession not found")
        if locked.owner_generation != owner_generation:
            raise CanonicalExecutionOwnerGenerationStaleError(
                "Session owner generation is stale during idle continuation"
            )
        archived_cycle_id: str | None = None
        if locked.status is not AgentSessionStatus.ACTIVE:
            if locked.status is not AgentSessionStatus.ARCHIVED:
                return IdleBoundaryEligibility(False, None)
            run = await self.agent_run_repository.get_by_id(session, run_id)
            cycle_id = None if run is None else run.scheduled_task_cycle_id
            if cycle_id is None:
                return IdleBoundaryEligibility(False, None)
            cycle = await self.scheduled_task_cycle_repository.get_started(
                session,
                agent_id=locked.agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if cycle is None or cycle.state.current_run_id != run_id:
                return IdleBoundaryEligibility(False, None)
            archived_cycle_id = cycle_id
        if locked.pending_idle_continuation_run_id != run_id:
            return IdleBoundaryEligibility(False, None)
        if locked.pending_command_id is not None:
            return IdleBoundaryEligibility(False, None)
        pending_wake_input = (
            await self.mailbox_repository.has_by_session_id_and_scheduling_mode(
                session,
                session_id=session_id,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            )
        )
        if pending_wake_input:
            return IdleBoundaryEligibility(False, None)
        active_run = await self.agent_run_repository.get_active_by_session_id(
            session,
            session_id=session_id,
        )
        if active_run is not None:
            return IdleBoundaryEligibility(False, None)
        return IdleBoundaryEligibility(True, archived_cycle_id)

    async def _enqueue(
        self,
        session: AsyncSession,
        input: IdleContinuationInput,
    ) -> IdleContinuationAdmission:
        """Idempotently create one wake-producing continuation."""
        existing = await self.mailbox_repository.get_by_idempotency_key(
            session,
            session_id=input.session_id,
            kind=input.kind,
            idempotency_key=input.idempotency_key,
        )
        if existing is None:
            mailbox_item = await self.mailbox_repository.create_idempotent(
                session,
                MailboxItemCreate(
                    session_id=input.session_id,
                    kind=input.kind,
                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=None,
                    order_sequence=0,
                    content=input.content,
                    idempotency_key=input.idempotency_key,
                    metadata=input.metadata,
                    action=None,
                    attachments=[],
                    file_parts=[],
                    payload=input.payload,
                ),
                idempotency_key=input.idempotency_key,
            )
            created = True
        else:
            mailbox_item = existing
            created = False
        if mailbox_item.scheduling_mode is not MailboxSchedulingMode.WAKE_SESSION:
            raise ValueError(
                "Input idempotency key already used for another scheduling mode"
            )
        if (
            mailbox_item.requested_model_target_label is not None
            or mailbox_item.requested_reasoning_effort is not None
            or mailbox_item.requested_enabled_execution_options
        ):
            raise ValueError(
                "Input idempotency key already used for another inference profile"
            )
        return IdleContinuationAdmission(
            mailbox_item=mailbox_item,
            created=created,
        )
