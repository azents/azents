"""make_tool utility tests."""

import asyncio
import json
from contextlib import suppress

import pytest
from pydantic import BaseModel, Field

from azents.engine.run.types import BackgroundHandle, FunctionToolError
from azents.engine.tooling.make_tool import make_tool

# ---------------------------------------------------------------------------
# Input model for tests
# ---------------------------------------------------------------------------


class GreetInput(BaseModel):
    """Greeting tool input."""

    name: str = Field(description="Name to greet")
    greeting: str = Field(default="Hello", description="Greeting word")


# ---------------------------------------------------------------------------
# Functions for tests
# ---------------------------------------------------------------------------


async def async_greet(args: GreetInput) -> str:
    """Greet someone."""
    return f"{args.greeting}, {args.name}!"


def sync_greet(args: GreetInput) -> str:
    """Greet someone synchronously."""
    return f"{args.greeting}, {args.name}!"


async def no_params_tool() -> str:
    """A tool with no parameters."""
    return "done"


async def no_docstring(args: GreetInput) -> str:
    return f"Hi, {args.name}"


# ---------------------------------------------------------------------------
# name/description extraction tests
# ---------------------------------------------------------------------------


class TestNameDescriptionExtraction:
    """name/description automatic extraction and override tests."""

    def test_auto_extract(self) -> None:
        """Automatically extract from function name and docstring."""
        tool = make_tool(async_greet)
        assert tool.spec.name == "async_greet"
        assert tool.spec.description == "Greet someone."

    def test_override_name(self) -> None:
        """Explicit name is used instead of function name."""
        tool = make_tool(async_greet, name="say_hello")
        assert tool.spec.name == "say_hello"
        assert tool.spec.description == "Greet someone."

    def test_override_description(self) -> None:
        """Explicit description is used instead of docstring."""
        tool = make_tool(async_greet, description="Custom description")
        assert tool.spec.name == "async_greet"
        assert tool.spec.description == "Custom description"

    def test_override_both(self) -> None:
        """Both name and description can be overridden."""
        tool = make_tool(async_greet, name="hi", description="Say hi")
        assert tool.spec.name == "hi"
        assert tool.spec.description == "Say hi"

    def test_no_docstring_raises(self) -> None:
        """ValueError when docstring is absent and description is unspecified."""
        with pytest.raises(ValueError, match="no description"):
            make_tool(no_docstring)

    def test_no_docstring_with_override(self) -> None:
        """Success when description is specified even without docstring."""
        tool = make_tool(no_docstring, description="Greet someone")
        assert tool.spec.description == "Greet someone"


# ---------------------------------------------------------------------------
# input_schema creation tests
# ---------------------------------------------------------------------------


class TestInputSchema:
    """JSON Schema creation tests from Pydantic model."""

    def test_schema_from_model(self) -> None:
        """Correctly create JSON Schema from Pydantic model."""
        tool = make_tool(async_greet)
        schema = tool.spec.input_schema
        assert schema["type"] == "object"
        props = schema["properties"]
        assert isinstance(props, dict)
        assert "name" in props
        assert "greeting" in props

    def test_required_fields(self) -> None:
        """required fields are set correctly."""
        tool = make_tool(async_greet)
        schema = tool.spec.input_schema
        required = schema.get("required")
        assert isinstance(required, list)
        assert "name" in required
        # greeting is not required because it has default
        assert "greeting" not in required

    def test_no_params_empty_schema(self) -> None:
        """Function without parameters creates empty schema."""
        tool = make_tool(no_params_tool)
        assert tool.spec.input_schema == {"type": "object", "properties": {}}

    def test_explicit_schema_overrides_model_facing_schema(self) -> None:
        """Expose an exact schema while retaining Pydantic validation."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }
        tool = make_tool(async_greet, input_schema=schema)

        assert tool.spec.input_schema is schema


# ---------------------------------------------------------------------------
# handler execution tests
# ---------------------------------------------------------------------------


class TestHandler:
    """handler wrapping and execution tests."""

    @pytest.mark.anyio()
    async def test_async_handler(self) -> None:
        """Run async function correctly."""
        tool = make_tool(async_greet)
        result = await tool.handler(json.dumps({"name": "World"}))
        assert result == "Hello, World!"

    @pytest.mark.anyio()
    async def test_async_handler_with_optional(self) -> None:
        """Run correctly with optional parameter."""
        tool = make_tool(async_greet)
        result = await tool.handler(json.dumps({"name": "World", "greeting": "Hi"}))
        assert result == "Hi, World!"

    @pytest.mark.anyio()
    async def test_sync_handler(self) -> None:
        """Wrap sync function as async and run."""
        tool = make_tool(sync_greet)
        result = await tool.handler(json.dumps({"name": "World"}))
        assert result == "Hello, World!"

    @pytest.mark.anyio()
    async def test_no_params_handler(self) -> None:
        """Run function without parameters correctly."""
        tool = make_tool(no_params_tool)
        result = await tool.handler("{}")
        assert result == "done"

    @pytest.mark.anyio()
    async def test_validation_error_raises_tool_error(self) -> None:
        """Raise FunctionToolError on Pydantic validation failure."""
        tool = make_tool(async_greet)
        with pytest.raises(FunctionToolError):
            await tool.handler(json.dumps({"greeting": "Hi"}))  # name missing

    @pytest.mark.anyio()
    async def test_explicit_schema_keeps_pydantic_validation(self) -> None:
        """Validate handler input with the function's Pydantic model."""
        tool = make_tool(
            async_greet,
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        )

        with pytest.raises(FunctionToolError):
            await tool.handler(json.dumps({"greeting": "Hi"}))


# ---------------------------------------------------------------------------
# with_prefix tests
# ---------------------------------------------------------------------------


class TestWithPrefix:
    """Tool.with_prefix() tests."""

    def test_prefix_applied_to_name(self) -> None:
        """prefix is applied to name."""
        tool = make_tool(async_greet)
        prefixed = tool.with_prefix("runtime_")
        assert prefixed.spec.name == "runtime_async_greet"

    def test_description_preserved(self) -> None:
        """description is unchanged."""
        tool = make_tool(async_greet)
        prefixed = tool.with_prefix("runtime_")
        assert prefixed.spec.description == tool.spec.description

    def test_input_schema_shared(self) -> None:
        """input_schema shares same object as original."""
        tool = make_tool(async_greet)
        prefixed = tool.with_prefix("runtime_")
        assert prefixed.spec.input_schema is tool.spec.input_schema

    def test_handler_shared(self) -> None:
        """handler shares same object as original."""
        tool = make_tool(async_greet)
        prefixed = tool.with_prefix("runtime_")
        assert prefixed.handler is tool.handler


# ---------------------------------------------------------------------------
# supports_background mode
# ---------------------------------------------------------------------------


class TestSupportsBackground:
    """Validate ``supports_background=True`` mode behavior."""

    def test_schema_injects_run_in_background_property(self) -> None:
        """supports_background=True injects run_in_background property."""
        tool = make_tool(async_greet, supports_background=True)
        properties = tool.spec.input_schema.get("properties")
        assert isinstance(properties, dict)
        assert "run_in_background" in properties
        rib = properties["run_in_background"]
        assert isinstance(rib, dict)
        assert rib.get("type") == "boolean"
        assert rib.get("default") is False

    def test_schema_unchanged_when_disabled(self) -> None:
        """With default (supports_background=False), schema is unchanged."""
        tool = make_tool(async_greet)
        properties = tool.spec.input_schema.get("properties")
        assert isinstance(properties, dict)
        assert "run_in_background" not in properties

    @pytest.mark.asyncio
    async def test_blocking_path_when_run_in_background_false(self) -> None:
        """run_in_background=False performs existing blocking behavior."""
        tool = make_tool(async_greet, supports_background=True)
        result = await tool.handler(
            json.dumps({"name": "Alice", "run_in_background": False})
        )
        assert result == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_blocking_path_when_run_in_background_missing(self) -> None:
        """Blocking behavior when run_in_background key is absent."""
        tool = make_tool(async_greet, supports_background=True)
        result = await tool.handler(json.dumps({"name": "Bob"}))
        assert result == "Hello, Bob!"

    @pytest.mark.asyncio
    async def test_background_path_returns_handle_immediately(self) -> None:
        """run_in_background=True returns BackgroundHandle immediately."""
        tool = make_tool(async_greet, supports_background=True)
        result = await tool.handler(
            json.dumps({"name": "Carol", "run_in_background": True})
        )
        assert isinstance(result, BackgroundHandle)
        assert result.task_id
        assert "task_id" in result.initial_message
        assert "running" in result.initial_message
        # wait until future completes to check result
        inner_result = await result.future
        assert inner_result == "Hello, Carol!"

    @pytest.mark.asyncio
    async def test_background_path_propagates_input_validation_errors(self) -> None:
        """Inner handler validation error propagates to background future."""
        tool = make_tool(async_greet, supports_background=True)
        result = await tool.handler(
            json.dumps({"run_in_background": True})  # name missing
        )
        assert isinstance(result, BackgroundHandle)
        with pytest.raises(FunctionToolError):
            await result.future

    @pytest.mark.asyncio
    async def test_background_task_can_be_cancelled(self) -> None:
        """BackgroundHandle.future can be cancelled externally."""

        async def slow_task(args: GreetInput) -> str:
            """Slow greeting for cancel test."""
            await asyncio.sleep(10)
            return f"{args.greeting}, {args.name}!"

        tool = make_tool(slow_task, supports_background=True)
        result = await tool.handler(
            json.dumps({"name": "Dan", "run_in_background": True})
        )
        assert isinstance(result, BackgroundHandle)
        result.future.cancel()
        with suppress(asyncio.CancelledError):
            await result.future
        assert result.future.cancelled()
