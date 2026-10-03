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
from azents.engine.tools.glob import GlobInput
from azents.engine.tools.grep import GrepInput
from azents.engine.tools.memory import DeleteMemoryInput, SaveMemoryInput
from azents.engine.tools.read_text import ReadTextInput
from azents.engine.tools.subagent import (
    FollowupTaskInput,
    InterruptAgentInput,
    SendMessageInput,
    SpawnAgentInput,
)


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
        tools=[declaration],
        supported_execution_options=(),
        enabled_execution_options=(),
    ).lower([], model="gpt-test")
    assert openai.tools[0]["parameters"] == schema
    pydantic_request = PydanticAILowerer(
        provider="openai",
        provider_id=LLMProvider.OPENAI,
        model="gpt-test",
        model_capabilities=ModelCapabilities(),
        tools=[declaration],
        supported_execution_options=(),
        enabled_execution_options=(),
    ).lower([], model="gpt-test")
    assert (
        pydantic_request.parameters.function_tools[0].parameters_json_schema == schema
    )
