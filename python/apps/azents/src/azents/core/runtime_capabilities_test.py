"""Runtime capability catalog and resolver tests."""

import pytest

from azents.core.enums import AgentRuntimeCapability
from azents.core.runtime_capabilities import (
    RuntimeCapability,
    RuntimeCapabilityResolver,
    RuntimeCapabilitySnapshot,
)


def test_managed_runtime_grants_all_runtime_capabilities() -> None:
    """Managed Agents receive every server-declared Runtime capability."""
    managed = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.MANAGED,
        version=3,
    )

    assert managed.granted_capabilities() == frozenset(RuntimeCapability)


def test_non_managed_runtime_denies_all_runtime_capabilities() -> None:
    """Runtime-free and removing Agents receive no Runtime capability."""
    runtime_free = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.NONE,
        version=3,
    )
    removing = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.REMOVING,
        version=4,
    )

    assert runtime_free.granted_capabilities() == frozenset()
    assert removing.granted_capabilities() == frozenset()
    assert not runtime_free.project(tuple(RuntimeCapability))
    assert not removing.allows(RuntimeCapability.PROCESS_EXECUTION)


def test_runtime_tool_bundle_projects_from_managed_runtime() -> None:
    """The Runtime Toolkit bundle follows managed Runtime authority."""
    resolver = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.MANAGED,
        version=1,
    )

    assert resolver.project(
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
    )
    resolver = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.MANAGED,
        version=3,
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
    )
    resolver = RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.NONE,
        version=3,
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
