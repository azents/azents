"""Agent decommission finalizer lifecycle-root tests."""

# pyright: reportPrivateUsage=false

from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
    _terminal_delete_pending,
)


class _ExistsSessionDouble:
    """Capture lifecycle-root checks without requiring an RDB fixture."""

    def __init__(self, results: list[bool]) -> None:
        self.results = results
        self.statements: list[str] = []

    async def scalar(self, statement: object) -> bool:
        """Return deterministic existence results in repository check order."""
        self.statements.append(str(statement))
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_finalizer_rejects_remaining_external_channel_route() -> None:
    """An Agent route remains a hard finalization fence after Session purge."""
    session = cast(AsyncSession, _ExistsSessionDouble([False] * 6 + [True]))

    with pytest.raises(
        RuntimeError,
        match="ExternalChannelAgentRoute lifecycle root remains",
    ):
        repository = AgentDecommissionFinalizerRepository()
        await repository._require_absent_lifecycle_roots(
            session,
            agent_id="agent-1",
        )


@pytest.mark.asyncio
async def test_finalizer_does_not_treat_workspace_connection_as_agent_root() -> None:
    """Workspace-owned External Channel connections remain outside Agent cleanup."""
    session_double = _ExistsSessionDouble([False] * 15)
    session = cast(AsyncSession, session_double)

    repository = AgentDecommissionFinalizerRepository()
    await repository._require_absent_lifecycle_roots(
        session,
        agent_id="agent-1",
    )

    checked_sql = "\n".join(session_double.statements)
    assert "external_channel_connections" not in checked_sql


def test_resource_binding_requires_generation_fenced_terminal_acknowledgement() -> None:
    """A resource-bound Runtime cannot bypass acknowledgement via logical ID."""
    acknowledged = cast(
        RDBAgentRuntime,
        SimpleNamespace(
            runtime_provider_id=None,
            runtime_provider_resource_id="provider-resource-1",
            desired_generation=4,
            terminal_delete_requested_generation=4,
            terminal_delete_acknowledged_generation=4,
        ),
    )
    stale = cast(
        RDBAgentRuntime,
        SimpleNamespace(
            runtime_provider_id=None,
            runtime_provider_resource_id="provider-resource-1",
            desired_generation=4,
            terminal_delete_requested_generation=4,
            terminal_delete_acknowledged_generation=3,
        ),
    )

    assert not _terminal_delete_pending(acknowledged)
    assert _terminal_delete_pending(stale)
