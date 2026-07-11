"""Utilities for creating Tool from function.

Automatically extracts FunctionToolSpec(name, description, input_schema) from
Python function signature, docstring, and Pydantic input model, and creates a
handler that wraps JSON parsing and validation.

"""

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolHandler,
    FunctionToolResult,
    FunctionToolSpec,
)

# Empty schema for tools without parameters
_EMPTY_SCHEMA: dict[str, object] = {"type": "object", "properties": {}}


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
) -> FunctionTool:
    """Create Tool from Python function.

    Automatically extract ToolSpec from function name, docstring, and Pydantic
    input model.
    name and description can be explicitly overridden.

    :param fn: Function to convert to tool (sync or async)
    :param name: Tool name; uses ``fn.__name__`` when unspecified
    :param description: Tool description; uses ``fn.__doc__`` when unspecified
    :param input_model: Explicit input model; extracted from function annotation
        when unspecified
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
    handler = _build_handler(fn, model)

    return FunctionTool(
        spec=FunctionToolSpec(
            name=tool_name,
            description=tool_description,
            input_schema=input_schema,
        ),
        handler=handler,
    )
