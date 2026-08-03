"""External Channel root Toolkit tests."""

import json
from typing import cast

import pytest

from azents.core.enums import (
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    SessionIdleHookContext,
)
from azents.engine.run.emit import PublishedEvent
from azents.engine.run.types import (
    TOOL_RESULT_END_TURN_METADATA_KEY,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tools.external_channel import (
    ChannelActionInput,
    ExternalChannelToolkit,
)
from azents.engine.tools.runtime_instruction_context import (
    RuntimeInstructionContext,
    RuntimeInstructionContextStore,
)
from azents.repos.external_channel.work_data import (
    ChannelActionResult,
    ChannelWorkSnapshot,
    ChannelWorkTask,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileDownloadResult,
    ExternalChannelFileTransferService,
)
from azents.services.external_channel.provider_effect import ProviderEffectOutcome
from azents.services.file_storage import FileStorage


def _snapshot(binding_id: str = "binding-1") -> ChannelWorkSnapshot:
    return ChannelWorkSnapshot(
        binding_id=binding_id,
        provider=ExternalChannelProvider.SLACK,
        resource_label="#incident",
        title="Investigating the incident…",
        tasks=[
            ChannelWorkTask(
                id="investigate",
                title="Investigate the incident",
                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                details=None,
                output=None,
                sources=[],
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

    async def execute(self, **kwargs: object) -> ChannelActionResult:
        self.calls.append(kwargs)
        return ChannelActionResult(
            binding_id=str(kwargs["binding_id"]),
            work_status=ExternalChannelWorkStatus.ACTIVE,
            state_revision=4,
            outcomes=(
                ProviderEffectOutcome(
                    operation=ExternalChannelDeliveryOperation.REPLY,
                    part=0,
                    status="failed",
                    reason="resource_unavailable",
                    detail="Slack cannot post to the linked conversation.",
                ),
            ),
        )


class _FileTransferService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.prepare_calls: list[dict[str, object]] = []

    async def download(
        self,
        **kwargs: object,
    ) -> ExternalChannelFileDownloadResult:
        self.calls.append(kwargs)
        return ExternalChannelFileDownloadResult(
            path=str(kwargs["path"]),
            filename="report.csv",
            media_type="text/csv",
            bytes_written=42,
        )

    async def prepare_outbound(
        self,
        **kwargs: object,
    ) -> tuple[ExternalChannelOutboundFileManifest, ...]:
        self.prepare_calls.append(kwargs)
        return (
            ExternalChannelOutboundFileManifest(
                path="/workspace/agent/report.csv",
                filename="report.csv",
                media_type="text/csv",
                expected_size=42,
            ),
        )


def _toolkit(
    service: _ActionService,
    *,
    file_transfer_service: _FileTransferService | None = None,
    file_storage: FileStorage | None = None,
) -> ExternalChannelToolkit:
    transfer = file_transfer_service or _FileTransferService()
    toolkit = ExternalChannelToolkit(
        service=cast(ExternalChannelActionService, service),
        file_transfer_service=cast(ExternalChannelFileTransferService, transfer),
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
    )
    if file_storage is not None:
        store = RuntimeInstructionContextStore()
        store.set(
            RuntimeInstructionContext(
                file_storage=file_storage,
                projects=(),
                transfer_capability=None,
                publication_capability=None,
                provider_delivery_capability=None,
            )
        )
        toolkit.set_runtime_context_store(store)
    return toolkit


async def _publish(event: PublishedEvent) -> None:
    del event


def _turn_context(*, tool_search_enabled: bool = False) -> TurnContext:
    return TurnContext(
        workspace_id="workspace-1",
        model="test-model",
        run_id="run-current",
        publish_event=_publish,
        session_id="session-1",
        tool_search_enabled=tool_search_enabled,
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
                    "title": "Investigating the incident…",
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

    assert isinstance(output, FunctionToolResult)
    assert output.metadata == {}
    payload = json.loads(cast(str, output.output))
    assert payload["state"] == "active"
    assert payload["outcomes"] == [
        {
            "detail": "Slack cannot post to the linked conversation.",
            "operation": "reply",
            "part": 0,
            "reason": "resource_unavailable",
            "status": "failed",
        }
    ]
    assert service.calls[0]["client_tool_call_id"] == "call-42"
    assert service.calls[0]["run_id"] == "run-current"
    assert service.calls[0]["authority"] is None


@pytest.mark.asyncio
async def test_channel_action_finish_returns_generic_end_turn_signal() -> None:
    """A completed finish uses the generic FunctionToolResult lifecycle signal."""
    service = _ActionService([_snapshot()])
    toolkit = _toolkit(service)
    state = await toolkit.update_context(_turn_context())

    with client_tool_execution_context(call_id="call-finish", name="channel_action"):
        output = await state.tools[0].handler(
            json.dumps(
                {
                    "mode": "finish",
                    "binding": "binding-1",
                    "message": "Done.",
                }
            )
        )

    assert isinstance(output, FunctionToolResult)
    assert output.metadata == {TOOL_RESULT_END_TURN_METADATA_KEY: True}


@pytest.mark.asyncio
async def test_download_external_file_uses_current_runtime_storage() -> None:
    """The root-only file Tool passes one opaque locator to the current Runtime."""
    service = _ActionService([_snapshot()])
    file_transfer_service = _FileTransferService()
    file_storage = cast(FileStorage, object())
    toolkit = _toolkit(
        service,
        file_transfer_service=file_transfer_service,
        file_storage=file_storage,
    )
    state = await toolkit.update_context(_turn_context())

    assert [tool.spec.name for tool in state.tools] == [
        "channel_action",
        "download_external_file",
    ]
    output = await state.tools[1].handler(
        json.dumps(
            {
                "file": "external-file:v1:slack:binding-1:::F123",
                "expected_size_bytes": 42,
                "path": "/workspace/agent/report.csv",
                "overwrite": False,
            }
        )
    )

    assert json.loads(cast(str, output)) == {
        "bytes": 42,
        "filename": "report.csv",
        "media_type": "text/csv",
        "path": "/workspace/agent/report.csv",
    }
    assert file_transfer_service.calls == [
        {
            "session_id": "session-1",
            "agent_id": "agent-1",
            "operation_id": "run-current",
            "file": "external-file:v1:slack:binding-1:::F123",
            "expected_size_bytes": 42,
            "path": "/workspace/agent/report.csv",
            "overwrite": False,
            "file_storage": file_storage,
            "transfer_service": None,
            "transfer_target": None,
        }
    ]


@pytest.mark.asyncio
async def test_channel_action_preflights_files_with_current_runtime_storage() -> None:
    """The Tool commits only manifests produced from the current run source."""
    service = _ActionService([_snapshot()])
    file_transfer_service = _FileTransferService()
    file_storage = cast(FileStorage, object())
    toolkit = _toolkit(
        service,
        file_transfer_service=file_transfer_service,
        file_storage=file_storage,
    )
    state = await toolkit.update_context(_turn_context())

    with client_tool_execution_context(call_id="call-files", name="channel_action"):
        await state.tools[0].handler(
            json.dumps(
                {
                    "mode": "continue",
                    "binding": "binding-1",
                    "message": "Attached report.",
                    "files": ["/workspace/agent/report.csv"],
                }
            )
        )

    assert file_transfer_service.prepare_calls == [
        {
            "session_id": "session-1",
            "agent_id": "agent-1",
            "binding_id": "binding-1",
            "paths": ["/workspace/agent/report.csv"],
            "file_storage": file_storage,
            "authority": None,
        }
    ]
    manifests = cast(
        tuple[ExternalChannelOutboundFileManifest, ...],
        service.calls[0]["files"],
    )
    assert manifests[0].path == "/workspace/agent/report.csv"
    assert service.calls[0]["file_storage"] is file_storage
    assert service.calls[0]["authority"] is None


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
                        "title": "Wrapping up the work…",
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


def test_finish_requires_message() -> None:
    """Finish retains its mode-specific final reply requirement."""
    with pytest.raises(ValueError, match="Finish requires a message"):
        ChannelActionInput.model_validate(
            {
                "mode": "finish",
                "binding": "binding-1",
            }
        )


def test_continue_limits_todos_to_available_activity_blocks() -> None:
    """One status card leaves 49 Slack message blocks for Todo cards."""
    with pytest.raises(ValueError, match="at most 49"):
        ChannelActionInput.model_validate(
            {
                "mode": "continue",
                "binding": "binding-1",
                "title": "Reviewing the task list…",
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


def test_channel_action_rejects_empty_file_lists() -> None:
    """An explicit file publication contains at least one Runtime path."""
    with pytest.raises(ValueError, match="at least 1 item"):
        ChannelActionInput.model_validate(
            {
                "mode": "continue",
                "binding": "binding-1",
                "message": "Attached report.",
                "files": [],
            }
        )


@pytest.mark.asyncio
async def test_static_prompt_compaction_and_idle_keep_minimal_channel_context() -> None:
    """Prompt layers retain only discovery and unfinished-work continuity."""
    service = _ActionService([_snapshot("binding-1"), _snapshot("binding-2")])
    toolkit = _toolkit(service)

    direct_prompt = await toolkit.get_static_prompt(_turn_context())
    search_prompt = await toolkit.get_static_prompt(
        _turn_context(tool_search_enabled=True)
    )
    assert "ordinary assistant output is not delivered" in direct_prompt.lower()
    assert "current input explicitly marked" in direct_prompt
    assert "ordinary user input" not in direct_prompt
    assert "Tool Search" not in direct_prompt
    assert "Tool Search" not in search_prompt
    assert "`channel_action` before completing" in search_prompt
    assert search_prompt == direct_prompt
    assert await toolkit.get_dynamic_prompt(_turn_context()) == ""

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
    assert "State revision" not in compacted.summary
    assert "Progress projection" not in compacted.summary
    assert "Latest action" not in compacted.summary
    assert "Latest delivery outcomes" not in compacted.summary

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
    assert set(idle.continuations[0].metadata) == {"source", "active_bindings"}


@pytest.mark.asyncio
async def test_channel_tool_descriptions_own_post_discovery_guidance() -> None:
    """Direct Channel tools retain their invocation and lifecycle guidance."""
    toolkit = _toolkit(
        _ActionService([_snapshot()]),
        file_storage=cast(FileStorage, object()),
    )
    state = await toolkit.update_context(_turn_context())

    channel_action, download_external_file = state.tools
    assert "ordinary user explicitly requests external publication" in (
        channel_action.spec.description
    )
    assert "active binding or prior External Channel history alone" in (
        channel_action.spec.description
    )
    assert "answer the user normally" in channel_action.spec.description
    assert "Use `finish`" in channel_action.spec.description
    assert "Use `continue`" in channel_action.spec.description
    assert "opaque locator" in download_external_file.spec.description

    schema_text = json.dumps(channel_action.spec.input_schema)
    assert channel_action.spec.input_schema["type"] == "object"
    assert "oneOf" not in channel_action.spec.input_schema
    assert "anyOf" not in channel_action.spec.input_schema
    assert "Pass it unchanged" in schema_text
    assert "independent from the session-scoped update_todo list" in schema_text
