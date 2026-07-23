"""External Channel root Toolkit tests."""

import datetime
import json
from typing import cast

import pytest

from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)
from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    SessionIdleHookContext,
)
from azents.engine.run.emit import PublishedEvent
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tools.external_channel import (
    ContinueChannelActionInput,
    ExternalChannelToolkit,
    render_channel_work_prompt,
)
from azents.repos.external_channel.work_data import (
    ChannelActionCommit,
    ChannelWorkDelivery,
    ChannelWorkSnapshot,
    ChannelWorkTask,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)


def _at(second: int) -> datetime.datetime:
    return datetime.datetime(2026, 7, 22, 0, 0, second, tzinfo=datetime.UTC)


def _snapshot(binding_id: str = "binding-1") -> ChannelWorkSnapshot:
    return ChannelWorkSnapshot(
        binding_id=binding_id,
        provider=ExternalChannelProvider.SLACK,
        resource_label="#incident",
        tasks=[
            ChannelWorkTask(
                id="investigate",
                title="Investigate the incident",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
            )
        ],
        state_revision=3,
        desired_progress_revision=2,
        progress_provider_message_key="slack:T1:C1:2.000001",
        projection_drift="synchronized",
        latest_action_mode=ExternalChannelActionMode.CONTINUE,
        latest_deliveries=[
            ChannelWorkDelivery(
                id="delivery-1",
                operation=ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
                status=ExternalChannelDeliveryStatus.DELIVERED,
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
                created_at=_at(1),
                completed_at=_at(2),
            )
        ],
    )


class _ActionService:
    def __init__(self, snapshots: list[ChannelWorkSnapshot]) -> None:
        self.snapshots = snapshots
        self.calls: list[dict[str, object]] = []

    async def has_active_binding(self, *, session_id: str, agent_id: str) -> bool:
        del session_id, agent_id
        return bool(self.snapshots)

    async def snapshot(
        self,
        *,
        session_id: str,
        agent_id: str,
    ) -> list[ChannelWorkSnapshot]:
        del session_id, agent_id
        return self.snapshots

    async def execute(self, **kwargs: object) -> ChannelActionCommit:
        self.calls.append(kwargs)
        return ChannelActionCommit(
            action_id="action-1",
            binding_id=str(kwargs["binding_id"]),
            work_id="work-1",
            work_status=ExternalChannelWorkStatus.ACTIVE,
            state_revision=4,
            deliveries=[
                ChannelWorkDelivery(
                    id="delivery-2",
                    operation=ExternalChannelDeliveryOperation.REPLY,
                    status=ExternalChannelDeliveryStatus.FAILED,
                    provider_message_key=None,
                    error_kind="resource_unavailable",
                    error_summary="Slack cannot post to the linked conversation.",
                    created_at=_at(3),
                    completed_at=_at(4),
                )
            ],
        )


def _toolkit(service: _ActionService) -> ExternalChannelToolkit:
    return ExternalChannelToolkit(
        service=cast(ExternalChannelActionService, service),
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
    )


async def _publish(event: PublishedEvent) -> None:
    del event


def _turn_context() -> TurnContext:
    return TurnContext(
        user_id=None,
        workspace_id="workspace-1",
        model="test-model",
        run_id="run-current",
        publish_event=_publish,
        session_id="session-1",
    )


@pytest.mark.asyncio
async def test_channel_action_uses_durable_client_call_identity() -> None:
    """The unprefixed tool commits the exact provider call ID and returns failure."""
    service = _ActionService([_snapshot()])
    toolkit = _toolkit(service)
    state = await toolkit.update_context(_turn_context())

    assert state.status is ToolkitStatus.ENABLED
    assert [tool.spec.name for tool in state.tools] == ["channel_action"]
    with client_tool_execution_context(call_id="call-42", name="channel_action"):
        output = await state.tools[0].handler(
            json.dumps(
                {
                    "mode": "continue",
                    "binding": "binding-1",
                    "message": "I am investigating.",
                    "todo_update": [
                        {
                            "id": "investigate",
                            "title": "Investigate the incident",
                            "status": "in_progress",
                        }
                    ],
                }
            )
        )

    assert isinstance(output, str)
    payload = json.loads(output)
    assert payload["state"] == "active"
    assert payload["deliveries"] == [
        {
            "detail": "Slack cannot post to the linked conversation.",
            "operation": "reply",
            "reason": "resource_unavailable",
            "status": "failed",
        }
    ]
    assert service.calls[0]["client_tool_call_id"] == "call-42"
    assert service.calls[0]["run_id"] == "run-current"


@pytest.mark.asyncio
async def test_continue_requires_unfinished_work() -> None:
    """Continue cannot leave the binding with only completed tasks."""
    toolkit = _toolkit(_ActionService([_snapshot()]))
    state = await toolkit.update_context(_turn_context())

    with client_tool_execution_context(call_id="call-1", name="channel_action"):
        with pytest.raises(FunctionToolError, match="unfinished task"):
            await state.tools[0].handler(
                json.dumps(
                    {
                        "mode": "continue",
                        "binding": "binding-1",
                        "todo_update": [
                            {
                                "id": "done",
                                "title": "Already done",
                                "status": "completed",
                            }
                        ],
                    }
                )
            )


def test_continue_limits_todos_to_available_activity_blocks() -> None:
    """One status card leaves 49 Slack message blocks for Todo cards."""
    with pytest.raises(ValueError, match="at most 49"):
        ContinueChannelActionInput.model_validate(
            {
                "mode": "continue",
                "binding": "binding-1",
                "todo_update": [
                    {
                        "id": f"task-{index}",
                        "title": f"Task {index}",
                        "status": "pending",
                    }
                    for index in range(50)
                ],
            }
        )


@pytest.mark.asyncio
async def test_prompt_compaction_and_idle_include_every_active_binding() -> None:
    """Turn, compaction, and continuation paths share canonical binding state."""
    service = _ActionService([_snapshot("binding-1"), _snapshot("binding-2")])
    toolkit = _toolkit(service)

    prompt = await toolkit.get_dynamic_prompt(_turn_context())
    assert "ordinary assistant output is not sent" in prompt.lower()
    assert "`binding-1`" in prompt
    assert "`binding-2`" in prompt
    assert prompt == render_channel_work_prompt(service.snapshots)

    compacted = await toolkit._on_compaction_summary(  # pyright: ignore[reportPrivateUsage]
        CompactionSummaryHookContext(
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id="session-1",
            run_id="run-1",
            compaction_id="compaction-1",
            reason=None,
            covered_until_event_id="event-1",
            summary="Base summary",
            continuity_history="",
        )
    )
    assert compacted is not None
    assert compacted.summary.count("## Channel Work Snapshot") == 1
    assert "binding-2" in compacted.summary

    idle = await toolkit._on_session_idle(  # pyright: ignore[reportPrivateUsage]
        SessionIdleHookContext(
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id="session-1",
            run_id="run-1",
            reason="completed",
        )
    )
    assert idle is not None
    assert len(idle.continuations) == 1
    assert idle.continuations[0].metadata["active_bindings"] == ("binding-1,binding-2")
