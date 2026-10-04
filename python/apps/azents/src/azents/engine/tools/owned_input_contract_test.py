"""Runtime and native-schema contracts for strict owned tool input models."""

import json

import pytest
from pydantic import BaseModel

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.tools import _native_tool_declaration
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tooling.tool_search import ToolSearchInput
from azents.engine.tools.builtin import ExecCommandInput, WriteStdinInput
from azents.engine.tools.external_channel import (
    ChannelActionInput,
    ChannelActionSourceInput,
    ChannelActionTaskInput,
    DownloadExternalFileInput,
)
from azents.engine.tools.github import GitHubSwitchInstallationInput
from azents.engine.tools.glob import GlobInput
from azents.engine.tools.goal import CreateGoalInput, UpdateGoalInput
from azents.engine.tools.grep import GrepInput
from azents.engine.tools.import_file import ImportFileInput
from azents.engine.tools.kubernetes import (
    K8sApiResourcesInput,
    K8sApplyInput,
    K8sDeleteInput,
    K8sEventsInput,
    K8sExecInput,
    K8sGetInput,
    K8sListInput,
    K8sLogsInput,
)
from azents.engine.tools.memory import DeleteMemoryInput, SaveMemoryInput
from azents.engine.tools.present_file import PresentFileInput
from azents.engine.tools.read_image import ReadImageInput
from azents.engine.tools.read_text import ReadTextInput
from azents.engine.tools.run_tool_to_file import RunToolToFileInput
from azents.engine.tools.scheduled import (
    AddScheduledTaskInput,
    DeleteScheduledTaskInput,
    SubmitScheduledTaskResultInput,
)
from azents.engine.tools.skill import LoadSkillInput
from azents.engine.tools.subagent import (
    FollowupTaskInput,
    InterruptAgentInput,
    SendMessageInput,
    SpawnAgentInput,
)
from azents.engine.tools.write import WriteInput


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ToolSearchInput, {"query": "files"}),
        (ExecCommandInput, {"command": "echo ok"}),
        (WriteStdinInput, {"process_id": "process-1", "chars": ""}),
        (GlobInput, {"pattern": "/workspace/agent/*"}),
        (GrepInput, {"pattern": "text", "path": "/workspace/agent"}),
        (
            SaveMemoryInput,
            {
                "scope": "agent",
                "type": "feedback",
                "name": "brief",
                "description": "Brief",
                "content": "Be brief.",
            },
        ),
        (DeleteMemoryInput, {"scope": "agent", "name": "brief"}),
        (ReadTextInput, {"path": "/workspace/agent/file.txt", "offset": 0}),
        (
            SpawnAgentInput,
            {"name": "child", "task": "Inspect", "model_target_label": None},
        ),
        (SendMessageInput, {"agent_name": "child", "message": "Hello"}),
        (FollowupTaskInput, {"agent_name": "child", "task": "Continue"}),
        (InterruptAgentInput, {"agent_name": "child"}),
        (ChannelActionSourceInput, {"url": "https://example.test", "label": "Source"}),
        (
            ChannelActionTaskInput,
            {"id": "task-1", "title": "Task", "status": "pending"},
        ),
        (ChannelActionInput, {"mode": "ignore", "binding": "active"}),
        (DownloadExternalFileInput, {"file": "opaque-file", "path": "/runtime/f"}),
        (GitHubSwitchInstallationInput, {"installation": "123"}),
        (CreateGoalInput, {"objective": "Inspect"}),
        (UpdateGoalInput, {"status": "complete"}),
        (ImportFileInput, {"uri": "exchange://object", "path": None}),
        (K8sListInput, {"cluster": "home", "kind": "Pod"}),
        (K8sGetInput, {"cluster": "home", "kind": "Pod", "name": "pod"}),
        (K8sLogsInput, {"cluster": "home", "pod": "pod"}),
        (K8sEventsInput, {"cluster": "home"}),
        (K8sApiResourcesInput, {"cluster": "home"}),
        (K8sApplyInput, {"cluster": "home", "manifest": "kind: Pod"}),
        (K8sDeleteInput, {"cluster": "home", "kind": "Pod", "name": "pod"}),
        (K8sExecInput, {"cluster": "home", "pod": "pod", "command": ["true"]}),
        (PresentFileInput, {"paths": ["/runtime/file"]}),
        (ReadImageInput, {"path": "/runtime/image.png"}),
        (
            RunToolToFileInput,
            {"tool_name": "search", "arguments": "{}", "directory": "/runtime/out"},
        ),
        (
            AddScheduledTaskInput,
            {
                "title": "Inspect",
                "objective": "Inspect later",
                "at": "2026-10-04T10:00:00Z",
                "cron": None,
                "timezone": None,
                "channel_id": None,
            },
        ),
        (DeleteScheduledTaskInput, {"task_id": "a" * 32}),
        (
            SubmitScheduledTaskResultInput,
            {"status": "finished", "result": "Done", "files": None},
        ),
        (LoadSkillInput, {"skill_path": "/runtime/skill/SKILL.md"}),
        (WriteInput, {"path": "/runtime/file", "content": "", "overwrite": False}),
    ],
)
async def test_owned_tool_unknown_fields_and_native_schemas(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    """Every owned input retains valid values and rejects undeclared fields."""
    invocations: list[BaseModel] = []

    async def execute(args: BaseModel) -> str:
        invocations.append(args)
        return "ok"

    tool = make_tool(
        execute, input_model=model, name="owned", description="Owned input test"
    )
    assert await tool.handler(json.dumps(payload)) == "ok"
    assert invocations == [model.model_validate(payload)]
    with pytest.raises(FunctionToolError, match="extra_forbidden"):
        await tool.handler(json.dumps({**payload, "undeclared": "value"}))
    assert len(invocations) == 1

    schema = tool.spec.input_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "oneOf" not in schema
    assert "anyOf" not in schema
    declaration = _native_tool_declaration(tool, "json_function")
    openai = OpenAIResponsesLowerer(
        provider="openai",
        provider_id=LLMProvider.OPENAI,
        model="gpt-test",
        top_k=None,
        tools=[declaration],
        supported_execution_options=(),
        enabled_execution_options=(),
    ).lower([], native_replay_context=None, model="gpt-test")
    assert openai.tools[0]["parameters"] == schema
    pydantic_request = PydanticAILowerer(
        provider="openai",
        provider_id=LLMProvider.OPENAI,
        model="gpt-test",
        model_capabilities=ModelCapabilities(),
        top_k=None,
        tools=[declaration],
        supported_execution_options=(),
        enabled_execution_options=(),
    ).lower([], native_replay_context=None, model="gpt-test")
    assert (
        pydantic_request.parameters.function_tools[0].parameters_json_schema == schema
    )
