"""Runtime capability catalog and resolver tests."""

import pytest

from azents.core.enums import AgentRuntimeCapability
from azents.core.runtime_capabilities import (
    RuntimeCapability,
    RuntimeCapabilityResolver,
    RuntimeCapabilitySnapshot,
)


def test_managed_shell_disabled_keeps_non_shell_capabilities() -> None:
    """Managed shell-disabled Agents are not equivalent to Runtime-free Agents."""
    managed = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.MANAGED,
        version=3,
        shell_enabled=False,
    )
    runtime_free = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.NONE,
        version=3,
        shell_enabled=False,
    )

    assert managed.allows(RuntimeCapability.RUNTIME_SETTINGS)
    assert managed.allows(RuntimeCapability.PROJECTS)
    assert not managed.allows(RuntimeCapability.PROCESS_EXECUTION)
    assert not managed.allows(RuntimeCapability.RUNTIME_FILESYSTEM)
    assert not managed.allows(RuntimeCapability.RUNTIME_CREDENTIALS)
    assert not runtime_free.allows(RuntimeCapability.RUNTIME_SETTINGS)


def test_runtime_tool_bundle_requires_shell_gated_capabilities() -> None:
    """The Runtime Toolkit bundle is omitted when shell execution is disabled."""
    resolver = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.MANAGED,
        version=1,
        shell_enabled=False,
    )

    assert not resolver.project(
        (
            RuntimeCapability.WORKSPACE,
            RuntimeCapability.RUNTIME_FILESYSTEM,
            RuntimeCapability.PROCESS_EXECUTION,
        )
    )


@pytest.mark.asyncio
async def test_stale_capability_version_is_rejected() -> None:
    """Authoritative admission rejects a changed Agent capability version."""
    current = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.REMOVING,
        version=4,
        shell_enabled=False,
    )
    resolver = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.MANAGED,
        version=3,
        shell_enabled=True,
        current_snapshot_provider=lambda: _current_snapshot(current),
    )

    decision = await resolver.decide(RuntimeCapability.PROCESS_EXECUTION)

    assert not decision.allowed
    assert decision.reason_code == "runtime_capability_stale"


@pytest.mark.asyncio
async def test_current_snapshot_cannot_expand_captured_authority() -> None:
    """Admission cannot grant authority absent from the captured snapshot."""
    current = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.MANAGED,
        version=3,
        shell_enabled=True,
    )
    resolver = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.NONE,
        version=3,
        shell_enabled=False,
        current_snapshot_provider=lambda: _current_snapshot(current),
    )

    decision = await resolver.decide(RuntimeCapability.RUNTIME_SETTINGS)

    assert not decision.allowed
    assert decision.reason_code == "runtime_capability_unavailable"


async def _current_snapshot(
    resolver: RuntimeCapabilityResolver,
) -> RuntimeCapabilitySnapshot:
    """Return the current snapshot for the stale-version fixture."""
    return resolver.snapshot
