"""Public deletion status derives from canonical lifecycle and bounded evidence."""

import pytest

from azents.core.agent_deletion import AgentDeletionStatus
from azents.core.enums import AgentLifecycleStatus
from azents.repos.agent_operations_test import _agent
from azents.services.agent import AgentService


@pytest.mark.parametrize(
    "lifecycle,errors,expected",
    [
        (AgentLifecycleStatus.ACTIVE, {}, None),
        (AgentLifecycleStatus.ACTIVE, {"agent-1": True}, None),
        (
            AgentLifecycleStatus.DECOMMISSIONING,
            {"agent-1": False},
            AgentDeletionStatus.DELETING,
        ),
        (
            AgentLifecycleStatus.DECOMMISSIONING,
            {"agent-1": True},
            AgentDeletionStatus.ERROR,
        ),
        (AgentLifecycleStatus.DECOMMISSIONING, {}, AgentDeletionStatus.ERROR),
    ],
)
def test_safe_projection(
    lifecycle: AgentLifecycleStatus,
    errors: dict[str, bool],
    expected: AgentDeletionStatus | None,
) -> None:
    agent = _agent().model_copy(update={"lifecycle_status": lifecycle})
    assert AgentService._deletion_status(agent, errors) is expected
