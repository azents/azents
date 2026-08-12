"""Dynamic Worktree Toolkit tests."""

import json
from typing import cast

import pytest

from azents.broker.types import BrokerMessage, SessionBroker, SessionWakeUp
from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.run.turn_action_bridge import TurnActionBridgeBoundary
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.services.session_git_worktree import (
    AgentCreateGitWorktreeAdmission,
    AgentRemoveGitWorktreeAdmission,
    SessionGitWorktreeService,
)

from .dynamic_worktree import DynamicWorktreeToolkit


async def _noop_publish(event: object) -> None:
    """Ignore published events."""
    del event


def _turn_context() -> TurnContext:
    """Create one Toolkit turn context."""
    return TurnContext(
        workspace_id="workspace-1",
        model="test-model",
        run_id="run-1",
        publish_event=_noop_publish,
        session_id="session-1",
    )


class _Service:
    """SessionGitWorktreeService fake for Toolkit tests."""

    def __init__(
        self,
        *,
        available: bool = True,
        remove_available: bool = False,
    ) -> None:
        """Initialize fake state."""
        self.available = available
        self.remove_available = remove_available
        self.admissions: list[dict[str, object]] = []
        self.remove_admissions: list[dict[str, object]] = []
        self.failure: ValueError | None = None

    async def agent_create_git_worktree_available(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> bool:
        """Return configured projection eligibility."""
        assert agent_id == "agent-1"
        assert session_id == "session-1"
        return self.available

    async def agent_remove_git_worktree_available(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> bool:
        """Return configured removal projection eligibility."""
        assert agent_id == "agent-1"
        assert session_id == "session-1"
        return self.remove_available

    async def admit_agent_create_git_worktree(
        self,
        *,
        agent_id: str,
        session_id: str,
        originating_run_id: str,
        client_tool_call_id: str,
        source_project_path: str,
        starting_ref: str | None,
        branch_name: str | None,
    ) -> AgentCreateGitWorktreeAdmission:
        """Record one admission or raise the configured failure."""
        if self.failure is not None:
            raise self.failure
        self.admissions.append(
            {
                "agent_id": agent_id,
                "session_id": session_id,
                "originating_run_id": originating_run_id,
                "client_tool_call_id": client_tool_call_id,
                "source_project_path": source_project_path,
                "starting_ref": starting_ref,
                "branch_name": branch_name,
            }
        )
        return AgentCreateGitWorktreeAdmission(
            mailbox_item_id="mailbox-1",
            bridge_identity="bridge-1",
        )

    async def admit_agent_remove_git_worktree(
        self,
        *,
        agent_id: str,
        session_id: str,
        originating_run_id: str,
        client_tool_call_id: str,
        worktree_project_path: str,
        force: bool,
    ) -> AgentRemoveGitWorktreeAdmission:
        """Record one removal admission or raise the configured failure."""
        if self.failure is not None:
            raise self.failure
        self.remove_admissions.append(
            {
                "agent_id": agent_id,
                "session_id": session_id,
                "originating_run_id": originating_run_id,
                "client_tool_call_id": client_tool_call_id,
                "worktree_project_path": worktree_project_path,
                "force": force,
            }
        )
        return AgentRemoveGitWorktreeAdmission(
            mailbox_item_id="mailbox-remove-1",
            bridge_identity="bridge-remove-1",
        )


class _Broker:
    """SessionBroker fake for Toolkit tests."""

    def __init__(self) -> None:
        """Initialize fake state."""
        self.activities: list[str] = []
        self.messages: list[BrokerMessage] = []

    async def notify_mailbox_activity(self, session_id: str) -> None:
        """Record owner activity notification."""
        self.activities.append(session_id)

    async def send_message(self, message: BrokerMessage) -> None:
        """Record durable broker routing."""
        self.messages.append(message)


def _toolkit(service: _Service, broker: _Broker) -> DynamicWorktreeToolkit:
    """Create a Toolkit with typed production collaborators."""
    return DynamicWorktreeToolkit(
        service=cast(SessionGitWorktreeService, service),
        broker=cast(SessionBroker, broker),
        agent_id="agent-1",
        session_id="session-1",
    )


@pytest.mark.asyncio
async def test_projects_create_tool_only_when_current_session_is_eligible() -> None:
    """Eligibility changes only the projected tool list."""
    service = _Service(available=False)
    toolkit = _toolkit(service, _Broker())

    disabled = await toolkit.update_context(_turn_context())
    service.available = True
    enabled = await toolkit.update_context(_turn_context())

    assert disabled.status is ToolkitStatus.ENABLED
    assert disabled.tools == []
    assert enabled.status is ToolkitStatus.ENABLED
    assert [tool.spec.name for tool in enabled.tools] == ["create_git_worktree"]


@pytest.mark.asyncio
async def test_create_requires_private_run_boundary() -> None:
    """A reconciled Toolkit cannot admit before its Run boundary is injected."""
    toolkit = _toolkit(_Service(), _Broker())
    state = await toolkit.update_context(_turn_context())

    with (
        client_tool_execution_context(call_id="call-1", name="create_git_worktree"),
        pytest.raises(FunctionToolError, match="authority is unavailable"),
    ):
        await state.tools[0].handler(
            json.dumps(
                {
                    "source_project_path": "/workspace/agent/repo",
                    "starting_ref": None,
                    "branch_name": None,
                }
            )
        )


@pytest.mark.asyncio
async def test_create_admits_authoritative_call_and_marks_run_boundary() -> None:
    """Durable admission precedes boundary observation and owner wake routing."""
    service = _Service()
    broker = _Broker()
    toolkit = _toolkit(service, broker)
    boundary = TurnActionBridgeBoundary()
    toolkit.bind_run(run_id="run-42", turn_action_bridge_boundary=boundary)
    state = await toolkit.update_context(_turn_context())

    with client_tool_execution_context(call_id="call-42", name="create_git_worktree"):
        output = await state.tools[0].handler(
            json.dumps(
                {
                    "source_project_path": "/workspace/agent/linked",
                    "starting_ref": " refs/tags/v1 ",
                    "branch_name": " feature/test ",
                }
            )
        )

    assert isinstance(output, str)
    assert service.admissions == [
        {
            "agent_id": "agent-1",
            "session_id": "session-1",
            "originating_run_id": "run-42",
            "client_tool_call_id": "call-42",
            "source_project_path": "/workspace/agent/linked",
            "starting_ref": " refs/tags/v1 ",
            "branch_name": " feature/test ",
        }
    ]
    assert json.loads(output) == {
        "accepted": True,
        "message": (
            "The worktree request was accepted. The authoritative result will "
            "arrive through a fresh continuation Run."
        ),
        "request_id": "mailbox-1",
    }
    observation = boundary.consume()
    assert observation is not None
    assert observation.call_ids == frozenset({"call-42"})
    assert broker.activities == ["session-1"]
    assert broker.messages == [SessionWakeUp(session_id="session-1")]


@pytest.mark.asyncio
async def test_rejected_admission_has_no_boundary_or_wake_side_effect() -> None:
    """An admission failure remains a normal tool error without wake routing."""
    service = _Service()
    service.failure = ValueError("source_project_path must identify a current Project.")
    broker = _Broker()
    toolkit = _toolkit(service, broker)
    boundary = TurnActionBridgeBoundary()
    toolkit.bind_run(run_id="run-1", turn_action_bridge_boundary=boundary)
    state = await toolkit.update_context(_turn_context())

    with (
        client_tool_execution_context(call_id="call-1", name="create_git_worktree"),
        pytest.raises(FunctionToolError, match="current Project"),
    ):
        await state.tools[0].handler(
            json.dumps(
                {
                    "source_project_path": "/workspace/agent/missing",
                    "starting_ref": None,
                    "branch_name": None,
                }
            )
        )

    assert boundary.consume() is None
    assert broker.activities == []
    assert broker.messages == []


@pytest.mark.asyncio
async def test_remove_projects_only_for_current_managed_worktree_context() -> None:
    """Removal appears independently from creation eligibility."""
    service = _Service(available=False, remove_available=True)
    toolkit = _toolkit(service, _Broker())

    state = await toolkit.update_context(_turn_context())

    assert [tool.spec.name for tool in state.tools] == ["remove_git_worktree"]


@pytest.mark.asyncio
async def test_remove_defaults_nonforce_and_marks_run_boundary() -> None:
    """Removal durably admits the exact path before wake and Run handoff."""
    service = _Service(remove_available=True)
    broker = _Broker()
    toolkit = _toolkit(service, broker)
    boundary = TurnActionBridgeBoundary()
    toolkit.bind_run(run_id="run-43", turn_action_bridge_boundary=boundary)
    state = await toolkit.update_context(_turn_context())
    remove_tool = next(
        tool for tool in state.tools if tool.spec.name == "remove_git_worktree"
    )

    with client_tool_execution_context(call_id="call-43", name="remove_git_worktree"):
        output = await remove_tool.handler(
            json.dumps(
                {
                    "worktree_project_path": "/workspace/agent/worktree",
                }
            )
        )

    assert isinstance(output, str)
    assert service.remove_admissions == [
        {
            "agent_id": "agent-1",
            "session_id": "session-1",
            "originating_run_id": "run-43",
            "client_tool_call_id": "call-43",
            "worktree_project_path": "/workspace/agent/worktree",
            "force": False,
        }
    ]
    assert json.loads(output) == {
        "accepted": True,
        "message": (
            "The worktree removal request was accepted. The authoritative result "
            "will arrive through a fresh continuation Run."
        ),
        "request_id": "mailbox-remove-1",
    }
    observation = boundary.consume()
    assert observation is not None
    assert observation.call_ids == frozenset({"call-43"})
    assert broker.activities == ["session-1"]
    assert broker.messages == [SessionWakeUp(session_id="session-1")]
