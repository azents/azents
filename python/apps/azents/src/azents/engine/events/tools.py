"""Event runtime client tool catalog."""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import TypeAdapter

from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.events.execution import ClientToolExecutor
from azents.engine.events.output_parts import enforce_tool_output_text_hard_cap
from azents.engine.events.system_prompt import ToolkitPromptInput
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    OutputTextPart,
    ToolOutput,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.types import (
    BackgroundHandle,
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolResult,
)

logger = logging.getLogger(__name__)

_TOOL_OUTPUT_ADAPTER: TypeAdapter[ToolOutput] = TypeAdapter(ToolOutput)
_SLOW_TOOLKIT_UPDATE_CONTEXT_SECONDS = 1.0


@dataclass(frozen=True)
class ToolCatalog:
    """Tool catalog used by one run/turn of event loop."""

    tools: dict[str, FunctionTool]
    prompt_fragment_inputs: list[ToolkitPromptInput]

    @property
    def native_tools(self) -> list[dict[str, object]]:
        """Return LiteLLM Responses function tool schema."""
        return [
            {
                "type": "function",
                "name": tool.spec.name,
                "description": tool.spec.description,
                "parameters": tool.spec.input_schema,
                "strict": False,
            }
            for tool in sorted(self.tools.values(), key=lambda item: item.spec.name)
        ]


async def build_tool_catalog(
    *,
    toolkit_bindings: Sequence[ToolkitBinding],
    context: TurnContext,
) -> ToolCatalog:
    """Collect Toolkit state and build event tool catalog."""
    tools: dict[str, FunctionTool] = {}
    prompt_fragment_inputs: list[ToolkitPromptInput] = []
    for index, binding in enumerate(toolkit_bindings):
        update_started_at = time.monotonic()
        try:
            state = await binding.toolkit.update_context(context)
        except Exception:
            duration_seconds = time.monotonic() - update_started_at
            if duration_seconds > _SLOW_TOOLKIT_UPDATE_CONTEXT_SECONDS:
                logger.warning(
                    "Toolkit update_context failed after slow duration",
                    extra=_toolkit_update_context_log_extra(
                        binding=binding,
                        context=context,
                        index=index,
                        duration_seconds=duration_seconds,
                    ),
                    exc_info=True,
                )
            raise
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
                    "prompt_present": bool(state.prompt.strip()),
                    "status": state.status.value,
                },
            )
        if state.status != ToolkitStatus.ENABLED:
            continue
        prompt = state.prompt.strip()
        if prompt:
            label = _toolkit_prompt_label(binding)
            prompt_fragment_inputs.append(
                ToolkitPromptInput(
                    id=f"toolkit-{index}",
                    label=label,
                    content=prompt,
                    metadata=_toolkit_prompt_metadata(binding),
                )
            )
        for tool in state.tools:
            bound = (
                tool.with_prefix(f"{binding.slug}__") if binding.use_prefix else tool
            )
            tools[bound.spec.name] = bound
    return ToolCatalog(
        tools=tools,
        prompt_fragment_inputs=prompt_fragment_inputs,
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
        self._catalog = catalog

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Run Tool handler and convert to event tool result."""
        tool = self._catalog.tools.get(call.name)
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
            )

        if isinstance(result, BackgroundHandle):
            return ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="interrupted",
                output=enforce_tool_output_text_hard_cap(
                    [OutputTextPart(text=result.initial_message)]
                ),
            )
        return _tool_result_payload(call, result)

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Call Tool cancellation hook fire-and-forget."""
        tool = self._catalog.tools.get(call.name)
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
