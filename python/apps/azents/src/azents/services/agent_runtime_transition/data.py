"""Agent Runtime transition service data."""

import dataclasses

from pydantic import BaseModel, Field

from azents.repos.agent.data import Agent
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_runtime_add.data import AgentRuntimeAddReceipt
from azents.repos.runtime_profile.data import RuntimeConfigurationRevision


class AgentRuntimeAdditionRequest(BaseModel):
    """One explicit administrator-confirmed Runtime addition."""

    agent_id: str = Field(description="Target Agent ID")
    workspace_runtime_profile_id: str = Field(
        description="Explicit Workspace Runtime Profile ID"
    )
    expected_capability_version: int = Field(ge=1)
    expected_runtime_profile_selection_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=120)


@dataclasses.dataclass(frozen=True)
class AgentRuntimeAdditionResult:
    """Committed or replayed Runtime addition evidence."""

    agent: Agent
    runtime: AgentRuntime
    desired_revision: RuntimeConfigurationRevision
    receipt: AgentRuntimeAddReceipt
    replayed: bool


class AgentRuntimeAdditionUnavailable(Exception):
    """The requested explicit Runtime addition cannot be committed."""

    def __init__(self, *, code: str, message: str) -> None:
        """Initialize one bounded transition failure."""
        super().__init__(message)
        self.code = code
