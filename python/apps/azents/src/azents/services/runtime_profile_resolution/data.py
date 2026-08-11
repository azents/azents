"""Runtime Profile resolution service contracts."""

import dataclasses

from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationAppliedSlot,
    RuntimeConfigurationSlot,
)


@dataclasses.dataclass
class RuntimeProfileResolutionUnavailable(Exception):
    """Current Agent sources cannot identify one exact Runtime Profile."""

    code: str
    provider_id: str | None
    message: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass(frozen=True)
class RuntimeProfileResolutionResult:
    """Runtime with its authoritative current desired/applied configuration."""

    runtime: AgentRuntime
    desired: RuntimeConfigurationSlot
    applied: RuntimeConfigurationAppliedSlot | None
    runtime_created: bool
