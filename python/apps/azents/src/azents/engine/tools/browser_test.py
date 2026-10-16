"""Browser tool authority, schema, outcome and model-image integration tests."""

import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal

import pytest
from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserCapture,
    BrowserCommand,
    BrowserDialog,
    BrowserObserveCommand,
    BrowserOpenCommand,
    BrowserPage,
    BrowserResult,
)

from azents.core.enums import LLMProvider, ModelFileStatus
from azents.core.llm_catalog import ModelCapabilities, ModelToolCallingCapabilities
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tools.browser import BrowserExecutionTarget, make_browser_tools
from azents.engine.tools.runtime_io import (
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.repos.model_file.data import ModelFile
from azents.runtime.transfer.runtime_image_read import (
    RuntimeImageReadError,
    RuntimeImageReadRequest,
)

_AUTHORITY = SessionResourceAuthority(
    workspace_id="workspace-1",
    agent_id="agent-1",
    session_id="child-session",
    root_session_id="root-session",
    run_id="run-1",
    run_index=2,
    owner_generation=3,
)
_FOLDER = "/workspace/reported/.azents/sessions/child-session"
_TARGET = BrowserExecutionTarget("runtime-1", 5, 7, _FOLDER)
_PAGE = BrowserPage(
    "page-1", "task-1", "incarnation-1", "https://example.test/", "Fixture", ()
)
_RESULT = BrowserResult(
    (), _PAGE, "Fixture content", False, (), None, None, None, None, "none"
)


@dataclasses.dataclass(frozen=True)
class _Invocation:
    runtime_id: str
    runner_generation: int
    owner_session_id: str
    command: BrowserCommand
    deadline_at: datetime


@dataclasses.dataclass
class _Runner:
    result: BrowserResult = _RESULT
    error: BaseException | None = None
    calls: list[_Invocation] = dataclasses.field(default_factory=list)

    async def run_browser_command(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        command: BrowserCommand,
        deadline_at: datetime,
    ) -> BrowserResult:
        self.calls.append(
            _Invocation(
                runtime_id, runner_generation, owner_session_id, command, deadline_at
            )
        )
        if self.error is not None:
            raise self.error
        return self.result


@dataclasses.dataclass
class _ImageReader:
    error: RuntimeImageReadError | None = None
    calls: list[RuntimeImageReadRequest] = dataclasses.field(default_factory=list)

    async def read(self, request: RuntimeImageReadRequest) -> ModelFile:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return ModelFile(
            id="m" * 32,
            workspace_id=_AUTHORITY.workspace_id,
            session_id=_AUTHORITY.session_id,
            agent_id=_AUTHORITY.agent_id,
            name="capture.jpg",
            media_type="image/jpeg",
            kind="image",
            size_bytes=10,
            created_run_id=_AUTHORITY.run_id,
            created_run_index=_AUTHORITY.run_index,
            storage_key="model-files/fixture",
            status=ModelFileStatus.AVAILABLE,
            normalized_format="jpeg",
            sha256="2" * 64,
            metadata={},
            created_at=datetime.now(UTC),
            deleted_at=None,
        )


@dataclasses.dataclass
class _Harness:
    runner: _Runner = dataclasses.field(default_factory=_Runner)
    reader: _ImageReader = dataclasses.field(default_factory=_ImageReader)
    authorized: bool = True
    transfer_allowed: bool = True
    prepared: int = 0
    authority_checks: int = 0

    async def target(self) -> BrowserExecutionTarget:
        self.prepared += 1
        return _TARGET

    async def revalidate(self) -> bool:
        self.authority_checks += 1
        return self.authorized

    async def require_transfer(self) -> None:
        if not self.transfer_allowed:
            raise FunctionToolError("Image transfer unavailable.")

    def tools(self) -> dict[str, FunctionTool]:
        return {
            tool.spec.name: tool
            for tool in make_browser_tools(
                runner_operations=self.runner,
                authority=_AUTHORITY,
                resolve_execution_target=self.target,
                revalidate_authority=self.revalidate,
                require_image_transfer=self.require_transfer,
                runtime_image_read_service=self.reader,
            )
        }


def _target_args() -> dict[str, str]:
    return {
        "task_id": "task-1",
        "page_id": "page-1",
        "resource_incarnation": "incarnation-1",
    }


async def test_open_uses_concrete_session_not_root_or_user_input() -> None:
    h = _Harness()
    tool = h.tools()["browser_open"]
    result = await tool.handler(
        json.dumps({"url": "https://example.test/", "label": "Research"})
    )
    assert isinstance(result, FunctionToolResult)
    call = h.runner.calls[0]
    assert call.owner_session_id == "child-session"
    assert call.runtime_id == "runtime-1" and call.runner_generation == 7
    assert isinstance(call.command, BrowserOpenCommand)
    assert call.command.authority.session_id == "child-session"
    assert call.command.authority.working_directory == _FOLDER
    assert h.authority_checks == 1
    assert isinstance(result.output, list)
    text = result.output[0]["text"]
    assert isinstance(text, str) and json.loads(text)["action_state"] == "none"
    with pytest.raises(FunctionToolError):
        await tool.handler(json.dumps({"session_id": "other"}))
    assert len(h.runner.calls) == 1


@pytest.mark.parametrize(
    "name,args",
    [
        ("browser_open", {}),
        ("browser_observe", {"view": "status"}),
        ("browser_act", {**_target_args(), "action": "reload"}),
    ],
)
async def test_current_authority_rechecked_before_every_effect(
    name: str, args: dict[str, object]
) -> None:
    h = _Harness(authorized=False)
    with pytest.raises(FunctionToolError, match="no longer current"):
        await h.tools()[name].handler(json.dumps(args))
    assert not h.runner.calls and h.prepared == 0


async def test_status_has_no_ambient_selected_page_and_other_views_require_target() -> (
    None
):
    h = _Harness()
    tool = h.tools()["browser_observe"]
    result = await tool.handler('{"view":"status"}')
    assert isinstance(result, FunctionToolResult) and isinstance(result.output, list)
    text = result.output[0]["text"]
    assert isinstance(text, str) and json.loads(text)["action_state"] == "none"
    command = h.runner.calls[0].command
    assert isinstance(command, BrowserObserveCommand) and command.target is None
    with pytest.raises(FunctionToolError):
        await tool.handler('{"view":"glance"}')
    with pytest.raises(FunctionToolError):
        await tool.handler('{"view":"dom","task_id":"task-1"}')
    assert len(h.runner.calls) == 1


async def test_action_passes_prearmed_expectation_and_current_frame_ref() -> None:
    h = _Harness()
    await h.tools()["browser_act"].handler(
        json.dumps(
            {
                **_target_args(),
                "frame_id": "frame-1",
                "action": "click",
                "ref": "ref-1",
                "observation_id": "observation-1",
                "expect": "download",
            }
        )
    )
    command = h.runner.calls[0].command
    assert isinstance(command, BrowserActCommand)
    assert command.target.frame_id == "frame-1"
    assert command.action.ref == "ref-1" and command.action.expect == "download"


@pytest.mark.parametrize("action_state", ["dispatched", "dialog_pending"])
async def test_action_state_is_preserved_without_claiming_site_workflow_success(
    action_state: Literal["dispatched", "dialog_pending"],
) -> None:
    h = _Harness()
    h.runner.result = dataclasses.replace(
        _RESULT,
        action_state=action_state,
        dialog=(
            BrowserDialog("dialog-1", "confirm", "Proceed?")
            if action_state == "dialog_pending"
            else None
        ),
    )
    result = await h.tools()["browser_act"].handler(
        json.dumps({**_target_args(), "action": "reload"})
    )
    assert isinstance(result, FunctionToolResult) and isinstance(result.output, list)
    text = result.output[0]["text"]
    assert isinstance(text, str)
    payload = json.loads(text)
    assert payload["action_state"] == action_state
    assert "success" not in payload
    if action_state == "dialog_pending":
        assert payload["dialog"]["id"] == "dialog-1"
    description = h.tools()["browser_act"].spec.description
    assert "not site workflow success" in description
    assert "original action is still waiting" in description
    assert len(h.runner.calls) == 1


@pytest.mark.parametrize("action", ["evaluate", "run_code", "close_browser", "context"])
async def test_unapproved_script_and_global_actions_are_not_exposed(
    action: str,
) -> None:
    h = _Harness()
    with pytest.raises(FunctionToolError):
        await h.tools()["browser_act"].handler(
            json.dumps({**_target_args(), "action": action})
        )
    assert not h.runner.calls


async def test_incomplete_action_does_not_dispatch_or_echo_sensitive_input() -> None:
    h = _Harness()
    with pytest.raises(FunctionToolError) as captured:
        await h.tools()["browser_act"].handler(
            json.dumps({**_target_args(), "action": "fill", "text": "private-fixture"})
        )
    assert "private-fixture" not in str(captured.value)
    assert not h.runner.calls


async def test_image_view_materializes_filepart_and_preserves_original() -> None:
    h = _Harness()
    original = BrowserCapture(_FOLDER + "/capture.png", "image/png", 123, 800, 600)
    h.runner.result = dataclasses.replace(_RESULT, capture=original)
    result = await h.tools()["browser_observe"].handler(
        json.dumps({**_target_args(), "view": "image"})
    )
    assert isinstance(result, FunctionToolResult) and isinstance(result.output, list)
    assert result.output[1]["type"] == "file"
    assert result.output[1]["model_file_id"] == "m" * 32
    request = h.reader.calls[0]
    assert request.runtime_path == original.path and request.media_type == "image/png"
    assert request.authority == _AUTHORITY and request.target.desired_generation == 5
    assert request.expected_size == 123 and request.filename == "capture.png"
    text = result.output[0]["text"]
    assert isinstance(text, str)
    assert json.loads(text)["capture"]["path"] == original.path
    assert PurePosixPath(original.path).suffix == ".png"
    assert h.authority_checks == 2


@pytest.mark.parametrize(
    "capture",
    [
        None,
        BrowserCapture("/another-session/capture.png", "image/png", 12, 8, 6),
        BrowserCapture(_FOLDER + "/../capture.png", "image/png", 12, 8, 6),
        BrowserCapture(_FOLDER + "/capture.png", "image/png", 21 * 1024 * 1024, 8, 6),
        BrowserCapture(_FOLDER + "/capture.jpg", "image/jpeg", 12, 8, 6),
    ],
)
async def test_image_path_only_invalid_scope_or_oversize_is_not_success(
    capture: BrowserCapture | None,
) -> None:
    h = _Harness()
    h.runner.result = dataclasses.replace(_RESULT, capture=capture)
    with pytest.raises(FunctionToolError):
        await h.tools()["browser_observe"].handler(
            json.dumps({**_target_args(), "view": "image"})
        )
    assert not h.reader.calls


async def test_transfer_failure_is_failed_image_observation_not_text_path_success() -> (
    None
):
    h = _Harness()
    h.runner.result = dataclasses.replace(
        _RESULT, capture=BrowserCapture(_FOLDER + "/capture.png", "image/png", 12, 8, 6)
    )
    h.reader.error = RuntimeImageReadError("private transport context")
    with pytest.raises(FunctionToolError, match="materialization failed") as captured:
        await h.tools()["browser_observe"].handler(
            json.dumps({**_target_args(), "view": "image"})
        )
    assert "private transport context" not in str(captured.value)


async def test_transfer_unavailable_prevents_capture_work() -> None:
    h = _Harness(transfer_allowed=False)
    with pytest.raises(FunctionToolError):
        await h.tools()["browser_observe"].handler(
            json.dumps({**_target_args(), "view": "image"})
        )
    assert not h.runner.calls


@pytest.mark.parametrize(
    "error",
    [
        RuntimeRunnerOperationFailedError(
            "https://private?secret=value", code="browser_conflict"
        ),
        RuntimeRunnerOperationUnavailable("internal"),
        RuntimeRunnerOperationGenerationError("internal"),
    ],
)
async def test_runtime_failure_is_not_success_and_does_not_leak_raw_error(
    error: Exception,
) -> None:
    h = _Harness()
    h.runner.error = error
    with pytest.raises(FunctionToolError) as captured:
        await h.tools()["browser_act"].handler(
            json.dumps({**_target_args(), "action": "reload"})
        )
    assert "secret=value" not in str(captured.value)
    assert len(h.runner.calls) == 1


async def test_cancelled_tool_is_not_converted_to_retry_or_success() -> None:
    h = _Harness()
    h.runner.error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await h.tools()["browser_open"].handler("{}")
    assert len(h.runner.calls) == 1


async def test_fill_empty_text_clears_input_without_becoming_missing_text() -> None:
    h = _Harness()
    await h.tools()["browser_act"].handler(
        json.dumps(
            {
                **_target_args(),
                "action": "fill",
                "ref": "ref-1",
                "observation_id": "observation-1",
                "text": "",
            }
        )
    )
    command = h.runner.calls[0].command
    assert isinstance(command, BrowserActCommand) and command.action.text == ""


@pytest.mark.parametrize("field", ["page", "popup"])
async def test_runner_result_cannot_substitute_another_task_page(field: str) -> None:
    h = _Harness()
    other_page = dataclasses.replace(_PAGE, task_id="other-task")
    h.runner.result = (
        dataclasses.replace(_RESULT, page=other_page)
        if field == "page"
        else dataclasses.replace(_RESULT, popup=other_page)
    )
    with pytest.raises(FunctionToolError, match="resource target|current task"):
        await h.tools()["browser_act"].handler(
            json.dumps({**_target_args(), "action": "reload"})
        )


async def test_unrecognized_runner_failure_code_is_not_echoed_in_metadata() -> None:
    h = _Harness()
    h.runner.error = RuntimeRunnerOperationFailedError(
        "private failure", code="https://private.test/?signed=private-fixture"
    )
    with pytest.raises(FunctionToolError) as captured:
        await h.tools()["browser_open"].handler("{}")
    assert captured.value.metadata["reason_code"] == "browser_operation_failed"
    assert "private-fixture" not in json.dumps(captured.value.metadata)


@pytest.mark.parametrize(
    "code", ["browser_encrypted_input_invalid", "browser_encrypted_input_failed"]
)
async def test_encrypted_input_failure_preserves_only_fixed_reason(code: str) -> None:
    h = _Harness()
    h.runner.error = RuntimeRunnerOperationFailedError("private-canary", code=code)
    with pytest.raises(FunctionToolError) as captured:
        await h.tools()["browser_act"].handler(
            json.dumps(
                {
                    **_target_args(),
                    "action": "fill",
                    "ref": "r",
                    "observation_id": "o",
                    "encrypted_text": "A" * 64,
                }
            )
        )
    assert captured.value.metadata["reason_code"] == code
    assert "private-canary" not in str(captured.value)
    if code == "browser_encrypted_input_invalid":
        assert "Browser encrypted input is invalid" in str(captured.value)


def test_all_three_schema_roots_are_objects_without_root_combinators() -> None:
    tools = _Harness().tools()
    assert set(tools) == {"browser_open", "browser_observe", "browser_act"}
    for tool in tools.values():
        schema = tool.spec.input_schema
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert not {"oneOf", "anyOf", "allOf"} & set(schema)
        props = schema["properties"]
        assert isinstance(props, dict)
        assert not {
            "session_id",
            "root_session_id",
            "context_id",
            "script",
            "cdp_endpoint",
        } & set(props)


@pytest.mark.parametrize("provider", list(LLMProvider))
def test_browser_schemas_lower_for_every_provider(provider: LLMProvider) -> None:
    """Exercise both supported lowerer families with the real tool schemas."""
    capabilities = ModelCapabilities(
        tool_calling=ModelToolCallingCapabilities(supported=True)
    )
    declarations: list[dict[str, object]] = [
        {
            "type": "function",
            "name": tool.spec.name,
            "description": tool.spec.description,
            "parameters": tool.spec.input_schema,
        }
        for tool in _Harness().tools().values()
    ]
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        native = OpenAIResponsesLowerer(
            provider=provider.value,
            provider_id=provider,
            model="fixture",
            tools=declarations,
            model_capabilities=capabilities,
            supported_execution_options=[],
            enabled_execution_options=[],
            top_k=None,
        ).lower([], model="fixture", native_replay_context=None)
        assert len(native.tools) == 3
        for declaration in native.tools:
            parameters = declaration["parameters"]
            assert isinstance(parameters, dict) and parameters["type"] == "object"
    else:
        lowered = PydanticAILowerer(
            provider=provider.value,
            provider_id=provider,
            model="fixture",
            tools=declarations,
            model_capabilities=capabilities,
            supported_execution_options=[],
            enabled_execution_options=[],
            top_k=None,
        ).lower([], model="fixture", native_replay_context=None)
        assert len(lowered.parameters.function_tools) == 3
        for definition in lowered.parameters.function_tools:
            assert definition.parameters_json_schema["type"] == "object"
