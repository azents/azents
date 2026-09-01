"""Typed evidence and result contracts for effective Terminal policy."""

import dataclasses
import enum

from azents.core.enums import AgentRuntimeCapability
from azents.core.runtime_profile import RuntimeProfileLifecycle


class TerminalPolicyDeniedScope(enum.StrEnum):
    """Source boundary that denied current Terminal use."""

    ACCESS = "access"
    SESSION = "session"
    RUNTIME = "runtime"
    PROVIDER_PROFILE = "provider_profile"
    WORKSPACE_PROFILE = "workspace_profile"
    AGENT = "agent"
    RUNNER = "runner"


class TerminalPolicyReasonCode(enum.StrEnum):
    """Stable fail-closed reason for current Terminal availability."""

    ACCESS_DENIED = "access_denied"
    SESSION_UNAVAILABLE = "session_unavailable"
    RUNTIME_FREE_AGENT = "runtime_free_agent"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    INFRASTRUCTURE_PROFILE_UNAVAILABLE = "infrastructure_profile_unavailable"
    WORKSPACE_PROFILE_UNAVAILABLE = "workspace_profile_unavailable"
    INFRASTRUCTURE_TERMINAL_DISABLED = "infrastructure_terminal_disabled"
    WORKSPACE_TERMINAL_DISABLED = "workspace_terminal_disabled"
    AGENT_TERMINAL_DISABLED = "agent_terminal_disabled"
    RUNTIME_INACTIVE = "runtime_inactive"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    RUNNER_GENERATION_STALE = "runner_generation_stale"
    RUNNER_TERMINAL_UNSUPPORTED = "runner_terminal_unsupported"


@dataclasses.dataclass(frozen=True)
class TerminalPolicyEvidence:
    """Current source rows and volatile Runner evidence for one Session."""

    access_allowed: bool
    session_available: bool
    agent_id: str
    agent_terminal_enabled: bool
    runtime_capability: AgentRuntimeCapability
    runtime_id: str | None
    runtime_active: bool
    desired_generation: int | None
    infrastructure_profile_id: str | None
    infrastructure_profile_version: int | None
    infrastructure_profile_lifecycle: RuntimeProfileLifecycle | None
    infrastructure_profile_available: bool
    infrastructure_terminal_enabled: bool | None
    workspace_profile_id: str | None
    workspace_profile_version: int | None
    workspace_profile_lifecycle: RuntimeProfileLifecycle | None
    workspace_profile_available: bool
    workspace_terminal_enabled: bool | None
    runner_generation: int | None
    expected_runner_generation: int | None
    runner_active: bool
    runner_capabilities: frozenset[str]


@dataclasses.dataclass(frozen=True)
class TerminalPolicySourceVersions:
    """Exact durable source versions used by one policy decision."""

    agent_id: str
    infrastructure_profile_id: str | None
    infrastructure_profile_version: int | None
    workspace_profile_id: str | None
    workspace_profile_version: int | None


@dataclasses.dataclass(frozen=True)
class TerminalPolicyResolution:
    """Server-authored effective Terminal permission."""

    available: bool
    reason_code: TerminalPolicyReasonCode | None
    denied_scope: TerminalPolicyDeniedScope | None
    sources: TerminalPolicySourceVersions
    runtime_id: str | None
    desired_generation: int | None
    runner_generation: int | None
