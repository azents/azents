"""Runtime execution-policy repository read-contract tests."""

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from .repository import RuntimeExecutionPolicyRepository


@pytest.mark.asyncio
async def test_empty_profile_identity_filter_avoids_unbounded_query() -> None:
    """An explicitly empty Profile scope cannot fall through to list-all."""
    session = Mock(spec=AsyncSession)
    session.scalars = AsyncMock()
    repository = RuntimeExecutionPolicyRepository()

    profiles = await repository.list_profiles(
        session,
        include_retired=True,
        profile_ids=frozenset(),
        offset=0,
        limit=50,
    )

    assert profiles == []
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_list_applies_workspace_and_agent_scope() -> None:
    """Audit reads retain both authorization-scope predicates."""
    scalar_result = Mock()
    scalar_result.all.return_value = []
    session = Mock(spec=AsyncSession)
    session.scalars = AsyncMock(return_value=scalar_result)
    repository = RuntimeExecutionPolicyRepository()

    events = await repository.list_audit_events(
        session,
        management_layer=None,
        target_id=None,
        workspace_id="workspace-1",
        agent_id="agent-1",
        offset=0,
        limit=50,
    )

    assert events == []
    statement = session.scalars.await_args.args[0]
    sql = str(statement)
    assert "runtime_execution_policy_audit_events.workspace_id" in sql
    assert "runtime_execution_policy_audit_events.agent_id" in sql
