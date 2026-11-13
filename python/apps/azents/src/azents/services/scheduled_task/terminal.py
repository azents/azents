"""Scheduled result validation over completed terminal database operations."""

from typing import Annotated

from fastapi import Depends

from azents.core.session_resource_authority import SessionExecutionOwner
from azents.repos.scheduled_task_terminal_operations import (
    ScheduledTaskTerminalOperations,
    ScheduledTaskTerminalOutcome,
    ScheduledTaskTerminalStatus,
    get_scheduled_task_terminal_operations,
)


class ScheduledTaskTerminalService:
    """Validate and sequence one idempotent Scheduled Task terminal submission."""

    def __init__(self, *, operations: ScheduledTaskTerminalOperations) -> None:
        self.operations = operations

    def for_execution(
        self, owner: SessionExecutionOwner
    ) -> "ScheduledTaskTerminalService":
        """Bind completed operations to one durable concrete-Session owner."""
        return ScheduledTaskTerminalService(
            operations=self.operations.for_execution(owner)
        )

    async def submit(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        run_id: str,
        cycle_id: str,
        status: ScheduledTaskTerminalStatus,
        result: str,
        notify: bool,
        suppression_reason: str | None,
    ) -> ScheduledTaskTerminalOutcome:
        """Validate text and return after the database operation completes."""
        normalized_result = result.strip()
        if not normalized_result:
            raise ValueError("Scheduled Task result must not be empty.")
        if notify and suppression_reason is not None:
            raise ValueError("A reported result must not include a suppression reason.")
        if not notify and (
            status != "finished"
            or suppression_reason is None
            or not suppression_reason.strip()
        ):
            raise ValueError(
                "Quiet completion requires success and a suppression reason."
            )
        return await self.operations.submit(
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            cycle_id=cycle_id,
            status=status,
            result=normalized_result,
            notify=notify,
            suppression_reason=suppression_reason,
        )


def get_scheduled_task_terminal_service(
    operations: Annotated[
        ScheduledTaskTerminalOperations,
        Depends(get_scheduled_task_terminal_operations),
    ],
) -> ScheduledTaskTerminalService:
    """Wire terminal validation without exposing a raw database session factory."""
    return ScheduledTaskTerminalService(operations=operations)
