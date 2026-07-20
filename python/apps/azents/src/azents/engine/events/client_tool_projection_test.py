"""Tests for profile-aware client tool catalog projection."""

from pydantic import BaseModel

from azents.core.tools import (
    ProfiledToolkitPrompt,
    Toolkit,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.events.tools import (
    ToolCatalog,
    build_tool_catalog,
    project_tool_catalog_for_client_profiles,
)
from azents.engine.run.client_tool_compatibility import ClientToolProfile
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.emit import PublishedEvent
from azents.engine.run.types import FunctionTool, FunctionToolSpec

_PROFILE = ClientToolProfile.GPT_V4A_APPLY_PATCH


class _Config(BaseModel):
    """Toolkit config for projection tests."""


async def _unconditional_handler(arguments: str) -> str:
    return arguments


async def _profiled_handler(arguments: str) -> str:
    return arguments


class _ProfiledToolkit(Toolkit[_Config]):
    """Toolkit contributing unconditional and profile-gated candidates."""

    async def update_context(self, context: TurnContext) -> ToolkitState:
        del context
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                FunctionTool(
                    spec=FunctionToolSpec(
                        name="edit",
                        description="Edit one value.",
                        input_schema={"type": "object"},
                    ),
                    handler=_unconditional_handler,
                ),
                FunctionTool(
                    spec=FunctionToolSpec(
                        name="apply_patch",
                        description="Apply one patch.",
                        input_schema={"type": "object"},
                    ),
                    handler=_profiled_handler,
                ).with_required_client_tool_profile(_PROFILE),
            ],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        del context
        return "Always use exact file paths."

    async def get_profiled_static_prompts(
        self,
        context: TurnContext,
    ) -> list[ProfiledToolkitPrompt]:
        del context
        return [
            ProfiledToolkitPrompt(
                required_client_tool_profile=_PROFILE,
                content="Use apply_patch for multi-file changes.",
            )
        ]


async def test_projection_excludes_profiled_schema_handler_entry_and_prompt() -> None:
    candidate = await _candidate_catalog()

    projected = project_tool_catalog_for_client_profiles(candidate, frozenset())

    assert list(projected.tools) == ["edit"]
    assert list(projected.entries) == ["edit"]
    assert [tool["name"] for tool in projected.native_tools] == ["edit"]
    assert [prompt.content for prompt in projected.static_prompt_fragment_inputs] == [
        "Always use exact file paths."
    ]
    assert projected.tools["edit"].handler is _unconditional_handler


async def test_projection_includes_profiled_schema_handler_entry_and_prompt() -> None:
    candidate = await _candidate_catalog()

    projected = project_tool_catalog_for_client_profiles(
        candidate,
        frozenset({_PROFILE}),
    )

    assert list(projected.tools) == ["edit", "apply_patch"]
    assert list(projected.entries) == ["edit", "apply_patch"]
    assert [tool["name"] for tool in projected.native_tools] == [
        "apply_patch",
        "edit",
    ]
    assert [prompt.content for prompt in projected.static_prompt_fragment_inputs] == [
        "Always use exact file paths.",
        "Use apply_patch for multi-file changes.",
    ]
    assert projected.tools["apply_patch"].handler is _profiled_handler


async def _candidate_catalog() -> ToolCatalog:
    return await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_ProfiledToolkit(),
                slug="runtime",
                use_prefix=False,
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


async def _noop_publish(event: PublishedEvent) -> None:
    del event
