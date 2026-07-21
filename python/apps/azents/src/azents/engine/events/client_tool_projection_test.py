"""Tests for generic client tool wire-variant projection."""

import pytest
from pydantic import BaseModel

from azents.core.enums import LLMProvider
from azents.core.tools import Toolkit, ToolkitState, ToolkitStatus, TurnContext
from azents.engine.events.tools import (
    ToolCatalog,
    build_tool_catalog,
    project_tool_catalog_for_client_compatibility,
)
from azents.engine.run.client_tool_compatibility import (
    ClientToolAdapterProfile,
    ClientToolModelProfile,
    ClientToolRoute,
    resolve_client_tool_adapter_profile,
)
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.emit import PublishedEvent
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolHandler,
    FunctionToolSpec,
    FunctionToolWireVariant,
)

_PROFILE = ClientToolModelProfile.V4A_PATCH
_TOOL_NAME = "batch_update"
_JSON_GUIDANCE = "Send structured arguments for batch updates."
_PLAINTEXT_GUIDANCE = "Send one plaintext batch update request."


class _Config(BaseModel):
    """Toolkit config for projection tests."""


async def _unconditional_handler(arguments: str) -> str:
    return arguments


async def _json_only_handler(arguments: str) -> str:
    return arguments


class _DualDialectHandler:
    """Test handler implementing both generic transport dialects."""

    async def __call__(self, arguments: str) -> str:
        """Execute the JSON-function variant."""
        return arguments

    async def execute_plaintext_custom(self, arguments: str) -> str:
        """Execute the plaintext-custom variant."""
        return arguments


class _VariantToolkit(Toolkit[_Config]):
    """Toolkit contributing unconditional and profile-gated candidates."""

    def __init__(self, handler: FunctionToolHandler) -> None:
        self.handler = handler

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
                        name=_TOOL_NAME,
                        description="Apply one batch update.",
                        input_schema={"type": "object"},
                    ),
                    handler=self.handler,
                    required_client_tool_model_profile=_PROFILE,
                    wire_variants=(
                        FunctionToolWireVariant(
                            wire_dialect="json_function",
                            model_guidance=_JSON_GUIDANCE,
                        ),
                        FunctionToolWireVariant(
                            wire_dialect="plaintext_custom",
                            model_guidance=_PLAINTEXT_GUIDANCE,
                        ),
                    ),
                ),
            ],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        del context
        return "Always use exact resource identifiers."


async def test_projection_excludes_semantically_ineligible_tool_and_guidance() -> None:
    candidate = await _candidate_catalog(_DualDialectHandler())

    projected = project_tool_catalog_for_client_compatibility(
        candidate,
        frozenset(),
        _adapter_profile(provider=LLMProvider.OPENAI, adapter="openai"),
    )

    assert list(projected.tools) == ["edit"]
    assert list(projected.entries) == ["edit"]
    assert [tool["name"] for tool in projected.native_tools] == ["edit"]
    assert [prompt.content for prompt in projected.static_prompt_fragment_inputs] == [
        "Always use exact resource identifiers."
    ]
    assert projected.tools["edit"].handler is _unconditional_handler


async def test_candidate_catalog_rejects_native_lowering_before_projection() -> None:
    candidate = await _candidate_catalog(_DualDialectHandler())

    assert candidate.wire_dialects == {}
    with pytest.raises(ValueError, match="has not been projected"):
        _ = candidate.native_tools


async def test_native_openai_selects_plaintext_variant_for_neutral_tool_name() -> None:
    handler = _DualDialectHandler()
    candidate = await _candidate_catalog(handler)

    projected = project_tool_catalog_for_client_compatibility(
        candidate,
        frozenset({_PROFILE}),
        _adapter_profile(provider=LLMProvider.OPENAI, adapter="openai"),
    )

    assert list(projected.tools) == ["edit", _TOOL_NAME]
    assert projected.wire_dialects[_TOOL_NAME] == "plaintext_custom"
    assert projected.native_tools == [
        {
            "type": "custom",
            "name": _TOOL_NAME,
            "description": "Apply one batch update.",
            "format": {"type": "text"},
        },
        {
            "type": "function",
            "name": "edit",
            "description": "Edit one value.",
            "parameters": {"type": "object"},
            "strict": False,
        },
    ]
    assert [prompt.content for prompt in projected.static_prompt_fragment_inputs] == [
        "Always use exact resource identifiers.",
        _PLAINTEXT_GUIDANCE,
    ]
    assert projected.tools[_TOOL_NAME].handler is handler


async def test_openrouter_selects_json_variant_and_matching_guidance() -> None:
    candidate = await _candidate_catalog(_DualDialectHandler())

    projected = project_tool_catalog_for_client_compatibility(
        candidate,
        frozenset({_PROFILE}),
        _adapter_profile(provider=LLMProvider.OPENROUTER, adapter="litellm"),
    )

    assert projected.wire_dialects[_TOOL_NAME] == "json_function"
    declaration = next(
        tool for tool in projected.native_tools if tool["name"] == _TOOL_NAME
    )
    assert declaration["type"] == "function"
    assert [prompt.content for prompt in projected.static_prompt_fragment_inputs] == [
        "Always use exact resource identifiers.",
        _JSON_GUIDANCE,
    ]


async def test_generic_litellm_route_omits_profiled_tool_but_keeps_ordinary_tool() -> (
    None
):
    candidate = await _candidate_catalog(_DualDialectHandler())

    projected = project_tool_catalog_for_client_compatibility(
        candidate,
        frozenset({_PROFILE}),
        _adapter_profile(provider=LLMProvider.OPENAI, adapter="litellm"),
    )

    assert list(projected.tools) == ["edit"]
    assert projected.wire_dialects == {"edit": "json_function"}


async def test_variant_guidance_requires_provider_visible_declaration() -> None:
    candidate = await _candidate_catalog(_DualDialectHandler())
    projected = project_tool_catalog_for_client_compatibility(
        candidate,
        frozenset({_PROFILE}),
        _adapter_profile(provider=LLMProvider.OPENAI, adapter="openai"),
    )

    visible_prompts = projected.static_prompt_fragment_inputs_for(["edit"])

    assert [prompt.content for prompt in visible_prompts] == [
        "Always use exact resource identifiers."
    ]


async def test_selected_plaintext_variant_requires_plaintext_handler() -> None:
    candidate = await _candidate_catalog(_json_only_handler)

    with pytest.raises(
        ValueError,
        match="requires a plaintext custom handler",
    ):
        project_tool_catalog_for_client_compatibility(
            candidate,
            frozenset({_PROFILE}),
            _adapter_profile(provider=LLMProvider.OPENAI, adapter="openai"),
        )


async def test_prefixing_preserves_declared_variants() -> None:
    candidate = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_VariantToolkit(_DualDialectHandler()),
                slug="runtime",
                use_prefix=True,
            )
        ],
        context=_turn_context(),
    )

    prefixed = candidate.tools[f"runtime__{_TOOL_NAME}"]

    assert [variant.wire_dialect for variant in prefixed.wire_variants] == [
        "json_function",
        "plaintext_custom",
    ]
    assert prefixed.required_client_tool_model_profile is _PROFILE


async def _candidate_catalog(handler: FunctionToolHandler) -> ToolCatalog:
    return await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                toolkit=_VariantToolkit(handler),
                slug="runtime",
                use_prefix=False,
            )
        ],
        context=_turn_context(),
    )


def _adapter_profile(
    *,
    provider: LLMProvider,
    adapter: str,
) -> ClientToolAdapterProfile:
    profile = resolve_client_tool_adapter_profile(
        route=ClientToolRoute(
            provider=provider,
            adapter=adapter,
            native_format="responses",
        )
    )
    if profile is None:
        raise AssertionError("expected adapter profile")
    return profile


def _turn_context() -> TurnContext:
    return TurnContext(
        user_id="user-1",
        workspace_id="workspace-1",
        model="gpt-5.1",
        run_id="run-1",
        publish_event=_noop_publish,
    )


async def _noop_publish(event: PublishedEvent) -> None:
    del event
