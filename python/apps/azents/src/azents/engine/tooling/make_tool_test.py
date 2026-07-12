"""make_tool utility tests."""

import json

import pytest
from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionToolError
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
