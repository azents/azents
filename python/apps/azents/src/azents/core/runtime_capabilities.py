"""Server-owned Runtime capability catalog and resolver."""

import dataclasses
import enum
from collections.abc import Awaitable, Callable, Iterable

from azents.core.enums import AgentRuntimeCapability


class RuntimeCapability(enum.StrEnum):
    """Stable product capability identifiers for Runtime-dependent surfaces."""

    PROCESS_EXECUTION = "process_execution"
    RUNTIME_FILESYSTEM = "runtime_filesystem"
    WORKSPACE = "workspace"
    PROJECTS = "projects"
    GIT_WORKTREES = "git_worktrees"
    FILESYSTEM_SKILLS = "filesystem_skills"
    RUNTIME_TRANSFER = "runtime_transfer"
    RUNTIME_SETTINGS = "runtime_settings"
    RUNTIME_CREDENTIALS = "runtime_credentials"


@dataclasses.dataclass(frozen=True)
class RuntimeCapabilitySnapshot:
    """Immutable Agent capability/version input to Runtime resolution."""

    state: AgentRuntimeCapability
    version: int

    def __post_init__(self) -> None:
        """Validate the durable snapshot values."""
        if self.version < 1:
            raise ValueError("Runtime capability version must be positive.")


RuntimeCapabilitySnapshotProvider = Callable[[], Awaitable[RuntimeCapabilitySnapshot]]


@dataclasses.dataclass(frozen=True)
class RuntimeCapabilityDefinition:
    """Code-owned policy for one product Runtime capability."""

    capability: RuntimeCapability


RUNTIME_CAPABILITY_CATALOG: dict[RuntimeCapability, RuntimeCapabilityDefinition] = {
    capability: RuntimeCapabilityDefinition(capability=capability)
    for capability in RuntimeCapability
}
"""All Runtime capability definitions declared by the server."""


class RuntimeCapabilityDeniedError(RuntimeError):
    """Raised when a Runtime-dependent operation is not currently authorized."""

    def __init__(
        self,
        capability: RuntimeCapability,
        *,
        reason_code: str,
        expected_version: int,
        actual_version: int,
    ) -> None:
        """Create a stable, content-free capability failure."""
        super().__init__(f"Runtime capability is unavailable: {capability.value}.")
        self.capability = capability
        self.reason_code = reason_code
        self.expected_version = expected_version
        self.actual_version = actual_version


@dataclasses.dataclass(frozen=True)
class RuntimeCapabilityDecision:
    """Pure resolver result for one capability request."""

    allowed: bool
    capability: RuntimeCapability
    reason_code: str | None
    expected_version: int
    actual_version: int


class RuntimeCapabilityResolver:
    """Resolve one immutable capability snapshot for projection and admission."""

    def __init__(
        self,
        snapshot: RuntimeCapabilitySnapshot,
        *,
        current_snapshot_provider: RuntimeCapabilitySnapshotProvider | None = None,
    ) -> None:
        """Create a resolver bound to one Agent capability snapshot."""
        self.snapshot = snapshot
        self.current_snapshot_provider = current_snapshot_provider

    @classmethod
    def from_agent(
        cls,
        *,
        state: AgentRuntimeCapability,
        version: int,
        current_snapshot_provider: RuntimeCapabilitySnapshotProvider | None = None,
    ) -> "RuntimeCapabilityResolver":
        """Create a resolver from the Agent row's capability fields."""
        return cls(
            RuntimeCapabilitySnapshot(
                state=state,
                version=version,
            ),
            current_snapshot_provider=current_snapshot_provider,
        )

    def granted_capabilities(self) -> frozenset[RuntimeCapability]:
        """Return capabilities granted by the immutable Agent snapshot."""
        if self.snapshot.state is not AgentRuntimeCapability.MANAGED:
            return frozenset()
        return frozenset(RUNTIME_CAPABILITY_CATALOG)

    def allows(self, capability: RuntimeCapability) -> bool:
        """Return whether the captured snapshot grants one capability."""
        return capability in self.granted_capabilities()

    def project(
        self,
        capabilities: Iterable[RuntimeCapability],
    ) -> bool:
        """Return whether every declared capability is granted for projection."""
        return all(self.allows(capability) for capability in capabilities)

    async def decide(
        self,
        capability: RuntimeCapability,
    ) -> RuntimeCapabilityDecision:
        """Resolve one capability against current Agent state when available."""
        captured_allowed = self.allows(capability)
        current = self.snapshot
        if self.current_snapshot_provider is not None:
            current = await self.current_snapshot_provider()
        if current.version != self.snapshot.version:
            return RuntimeCapabilityDecision(
                allowed=False,
                capability=capability,
                reason_code="runtime_capability_stale",
                expected_version=self.snapshot.version,
                actual_version=current.version,
            )
        allowed = captured_allowed and current.state is AgentRuntimeCapability.MANAGED
        return RuntimeCapabilityDecision(
            allowed=allowed,
            capability=capability,
            reason_code=None if allowed else "runtime_capability_unavailable",
            expected_version=self.snapshot.version,
            actual_version=current.version,
        )

    async def require(self, capability: RuntimeCapability) -> None:
        """Require one capability before Runtime or credential side effects."""
        decision = await self.decide(capability)
        if decision.allowed:
            return
        raise RuntimeCapabilityDeniedError(
            capability,
            reason_code=decision.reason_code or "runtime_capability_unavailable",
            expected_version=decision.expected_version,
            actual_version=decision.actual_version,
        )
