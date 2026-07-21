"""Event tool catalog tests."""

import asyncio

from pydantic import BaseModel

from azents.core.tools import Toolkit, ToolkitState, ToolkitStatus, TurnContext
from azents.engine.events.generated_files import GeneratedFileOutput
from azents.engine.events.litellm_responses import LiteLLMResponsesLowerer
from azents.engine.events.output_parts import (
    TOOL_OUTPUT_TEXT_HARD_CAP_CHARS,
    iter_output_parts,
)
from azents.engine.events.tools import (
    ToolCatalogClientToolExecutor,
    build_tool_catalog,
    extend_tool_catalog,
    summarize_tool_arguments,
)
from azents.engine.events.types import (
    AttachmentOutputPart,
    ClientToolCallPayload,
    NativeArtifact,
    OutputTextPart,
    build_native_compat_key,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolResult,
    FunctionToolSpec,
)
from azents.engine.tooling.tool_search import ToolExposure


class _ToolkitConfig(BaseModel):
    """Toolkit config for tests."""


class _Toolkit(Toolkit[_ToolkitConfig]):
    """Toolkit for tests."""

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return Tool state."""
        del context
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                FunctionTool(
                    spec=FunctionToolSpec(
                        name="echo",
                        description="Echo input.",
                        input_schema={
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    ),
                    handler=_echo,
                )
            ],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static prompt for tests."""
        del context
        return "tool prompt"


class _DynamicPromptToolkit(Toolkit[_ToolkitConfig]):
    """Toolkit that intentionally returns dynamic prompt content."""

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return dynamic prompt state."""
        del context
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[],
        )

    async def get_dynamic_prompt(self, context: TurnContext) -> str:
        """Return dynamic prompt for tests."""
        del context
        return "dynamic tool prompt"


class _InlineToolkit(Toolkit[_ToolkitConfig]):
    """Test toolkit returning a single FunctionTool."""

    def __init__(self, tool: FunctionTool) -> None:
        self._tool = tool

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return injected tool state."""
        del context
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[self._tool])


class _FunctionToolResultToolkit(Toolkit[_ToolkitConfig]):
    """Toolkit for testing FunctionToolResult output part return."""

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return Tool state."""
        del context
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                FunctionTool(
                    spec=FunctionToolSpec(
                        name="legacy_result",
                        description="Return structured legacy result.",
                        input_schema={"type": "object"},
                    ),
                    handler=_legacy_result,
                )
            ],
        )


async def _echo(arguments: str) -> str:
    """Echo handler."""
    return arguments


async def _legacy_result(arguments: str) -> FunctionToolResult:
    """Return structured tool output part result."""
    del arguments
    return FunctionToolResult(
        output=[
            {"type": "text", "text": "created report"},
            {
                "type": "attachment",
                "attachment_id": None,
                "uri": "exchange://workspace/session/report.txt",
                "name": "report.txt",
                "media_type": "text/plain",
                "size": 12,
                "preview_summary": "preview",
            },
        ],
    )


async def test_build_tool_catalog_prefixes_and_lowers_native_schema() -> None:
    """Create prefixed function tool schema from Toolkit state."""
    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_Toolkit(),
                slug="demo",
                use_prefix=True,
            )
        ],
        context=TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    assert list(catalog.tools) == ["demo__echo"]
    assert catalog.static_prompt_fragment_inputs[0].label == "demo"
    assert catalog.static_prompt_fragment_inputs[0].content == "tool prompt"
    assert catalog.dynamic_prompt_fragment_inputs == []
    assert catalog.native_tools[0]["name"] == "demo__echo"
    assert catalog.native_tools[0]["strict"] is False

    request = LiteLLMResponsesLowerer(
        provider="openai",
        model="gpt-5.1",
        tools=catalog.native_tools,
    ).lower([], model="gpt-5.1")
    assert request.tools == catalog.native_tools


async def test_build_tool_catalog_classifies_direct_and_deferred_tools() -> None:
    """Keep core and service control tools direct while deferring operations."""
    switch_installation = FunctionTool(
        spec=FunctionToolSpec(
            name="switch_installation",
            description="Select the active GitHub installation.",
            input_schema={"type": "object"},
        ),
        handler=_echo,
    )
    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_Toolkit(),
                slug="core",
                use_prefix=False,
                toolkit_type=None,
            ),
            ToolkitBinding(
                toolkit=_Toolkit(),
                slug="azents",
                use_prefix=True,
                toolkit_type="github",
            ),
            ToolkitBinding(
                toolkit=_InlineToolkit(switch_installation),
                slug="github",
                use_prefix=True,
                toolkit_type="github",
            ),
        ],
        context=TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    assert catalog.direct_tool_names == ["echo", "github__switch_installation"]
    assert catalog.deferred_tool_names == ["azents__echo"]
    assert catalog.entries["azents__echo"].source.slug == "azents"
    assert catalog.entries["azents__echo"].source.toolkit_type == "github"


async def test_catalog_enriches_registered_tool_call_with_source_snapshot() -> None:
    """Use the selected catalog entry instead of parsing a tool name prefix."""
    toolkit = _Toolkit()
    toolkit.display_name = "GitHub"
    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=toolkit,
                slug="github",
                use_prefix=True,
                toolkit_type="github",
                toolkit_config_id="toolkit-config-1",
            )
        ],
        context=TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    enriched = catalog.enrich_client_tool_call(
        ClientToolCallPayload(
            call_id="call-1",
            name="github__echo",
            arguments="{}",
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    assert enriched.toolkit_source is not None
    assert enriched.toolkit_source.model_dump() == {
        "toolkit_config_id": "toolkit-config-1",
        "toolkit_type": "github",
        "toolkit_name": "GitHub",
        "toolkit_slug": "github",
    }


async def test_extend_tool_catalog_marks_runtime_builtin_direct() -> None:
    """Client-executed runtime builtins remain pinned direct tools."""
    catalog = await build_tool_catalog(
        toolkit_bindings=[],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="grok-4",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )
    image_generation = FunctionTool(
        spec=FunctionToolSpec(
            name="image_generation",
            description="Generate an image.",
            input_schema={"type": "object"},
        ),
        handler=_echo,
    )

    extended = extend_tool_catalog(catalog, [image_generation])

    assert extended.entries["image_generation"].exposure == ToolExposure.DIRECT
    assert extended.direct_tool_names == ["image_generation"]


async def test_build_tool_catalog_separates_dynamic_prompt_layer() -> None:
    """Dynamic toolkit prompt content is isolated from static prompt inputs."""
    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_DynamicPromptToolkit(),
                slug="memory",
                use_prefix=True,
            )
        ],
        context=TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    assert catalog.static_prompt_fragment_inputs == []
    assert catalog.dynamic_prompt_fragment_inputs[0].label == "memory"
    assert catalog.dynamic_prompt_fragment_inputs[0].content == "dynamic tool prompt"
    assert (
        catalog.dynamic_prompt_fragment_inputs[0].metadata["prompt_layer"] == "dynamic"
    )


async def test_native_tools_are_sorted_by_function_name() -> None:
    """Canonicalize provider-facing native tool order by function name."""
    tools = [
        FunctionTool(
            spec=FunctionToolSpec(
                name=name,
                description=f"{name} tool.",
                input_schema={"type": "object"},
            ),
            handler=_echo,
        )
        for name in ["zeta", "alpha", "middle"]
    ]

    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_InlineToolkit(tool),
                slug="",
                use_prefix=False,
            )
            for tool in tools
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    assert [tool["name"] for tool in catalog.native_tools] == [
        "alpha",
        "middle",
        "zeta",
    ]


async def test_client_tool_executor_returns_event_result() -> None:
    """Convert Tool handler result to event client_tool_result."""
    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(toolkit=_Toolkit(), slug="", use_prefix=False)
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    result = await ToolCatalogClientToolExecutor(catalog).execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="echo",
            arguments='{"text":"hello"}',
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    assert result.status == "completed"
    assert result.name == "echo"
    assert result.output == '{"text":"hello"}'
    assert result.metadata == {}
    parts = list(iter_output_parts(result.output))
    assert isinstance(parts[0], OutputTextPart)
    assert parts[0].text == '{"text":"hello"}'


async def test_client_tool_executor_preserves_failed_result_metadata() -> None:
    """Preserve structured diagnostics from one model-visible tool failure."""

    async def handler(arguments: str) -> str:
        del arguments
        raise FunctionToolError(
            "Provider rejected the request.",
            metadata={"code": "http_failure", "status": 400},
        )

    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_InlineToolkit(
                    FunctionTool(
                        spec=FunctionToolSpec(
                            name="failing_tool",
                            description="Return one structured failure.",
                            input_schema={"type": "object"},
                        ),
                        handler=handler,
                    )
                ),
                slug="",
                use_prefix=False,
            )
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    result = await ToolCatalogClientToolExecutor(catalog).execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="failing_tool",
            arguments="{}",
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    assert result.status == "failed"
    parts = list(iter_output_parts(result.output))
    assert len(parts) == 1
    assert isinstance(parts[0], OutputTextPart)
    assert parts[0].text == "Provider rejected the request."
    assert result.metadata == {"code": "http_failure", "status": 400}


async def test_client_tool_executor_applies_global_text_output_cap() -> None:
    """Tool executor applies global text hard cap to every tool result."""
    long_output = "a" + "b" * TOOL_OUTPUT_TEXT_HARD_CAP_CHARS

    async def handler(arguments: str) -> str:
        del arguments
        return long_output

    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_InlineToolkit(
                    FunctionTool(
                        spec=FunctionToolSpec(
                            name="long_output",
                            description="Return long output.",
                            input_schema={"type": "object"},
                        ),
                        handler=handler,
                    )
                ),
                slug="",
                use_prefix=False,
            )
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    result = await ToolCatalogClientToolExecutor(catalog).execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="long_output",
            arguments="{}",
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    assert result.status == "completed"
    assert result.output == "... (truncated)\n" + "b" * TOOL_OUTPUT_TEXT_HARD_CAP_CHARS


async def test_client_tool_executor_caps_structured_text_output_parts() -> None:
    """Structured output part also cannot bypass global text hard cap."""
    long_output = "a" + "b" * TOOL_OUTPUT_TEXT_HARD_CAP_CHARS

    async def handler(arguments: str) -> FunctionToolResult:
        del arguments
        return FunctionToolResult(
            output=[
                {"type": "text", "text": "prefix"},
                {
                    "type": "attachment",
                    "uri": "exchange://workspace/session/report.txt",
                    "name": "report.txt",
                    "media_type": "text/plain",
                    "size": 12,
                },
                {"type": "text", "text": long_output},
            ]
        )

    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_InlineToolkit(
                    FunctionTool(
                        spec=FunctionToolSpec(
                            name="structured_long_output",
                            description="Return structured long output.",
                            input_schema={"type": "object"},
                        ),
                        handler=handler,
                    )
                ),
                slug="",
                use_prefix=False,
            )
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    result = await ToolCatalogClientToolExecutor(catalog).execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="structured_long_output",
            arguments="{}",
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    parts = list(iter_output_parts(result.output))
    assert isinstance(parts[0], AttachmentOutputPart)
    assert isinstance(parts[1], OutputTextPart)
    assert parts[1].text == "... (truncated)\n" + "b" * TOOL_OUTPUT_TEXT_HARD_CAP_CHARS


async def test_client_tool_executor_carries_transient_generated_files() -> None:
    """Bind generated bytes to the call identity without serializing them."""

    async def handler(arguments: str) -> FunctionToolResult:
        del arguments
        return FunctionToolResult(
            output=[],
            generated_files=[
                GeneratedFileOutput(
                    output_index=0,
                    filename="generated.png",
                    media_type="image/png",
                    sha256="a" * 64,
                    body=b"generated-bytes",
                )
            ],
        )

    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_InlineToolkit(
                    FunctionTool(
                        spec=FunctionToolSpec(
                            name="image_generation",
                            description="Generate an image.",
                            input_schema={"type": "object"},
                        ),
                        handler=handler,
                    )
                ),
                slug="",
                use_prefix=False,
            )
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="grok-4",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    result = await ToolCatalogClientToolExecutor(catalog).execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="image_generation",
            arguments="{}",
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    assert len(result.pending_generated_files) == 1
    assert result.pending_generated_files[0].call_id == "call-1"
    assert result.pending_generated_files[0].body == b"generated-bytes"
    assert "generated-bytes" not in result.model_dump_json()


async def test_client_tool_executor_preserves_function_tool_result_metadata() -> None:
    """FunctionToolResult metadata is preserved without changing output."""

    async def handler(arguments: str) -> FunctionToolResult:
        del arguments
        return FunctionToolResult(
            output="process output",
            metadata={
                "kind": "exec_command_result",
                "process_id": "proc_123",
                "status": "running",
                "nested": {"count": 1},
                "items": ["stdout", None],
            },
        )

    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_InlineToolkit(
                    FunctionTool(
                        spec=FunctionToolSpec(
                            name="metadata_result",
                            description="Return result metadata.",
                            input_schema={"type": "object"},
                        ),
                        handler=handler,
                    )
                ),
                slug="",
                use_prefix=False,
            )
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    result = await ToolCatalogClientToolExecutor(catalog).execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="metadata_result",
            arguments="{}",
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    assert result.status == "completed"
    assert result.output == "process output"
    assert result.metadata == {
        "kind": "exec_command_result",
        "process_id": "proc_123",
        "status": "running",
        "nested": {"count": 1},
        "items": ["stdout", None],
    }


async def test_client_tool_executor_dispatches_cancel_handler() -> None:
    """Tool cancellation hook is dispatched fire-and-forget."""
    called = asyncio.Event()
    requests: list[FunctionToolCancelRequest] = []

    async def cancel_handler(request: FunctionToolCancelRequest) -> None:
        requests.append(request)
        called.set()

    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_InlineToolkit(
                    FunctionTool(
                        spec=FunctionToolSpec(
                            name="slow",
                            description="Slow tool.",
                            input_schema={"type": "object"},
                        ),
                        handler=_echo,
                        cancel_handler=cancel_handler,
                    )
                ),
                slug="",
                use_prefix=False,
            )
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    ToolCatalogClientToolExecutor(catalog).request_cancel(
        ClientToolCallPayload(
            call_id="call-1",
            name="slow",
            arguments='{"pid":123}',
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    await asyncio.wait_for(called.wait(), timeout=1)
    assert requests == [
        FunctionToolCancelRequest(
            call_id="call-1",
            name="slow",
            arguments='{"pid":123}',
        )
    ]


async def test_client_tool_executor_migrates_function_tool_result_parts() -> None:
    """FunctionToolResult output part input is validated as event output parts."""
    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_FunctionToolResultToolkit(),
                slug="",
                use_prefix=False,
            )
        ],
        context=TurnContext(
            user_id=None,
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=_noop_publish,
        ),
    )

    result = await ToolCatalogClientToolExecutor(catalog).execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="legacy_result",
            arguments="{}",
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    assert result.status == "completed"
    assert isinstance(result.output, list)
    text_part = result.output[0]
    attachment_part = result.output[1]
    assert isinstance(text_part, OutputTextPart)
    assert text_part.text == "created report"
    assert isinstance(attachment_part, AttachmentOutputPart)
    assert attachment_part.uri == "exchange://workspace/session/report.txt"
    assert attachment_part.preview_summary == "preview"


async def test_client_tool_executor_returns_failed_for_unknown_tool() -> None:
    """Unregistered tool call is converted to failed result."""
    result = await ToolCatalogClientToolExecutor(
        await build_tool_catalog(
            toolkit_bindings=[],
            context=TurnContext(
                user_id=None,
                workspace_id="workspace-1",
                model="gpt-5.1",
                run_id="run-1",
                publish_event=_noop_publish,
            ),
        )
    ).execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="missing",
            arguments="{}",
            native_artifact=_artifact(),
            wire_dialect="json_function",
        )
    )

    assert result.status == "failed"
    output = result.output[0]
    assert isinstance(output, OutputTextPart)
    assert "Tool not found" in output.text


def test_summarize_tool_arguments_is_stable() -> None:
    """Tool arguments summary stabilizes JSON key order."""
    assert summarize_tool_arguments('{"b":2,"a":1}') == '{"a": 1, "b": 2}'


async def _noop_publish(_event: object) -> None:
    """No-op publish."""


def _artifact() -> NativeArtifact:
    """Create native artifact for tests."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item={"type": "function_call"},
    )
