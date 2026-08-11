"""Agent Runtime removal service data models."""

from pydantic import BaseModel, Field

from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.agent_runtime_removal_scope.data import AgentRuntimeRemovalImpact


class AgentRuntimeRemovalConfirmationRequest(BaseModel):
    """Internal final-confirmation request for irreversible Runtime removal."""

    agent_id: str = Field(description="Target Agent ID")
    workspace_id: str = Field(description="Owning Workspace ID")
    requested_by_workspace_user_id: str = Field(
        description="Workspace User confirming removal"
    )
    idempotency_key: str = Field(min_length=1, max_length=120)
    expected_capability_version: int = Field(ge=1)
    expected_runtime_profile_selection_version: int = Field(ge=1)


class AgentRuntimeRemovalConfirmationResult(BaseModel):
    """Committed Runtime removal operation and content-free impact."""

    operation: AgentRuntimeRemovalOperation
    impact: AgentRuntimeRemovalImpact
    replayed: bool


class AgentRuntimeRemovalUnavailable(RuntimeError):
    """Stable internal removal-admission failure."""

    def __init__(self, *, code: str, message: str) -> None:
        """Initialize a bounded removal failure."""
        super().__init__(message)
        self.code = code
        self.message = message
