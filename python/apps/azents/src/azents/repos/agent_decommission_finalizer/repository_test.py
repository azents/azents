"""Agent decommission finalizer lifecycle-root tests."""

import pytest

from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
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
    session = _ExistsSessionDouble([False] * 6 + [True])

    with pytest.raises(
        RuntimeError,
        match="ExternalChannelAgentRoute lifecycle root remains",
    ):
        await AgentDecommissionFinalizerRepository()._require_absent_lifecycle_roots(  # pyright: ignore[reportPrivateUsage]  # Pin finalizer root fence.
            session,  # type: ignore[arg-type]
            agent_id="agent-1",
        )


@pytest.mark.asyncio
async def test_finalizer_does_not_treat_workspace_connection_as_agent_root() -> None:
    """Workspace-owned External Channel connections remain outside Agent cleanup."""
    session = _ExistsSessionDouble([False] * 15)

    await AgentDecommissionFinalizerRepository()._require_absent_lifecycle_roots(  # pyright: ignore[reportPrivateUsage]  # Pin Workspace ownership boundary.
        session,  # type: ignore[arg-type]
        agent_id="agent-1",
    )

    checked_sql = "\n".join(session.statements)
    assert "external_channel_connections" not in checked_sql
