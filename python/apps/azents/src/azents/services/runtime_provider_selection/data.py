"""Runtime Provider selection service contracts."""

import dataclasses

from azents.core.enums import RuntimeProviderBindingOrigin
from azents.repos.agent_runtime.data import AgentRuntime


@dataclasses.dataclass(frozen=True)
class RuntimeProviderSelectionUnavailable(Exception):
    """The requested exact Provider candidate cannot provision a Runtime."""

    code: str
    provider_id: str | None
    message: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass(frozen=True)
class RuntimeProviderSelection:
    """Resolved Provider candidate and immutable binding provenance."""

    provider_resource_id: str
    provider_logical_id: str
    binding_origin: RuntimeProviderBindingOrigin
    binding_evidence: dict[str, object]


@dataclasses.dataclass(frozen=True)
class RuntimeProviderBindingResult:
    """Result of one transactional Runtime binding attempt."""

    runtime: AgentRuntime
    created: bool
    selection: RuntimeProviderSelection | None
