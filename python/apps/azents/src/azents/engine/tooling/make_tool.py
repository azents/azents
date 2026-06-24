"""Utilities for creating Tool from function.

Automatically extracts FunctionToolSpec(name, description, input_schema) from
Python function signature, docstring, and Pydantic input model, and creates a
handler that wraps JSON parsing and validation.

When ``supports_background=True`` is given, automatically inject
``run_in_background`` parameter into input schema and wraps handler with
BackgroundHandle-returning wrapper. This option is internal to make_tool and is
not stored in ``FunctionToolSpec``.
"""

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

from azcommon.uuid import uuid7
from pydantic import BaseModel, ValidationError

from azents.engine.run.types import (
    BackgroundHandle,
    FunctionTool,
    FunctionToolError,
    FunctionToolHandler,
    FunctionToolResult,
    FunctionToolSpec,
)

# Empty schema for tools without parameters
_EMPTY_SCHEMA: dict[str, object] = {"type": "object", "properties": {}}

# Parameter description injected into input schema of background-supporting tools
_RUN_IN_BACKGROUND_PROPERTY: dict[str, object] = {
    "type": "boolean",
    "default": False,
    "description": (
        "If true, run in background. Returns immediately with a task_id. "
        "The result is delivered as a new conversation turn when the task "
        "completes. Use this for long-running tasks whose result is not "
        "needed immediately."
    ),
}


def _extract_input_model(fn: Callable[..., Any]) -> type[BaseModel] | None:
    """Extract Pydantic BaseModel subclass from first parameter of function.

    :param fn: Function to analyze
    :return: BaseModel subclass or None when no parameter or not BaseModel
    """
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    if not params:
        return None

    annotation = params[0].annotation
    if annotation is inspect.Parameter.empty:
        return None

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    return None


def _build_handler(
    fn: Callable[..., Any],
    model: type[BaseModel] | None,
) -> FunctionToolHandler:
    """Wrap function as async handler including JSON parsing and validation.

    :param fn: Original function (sync or async)
    :param model: Pydantic input model; None for tool without arguments
    :return: FunctionToolHandler (Callable[[str], Awaitable[str]])
    """
    is_async = inspect.iscoroutinefunction(fn)

    async def handler(arguments: str) -> str | FunctionToolResult:
        if model is not None:
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise FunctionToolError(
                    f"Invalid JSON in tool arguments: {exc}"
                ) from None
            try:
                validated = model.model_validate(parsed)
            except ValidationError as exc:
                raise FunctionToolError(str(exc)) from None

            if is_async:
                return await fn(validated)
            return await asyncio.to_thread(fn, validated)

        # Tool without parameters
        if is_async:
            return await fn()
        return await asyncio.to_thread(fn)

    return handler


def make_tool(
    fn: Callable[..., str | FunctionToolResult | Awaitable[str | FunctionToolResult]],
    *,
    name: str | None = None,
    description: str | None = None,
    input_model: type[BaseModel] | None = None,
    supports_background: bool = False,
) -> FunctionTool:
    """Create Tool from Python function.

    Automatically extract ToolSpec from function name, docstring, and Pydantic
    input model.
    name and description can be explicitly overridden.

    ``supports_background=True``then:
    - Automatically inject ``run_in_background: boolean`` parameter into input schema.
    - When handler is called with ``run_in_background=True``, execute with
      ``asyncio.create_task`` and immediately return ``BackgroundHandle``. Engine
      recognizes it, registers task in registry, and returns ``initial_message`` to LLM.
    - This option is internal to make_tool and is not stored in ``FunctionToolSpec``.

    Usage example::

        class ExecuteCodeInput(BaseModel):
            command: str = Field(description="Shell command to run")
            timeout: int = Field(default=30, description="Timeout in seconds")

        async def execute_code(args: ExecuteCodeInput) -> str:
            \"\"\"Execute a shell command in the runtime workspace.\"\"\"
            ...

        tool = make_tool(execute_code, supports_background=True)

    :param fn: Function to convert to tool (sync or async)
    :param name: Tool name; uses ``fn.__name__`` when unspecified
    :param description: Tool description; uses ``fn.__doc__`` when unspecified
    :param input_model: Explicit input model; extracted from function annotation
        when unspecified
    :param supports_background: When True, enable schema injection plus
        BackgroundHandle wrapping
    :return: FunctionTool instance
    :raises ValueError: When description cannot be determined
    """
    tool_name = name or fn.__name__

    tool_description = description or (fn.__doc__ or "").strip()
    if not tool_description:
        msg = (
            f"Tool '{tool_name}' has no description. "
            "Provide a docstring or pass description= explicitly."
        )
        raise ValueError(msg)

    model = input_model or _extract_input_model(fn)
    input_schema: dict[str, object] = (
        model.model_json_schema() if model is not None else dict(_EMPTY_SCHEMA)
    )
    if supports_background:
        input_schema = _inject_background_property(input_schema)

    inner_handler = _build_handler(fn, model)
    handler: FunctionToolHandler
    if supports_background:
        handler = _wrap_with_background(inner_handler, tool_name)
    else:
        handler = inner_handler

    return FunctionTool(
        spec=FunctionToolSpec(
            name=tool_name,
            description=tool_description,
            input_schema=input_schema,
        ),
        handler=handler,
    )


def _inject_background_property(schema: dict[str, object]) -> dict[str, object]:
    """Inject ``run_in_background: boolean`` property into input schema.

    Shallow-copy existing schema and return new properties dict.
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    new_properties: dict[str, object] = {**properties}
    new_properties["run_in_background"] = dict(_RUN_IN_BACKGROUND_PROPERTY)
    return {**schema, "properties": new_properties}


def _wrap_with_background(
    inner_handler: FunctionToolHandler,
    tool_name: str,
) -> FunctionToolHandler:
    """Wrap handler with background-capable wrapper.

    Extract ``run_in_background`` from args:
    - When True: execute inner_handler with asyncio.create_task and immediately
      return BackgroundHandle
    - When False: await inner_handler and perform existing blocking behavior
    """

    async def wrapped(
        arguments: str,
    ) -> str | FunctionToolResult | BackgroundHandle:
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise FunctionToolError(f"Invalid JSON in tool arguments: {exc}") from None
        if not isinstance(parsed, dict):
            raise FunctionToolError("Tool arguments must be a JSON object")
        run_in_background = bool(parsed.pop("run_in_background", False))
        clean_args_json = json.dumps(parsed, ensure_ascii=False)

        if not run_in_background:
            return await inner_handler(clean_args_json)

        task_id = uuid7().hex
        future: asyncio.Task[str | FunctionToolResult] = asyncio.create_task(
            _run_inner(inner_handler, clean_args_json),
            name=f"bg_tool_{tool_name}_{task_id}",
        )
        initial_message = json.dumps(
            {
                "task_id": task_id,
                "status": "running",
                "tool": tool_name,
                "note": (
                    "Task running in background. A notification with the "
                    "result will arrive as a new message when it completes. "
                    "Use task_status to check progress or task_stop to cancel."
                ),
            },
            ensure_ascii=False,
        )
        return BackgroundHandle(
            task_id=task_id,
            future=future,
            initial_message=initial_message,
        )

    return wrapped


async def _run_inner(
    inner_handler: FunctionToolHandler,
    clean_args_json: str,
) -> str | FunctionToolResult:
    """Inner handler wrapper for background execution.

    BackgroundHandle is dedicated to blocking return path, so prevent abnormal case
    where inner_handler returns BackgroundHandle inside wrapped coroutine and force
    str | FunctionToolResult.
    """
    result = await inner_handler(clean_args_json)
    if isinstance(result, BackgroundHandle):
        # Defensive handling: returning BackgroundHandle from inner handler does not
        # match make_tool semantics. Replace with error message.
        raise FunctionToolError(
            "Inner handler returned BackgroundHandle in background mode; "
            "this is not supported."
        )
    return result
