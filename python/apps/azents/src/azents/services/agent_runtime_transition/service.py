"""Explicit Agent Runtime addition through one completed atomic repository owner."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.agent_runtime_transition_operations import (
    AgentRuntimeAdditionCommand,
    AgentRuntimeAdditionRejected,
    AgentRuntimeTransitionOperationRepository,
)
from azents.services.agent_runtime_transition.data import (
    AgentRuntimeAdditionRequest,
    AgentRuntimeAdditionResult,
    AgentRuntimeAdditionUnavailable,
)


@dataclasses.dataclass
class AgentRuntimeTransitionService:
    """Project committed addition/replay evidence without opening DB scopes."""

    operations: Annotated[
        AgentRuntimeTransitionOperationRepository,
        Depends(AgentRuntimeTransitionOperationRepository),
    ]

    async def add_runtime(
        self, request: AgentRuntimeAdditionRequest
    ) -> AgentRuntimeAdditionResult:
        """Commit all capability/source/Runtime/receipt changes or none of them."""
        try:
            record = await self.operations.add_runtime(
                AgentRuntimeAdditionCommand(
                    agent_id=request.agent_id,
                    workspace_runtime_profile_id=request.workspace_runtime_profile_id,
                    expected_capability_version=request.expected_capability_version,
                    expected_runtime_profile_selection_version=(
                        request.expected_runtime_profile_selection_version
                    ),
                    idempotency_key=request.idempotency_key,
                )
            )
        except AgentRuntimeAdditionRejected as error:
            raise AgentRuntimeAdditionUnavailable(
                code=error.code, message=str(error)
            ) from error
        return AgentRuntimeAdditionResult(
            agent=record.agent,
            runtime=record.runtime,
            desired=record.desired,
            receipt=record.receipt,
            replayed=record.replayed,
        )

    def completed_removal_authorizes_rearm(
        self,
        operation: AgentRuntimeRemovalOperation | None,
        runtime: AgentRuntime,
    ) -> bool:
        """Project the unchanged pure completed-removal evidence predicate."""
        return self.operations.completed_removal_authorizes_rearm(operation, runtime)
