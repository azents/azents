"""Event runtime client tool catalog."""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import TypeAdapter

from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.events.execution import ClientToolExecutor
from azents.engine.events.generated_files import PendingGeneratedFileOutput
from azents.engine.events.output_parts import enforce_tool_output_text_hard_cap
from azents.engine.events.system_prompt import ToolkitPromptInput
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    OutputTextPart,
    ToolkitSourceSnapshot,
    ToolOutput,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.tool_search import (
    CatalogTool,
    ToolCatalogSource,
    ToolExposure,
    classify_tool_exposure,
)

logger = logging.getLogger(__name__)

_TOOL_OUTPUT_ADAPTER: TypeAdapter[ToolOutput] = TypeAdapter(ToolOutput)
_SLOW_TOOLKIT_UPDATE_CONTEXT_SECONDS = 1.0


@dataclass(frozen=True)
class ToolCatalog:
    """Tool catalog used by one run/turn of event loop."""

    tools: Mapping[str, FunctionTool]
    entries: Mapping[str, CatalogTool]
    static_prompt_fragment_inputs: list[ToolkitPromptInput]
    dynamic_prompt_fragment_inputs: list[ToolkitPromptInput]
    active_toolkit_bindings: list[ToolkitBinding]

    @property
    def direct_tool_names(self) -> list[str]:
        """Return direct tool names in canonical order."""
        return sorted(
            name
            for name, entry in self.entries.items()
            if entry.exposure == ToolExposure.DIRECT
        )

    @property
    def deferred_tool_names(self) -> list[str]:
        """Return deferred tool names in canonical order."""
        return sorted(
            name
            for name, entry in self.entries.items()
            if entry.exposure == ToolExposure.DEFERRED
        )

    @property
    def prompt_fragment_inputs(self) -> list[ToolkitPromptInput]:
        """Return all toolkit prompt inputs in model assembly order."""
        return [
            *self.static_prompt_fragment_inputs,
            *self.dynamic_prompt_fragment_inputs,
        ]

    @property
    def native_tools(self) -> list[dict[str, object]]:
        """Return every executable tool schema in canonical order."""
        return self.native_tools_for(tuple(self.tools))

    def enrich_client_tool_call(
        self,
        call: ClientToolCallPayload,
    ) -> ClientToolCallPayload:
        """Copy the exact catalog entry's immutable Toolkit source onto a call."""
        entry = self.entries.get(call.name)
        if entry is None or entry.source.toolkit_config_id is None:
            return call.model_copy(update={"toolkit_source": None})
        if entry.source.toolkit_type is None:
            raise ValueError("DB-attached Toolkit source requires toolkit_type")
        return call.model_copy(
            update={
                "toolkit_source": ToolkitSourceSnapshot(
                    toolkit_config_id=entry.source.toolkit_config_id,
                    toolkit_type=entry.source.toolkit_type,
                    toolkit_name=entry.source.label,
                    toolkit_slug=entry.source.slug,
                )
            }
        )

    def native_tools_for(
        self,
        tool_names: Sequence[str],
    ) -> list[dict[str, object]]:
        """Return selected function schemas in canonical final-name order."""
        selected: list[FunctionTool] = []
        for name in sorted(set(tool_names)):
            tool = self.tools.get(name)
            if tool is None:
                raise ValueError(f"Tool name is not in the prepared catalog: {name}")
            selected.append(tool)
        return [
            {
                "type": "function",
                "name": tool.spec.name,
                "description": tool.spec.description,
                "parameters": tool.spec.input_schema,
                "strict": False,
            }
            for tool in selected
        ]


def extend_tool_catalog(
    catalog: ToolCatalog,
    additional_tools: Sequence[FunctionTool],
) -> ToolCatalog:
    """Return a catalog extended with collision-checked auto-bound tools."""
    tools = dict(catalog.tools)
    entries = dict(catalog.entries)
    source = ToolCatalogSource(
        slug="builtin",
        toolkit_type=None,
        toolkit_class="RuntimeBuiltinTool",
        display_name="Runtime",
        use_prefix=False,
    )
    for tool in additional_tools:
        name = tool.spec.name
        if name in tools:
            raise ValueError(f"Tool name is already bound: {name}")
        tools[name] = tool
        entries[name] = CatalogTool(
            tool=tool,
            source=source,
            exposure=ToolExposure.DIRECT,
        )
    return ToolCatalog(
        tools=MappingProxyType(tools),
        entries=MappingProxyType(entries),
        static_prompt_fragment_inputs=catalog.static_prompt_fragment_inputs,
        dynamic_prompt_fragment_inputs=catalog.dynamic_prompt_fragment_inputs,
        active_toolkit_bindings=catalog.active_toolkit_bindings,
    )


async def build_tool_catalog(
    *,
    toolkit_bindings: Sequence[ToolkitBinding],
    context: TurnContext,
) -> ToolCatalog:
    """Collect Toolkit state and build event tool catalog."""
    tools: dict[str, FunctionTool] = {}
    entries: dict[str, CatalogTool] = {}
    static_prompt_fragment_inputs: list[ToolkitPromptInput] = []
    dynamic_prompt_fragment_inputs: list[ToolkitPromptInput] = []
    active_toolkit_bindings: list[ToolkitBinding] = []
    for index, binding in enumerate(toolkit_bindings):
        update_started_at = time.monotonic()
        state = await binding.toolkit.update_context(context)
        duration_seconds = time.monotonic() - update_started_at
        if duration_seconds > _SLOW_TOOLKIT_UPDATE_CONTEXT_SECONDS:
            logger.warning(
                "Toolkit update_context slow",
                extra={
                    **_toolkit_update_context_log_extra(
                        binding=binding,
                        context=context,
                        index=index,
                        duration_seconds=duration_seconds,
                    ),
                    "tool_count": len(state.tools),
                    "status": state.status.value,
                },
            )
        if state.status != ToolkitStatus.ENABLED:
            continue
        active_toolkit_bindings.append(binding)
        label = _toolkit_prompt_label(binding)
        prompt = (await binding.toolkit.get_static_prompt(context)).strip()
        if prompt:
            static_prompt_fragment_inputs.append(
                _toolkit_prompt_input(
                    binding=binding,
                    index=index,
                    label=label,
                    layer="static",
                    content=prompt,
                )
            )
        dynamic_prompt = (await binding.toolkit.get_dynamic_prompt(context)).strip()
        if dynamic_prompt:
            dynamic_prompt_fragment_inputs.append(
                _toolkit_prompt_input(
                    binding=binding,
                    index=index,
                    label=label,
                    layer="dynamic",
                    content=dynamic_prompt,
                )
            )
        source = _tool_catalog_source(binding)
        for tool in state.tools:
            bound = (
                tool.with_prefix(f"{binding.slug}__") if binding.use_prefix else tool
            )
            tools[bound.spec.name] = bound
            entries[bound.spec.name] = CatalogTool(
                tool=bound,
                source=source,
                exposure=classify_tool_exposure(
                    source=source,
                    original_tool_name=tool.spec.name,
                ),
            )
    return ToolCatalog(
        tools=MappingProxyType(tools),
        entries=MappingProxyType(entries),
        static_prompt_fragment_inputs=static_prompt_fragment_inputs,
        dynamic_prompt_fragment_inputs=dynamic_prompt_fragment_inputs,
        active_toolkit_bindings=active_toolkit_bindings,
    )


def _tool_catalog_source(binding: ToolkitBinding) -> ToolCatalogSource:
    """Retain searchable source and routing metadata for one Toolkit binding."""
    routing_metadata: list[tuple[str, str]] = []
    if binding.slug:
        routing_metadata.append(("slug", binding.slug))
    if binding.toolkit_type is not None:
        routing_metadata.append(("toolkit_type", binding.toolkit_type))
    return ToolCatalogSource(
        slug=binding.slug,
        toolkit_type=binding.toolkit_type,
        toolkit_class=binding.toolkit.__class__.__name__,
        display_name=binding.toolkit.display_name.strip(),
        use_prefix=binding.use_prefix,
        toolkit_config_id=binding.toolkit_config_id,
        routing_metadata=tuple(routing_metadata),
    )


def _toolkit_prompt_input(
    *,
    binding: ToolkitBinding,
    index: int,
    label: str,
    layer: str,
    content: str,
) -> ToolkitPromptInput:
    """Build a layer-tagged toolkit prompt input."""
    return ToolkitPromptInput(
        id=f"toolkit-{index}-{layer}",
        label=label,
        content=content,
        metadata={**_toolkit_prompt_metadata(binding), "prompt_layer": layer},
    )


def _toolkit_update_context_log_extra(
    *,
    binding: ToolkitBinding,
    context: TurnContext,
    index: int,
    duration_seconds: float,
) -> dict[str, object]:
    """Build structured fields for Toolkit update_context slow log."""
    return {
        "session_id": context.session_id,
        "run_id": context.run_id,
        "workspace_id": context.workspace_id,
        "model": context.model,
        "run_index": context.run_index,
        "toolkit_index": index,
        "toolkit_slug": binding.slug,
        "toolkit_type": binding.toolkit_type,
        "toolkit_class": binding.toolkit.__class__.__name__,
        "toolkit_display_name": binding.toolkit.display_name,
        "use_prefix": binding.use_prefix,
        "duration_seconds": round(duration_seconds, 3),
        "threshold_seconds": _SLOW_TOOLKIT_UPDATE_CONTEXT_SECONDS,
    }


def _toolkit_prompt_label(binding: ToolkitBinding) -> str:
    """Return Toolkit prompt fragment label."""
    display_name = binding.toolkit.display_name.strip()
    if display_name:
        return display_name
    if binding.slug:
        return binding.slug
    return binding.toolkit.__class__.__name__


def _toolkit_prompt_metadata(binding: ToolkitBinding) -> dict[str, str]:
    """Return Toolkit prompt fragment source metadata."""
    metadata: dict[str, str] = {
        "toolkit_class": binding.toolkit.__class__.__name__,
        "use_prefix": str(binding.use_prefix).lower(),
    }
    if binding.slug:
        metadata["slug"] = binding.slug
    if binding.toolkit_type is not None:
        metadata["toolkit_type"] = binding.toolkit_type
    display_name = binding.toolkit.display_name.strip()
    if display_name:
        metadata["display_name"] = display_name
    return metadata


class ToolCatalogClientToolExecutor(ClientToolExecutor):
    """Event client tool call executor."""

    def __init__(self, catalog: ToolCatalog) -> None:
        self.catalog = catalog

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Run Tool handler and convert to event tool result."""
        tool = self.catalog.tools.get(call.name)
        if tool is None:
            return ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="failed",
                output=enforce_tool_output_text_hard_cap(
                    [OutputTextPart(text=f"Tool not found: {call.name}")]
                ),
            )
        try:
            result = await tool.handler(call.arguments)
        except FunctionToolError as exc:
            return ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="failed",
                output=enforce_tool_output_text_hard_cap(
                    [OutputTextPart(text=str(exc))]
                ),
                metadata=dict(exc.metadata),
            )

        return _tool_result_payload(call, result)

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Call Tool cancellation hook fire-and-forget."""
        tool = self.catalog.tools.get(call.name)
        if tool is None or tool.cancel_handler is None:
            return
        request = FunctionToolCancelRequest(
            call_id=call.call_id,
            name=call.name,
            arguments=call.arguments,
        )
        asyncio.create_task(_call_cancel_handler(tool, request))


async def _call_cancel_handler(
    tool: FunctionTool,
    request: FunctionToolCancelRequest,
) -> None:
    """Isolate cancellation hook failures so they do not block run stop."""
    if tool.cancel_handler is None:
        return
    with contextlib.suppress(Exception):
        await tool.cancel_handler(request)


def _tool_result_payload(
    call: ClientToolCallPayload,
    result: str | FunctionToolResult,
) -> ClientToolResultPayload:
    """Convert FunctionToolResult to event payload."""
    if isinstance(result, str):
        return ClientToolResultPayload(
            call_id=call.call_id,
            name=call.name,
            status="completed",
            output=enforce_tool_output_text_hard_cap(result),
        )

    output = _TOOL_OUTPUT_ADAPTER.validate_python(result.output)
    return ClientToolResultPayload(
        call_id=call.call_id,
        name=call.name,
        status="completed",
        output=enforce_tool_output_text_hard_cap(output),
        metadata=dict(result.metadata),
        pending_generated_files=[
            PendingGeneratedFileOutput(
                call_id=call.call_id,
                tool_name=call.name,
                output_index=generated.output_index,
                filename=generated.filename,
                media_type=generated.media_type,
                sha256=generated.sha256,
                body=generated.body,
            )
            for generated in result.generated_files
        ],
    )


def summarize_tool_arguments(arguments: str, *, max_chars: int = 2_000) -> str:
    """Return tool arguments summary for UI activity."""
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        text = arguments
    else:
        text = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated]"
