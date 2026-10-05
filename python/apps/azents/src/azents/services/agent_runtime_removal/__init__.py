"""Durable Agent Runtime removal confirmation and coordinator."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated, Protocol

from fastapi import Depends

from azents.broker.deps import get_broker
from azents.broker.types import SessionStopSignal
from azents.core.agent_runtime_removal import (
    AgentRuntimeRemovalConfirmationRequest,
    AgentRuntimeRemovalConfirmationResult,
)
from azents.core.enums import AgentRuntimeRemovalStage
from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.agent_runtime_removal.operations import (
    AgentRuntimeRemovalCleanupProgress,
    AgentRuntimeRemovalOperationsRepository,
)

_LEASE_DURATION = datetime.timedelta(minutes=15)
_RETRY_DELAY = datetime.timedelta(seconds=5)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_OPERATION_LIMIT = 100

_DEADLINE_SAFETY_MARGIN = datetime.timedelta(seconds=30)

logger = logging.getLogger(__name__)


class AgentRuntimeRemovalBroker(Protocol):
    """Best-effort Session stop wake-up transport."""

    async def send_message(self, signal: SessionStopSignal) -> None:
        """Send one Session stop wake-up."""
        ...


@dataclasses.dataclass(frozen=True)
class AgentRuntimeRemovalCoordinatorSummary:
    """Result of one bounded Runtime removal scheduler pass."""

    claimed_count: int
    completed_count: int
    retry_scheduled_count: int
    deadline_reached: bool
    limit_reached: bool


class AgentRuntimeRemovalService:
    """Confirm and advance irreversible Agent Runtime removal."""

    def __init__(
        self,
        operations: Annotated[
            AgentRuntimeRemovalOperationsRepository,
            Depends(AgentRuntimeRemovalOperationsRepository),
        ],
        broker: Annotated[AgentRuntimeRemovalBroker, Depends(get_broker)],
    ) -> None:
        """Initialize completed removal operations and external wake transport."""
        self.operations = operations
        self.broker = broker

    async def confirm(
        self,
        request: AgentRuntimeRemovalConfirmationRequest,
    ) -> AgentRuntimeRemovalConfirmationResult:
        """Commit the irreversible Agent work fence and durable operation."""
        return await self.operations.confirm(request=request)

    async def coordinate_once(
        self,
        *,
        lease_owner: str,
        deadline: datetime.datetime,
    ) -> AgentRuntimeRemovalCoordinatorSummary:
        """Claim and advance a bounded set of durable removal operations."""
        claimed_count = 0
        completed_count = 0
        retry_scheduled_count = 0
        deadline_reached = False
        for _ in range(_OPERATION_LIMIT):
            now = datetime.datetime.now(datetime.UTC)
            if now + _DEADLINE_SAFETY_MARGIN >= deadline:
                deadline_reached = True
                break
            operation = await self.operations.claim_due(
                now=now,
                lease_owner=lease_owner,
                lease_until=now + _LEASE_DURATION,
            )
            if operation is None:
                break
            claimed_count += 1
            try:
                completed = await self._advance(
                    operation=operation,
                    lease_owner=lease_owner,
                    deadline=deadline,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._retry(
                    operation=operation,
                    lease_owner=lease_owner,
                    error_kind=type(exc).__name__,
                    error_summary=str(exc) or type(exc).__name__,
                )
                retry_scheduled_count += 1
                logger.exception(
                    "Agent Runtime removal failed; retry scheduled",
                    extra={
                        "agent_runtime_removal_operation_id": operation.id,
                        "agent_id": operation.agent_id,
                        "stage": operation.stage.value,
                        "attempt_count": operation.attempt_count,
                    },
                )
                continue
            completed_count += int(completed)
            retry_scheduled_count += int(not completed)
        return AgentRuntimeRemovalCoordinatorSummary(
            claimed_count=claimed_count,
            completed_count=completed_count,
            retry_scheduled_count=retry_scheduled_count,
            deadline_reached=deadline_reached,
            limit_reached=claimed_count == _OPERATION_LIMIT,
        )

    async def _advance(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
        deadline: datetime.datetime,
    ) -> bool:
        """Advance one operation until completion or an external wait."""
        current = operation
        while datetime.datetime.now(datetime.UTC) + _DEADLINE_SAFETY_MARGIN < deadline:
            match current.stage:
                case AgentRuntimeRemovalStage.FENCING:
                    current = await self._set_stage(
                        operation_id=current.id,
                        lease_owner=lease_owner,
                        expected_attempt=current.attempt_count,
                        stage=AgentRuntimeRemovalStage.INTERRUPTING_WORK,
                    )
                case AgentRuntimeRemovalStage.INTERRUPTING_WORK:
                    if await self._interrupt_work(
                        operation=current,
                        lease_owner=lease_owner,
                    ):
                        current = await self._set_stage(
                            operation_id=current.id,
                            lease_owner=lease_owner,
                            expected_attempt=current.attempt_count,
                            stage=AgentRuntimeRemovalStage.CLEANING_PRODUCT_STATE,
                        )
                    else:
                        await self._retry(
                            operation=current,
                            lease_owner=lease_owner,
                            error_kind="active_work_pending",
                            error_summary="Agent work is still stopping.",
                        )
                        return False
                case AgentRuntimeRemovalStage.CLEANING_PRODUCT_STATE:
                    progress = await self._cleanup_product_state(
                        operation=current,
                        lease_owner=lease_owner,
                    )
                    current = progress.operation
                    if not progress.completed:
                        await self._retry(
                            operation=current,
                            lease_owner=lease_owner,
                            error_kind="product_cleanup_pending",
                            error_summary=(
                                "Runtime-owned product cleanup is continuing."
                            ),
                        )
                        return False
                    current = await self._set_stage(
                        operation_id=current.id,
                        lease_owner=lease_owner,
                        expected_attempt=current.attempt_count,
                        stage=AgentRuntimeRemovalStage.DELETING_RUNTIME,
                    )
                case AgentRuntimeRemovalStage.DELETING_RUNTIME:
                    if not await self._delete_runtime(
                        operation=current,
                        lease_owner=lease_owner,
                    ):
                        await self._retry(
                            operation=current,
                            lease_owner=lease_owner,
                            error_kind="physical_deletion_pending",
                            error_summary=(
                                "Authoritative Runtime deletion acknowledgement "
                                "is pending."
                            ),
                        )
                        return False
                    current = await self._set_stage(
                        operation_id=current.id,
                        lease_owner=lease_owner,
                        expected_attempt=current.attempt_count,
                        stage=AgentRuntimeRemovalStage.FINALIZING,
                    )
                case AgentRuntimeRemovalStage.FINALIZING:
                    completed = await self.operations.finalize(
                        operation_id=current.id,
                        lease_owner=lease_owner,
                        expected_attempt=current.attempt_count,
                        now=datetime.datetime.now(datetime.UTC),
                    )
                    if not completed:
                        raise RuntimeError(
                            "Agent Runtime removal lease was lost before finalization"
                        )
                    return True
                case AgentRuntimeRemovalStage.COMPLETED:
                    return True
        await self._retry(
            operation=current,
            lease_owner=lease_owner,
            error_kind="scheduler_deadline",
            error_summary="Runtime removal yielded before the scheduler deadline.",
        )
        return False

    async def _interrupt_work(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
    ) -> bool:
        """Record durable stop fences and send best-effort wake signals."""
        interrupted = await self.operations.interrupt_work(
            operation=operation, lease_owner=lease_owner
        )
        for session_id in interrupted.stop_session_ids:
            try:
                await self.broker.send_message(SessionStopSignal(session_id=session_id))
            except Exception:
                logger.exception(
                    "Agent Runtime removal stop wake-up failed",
                    extra={
                        "agent_runtime_removal_operation_id": operation.id,
                        "agent_id": operation.agent_id,
                    },
                )
        return not interrupted.active_work_remaining

    async def _cleanup_product_state(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
    ) -> AgentRuntimeRemovalCleanupProgress:
        """Process and checkpoint one root-context cleanup page."""
        return await self.operations.cleanup_product_state(
            operation=operation, lease_owner=lease_owner
        )

    async def _delete_runtime(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
    ) -> bool:
        """Observe pending deletion without locking; fence actual target/ack writes."""
        return await self.operations.delete_runtime(
            operation=operation, lease_owner=lease_owner
        )

    async def _set_stage(
        self,
        *,
        operation_id: str,
        lease_owner: str,
        expected_attempt: int,
        stage: AgentRuntimeRemovalStage,
    ) -> AgentRuntimeRemovalOperation:
        """Advance one owned stage and reload its durable evidence."""
        return await self.operations.set_stage(
            operation_id=operation_id,
            lease_owner=lease_owner,
            expected_attempt=expected_attempt,
            stage=stage,
        )

    async def _retry(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
        error_kind: str,
        error_summary: str,
    ) -> None:
        """Release one operation into bounded retry wait."""
        now = datetime.datetime.now(datetime.UTC)
        exponent = min(max(operation.attempt_count - 1, 0), 8)
        delay = min(_RETRY_DELAY * (2**exponent), _MAX_RETRY_DELAY)
        await self.operations.mark_retry(
            operation_id=operation.id,
            lease_owner=lease_owner,
            expected_attempt=operation.attempt_count,
            next_attempt_at=now + delay,
            error_kind=error_kind,
            error_summary=error_summary,
            now=now,
        )
