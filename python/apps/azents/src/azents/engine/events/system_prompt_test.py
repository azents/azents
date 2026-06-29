"""System prompt builder tests."""

from azents.engine.events.system_prompt import (
    ToolkitPromptInput,
    build_system_prompt,
)
from azents.engine.hooks.types import TurnInjectedPrompt


def test_build_system_prompt_wraps_sections_and_matches_final_prompt() -> None:
    """The assembled fragments must match the final system prompt."""
    result = build_system_prompt(
        agent_prompt="agent rules",
        static_toolkit_prompts=[
            ToolkitPromptInput(
                id="toolkit-0-static",
                label="github",
                content="github rules",
                metadata={"slug": "github", "prompt_layer": "static"},
            )
        ],
        dynamic_toolkit_prompts=[
            ToolkitPromptInput(
                id="toolkit-1-dynamic",
                label="todo",
                content="todo state",
                metadata={"slug": "todo", "prompt_layer": "dynamic"},
            )
        ],
        injected_prompts=[
            TurnInjectedPrompt(
                persistence="hidden_internal_input",
                text="hook rules",
                hook_provider_slug="hookkit",
                hook_prompt_index=0,
            )
        ],
    )

    assert result.prompt == (
        "## Agent prompt\n\nagent rules\n\n"
        "## Static toolkit prompt: github\n\ngithub rules\n\n"
        "## Dynamic toolkit prompt: todo\n\ntodo state\n\n"
        "## Turn injected prompt from hookkit\n\nhook rules"
    )
    assert result.analysis is not None
    fragments = [
        result.analysis.agent_prompt,
        *result.analysis.toolkit_prompts,
        *result.analysis.injected_prompts,
    ]
    assert result.analysis.final_prompt is not None
    assert "\n\n".join(fragment.content for fragment in fragments if fragment) == (
        result.analysis.final_prompt.content
    )
    assert result.analysis.final_prompt.content == result.prompt


def test_build_system_prompt_returns_empty_when_no_prompt_parts() -> None:
    """Do not generate a system prompt when there are no prompt fragments."""
    result = build_system_prompt(
        agent_prompt=None,
        static_toolkit_prompts=[],
        dynamic_toolkit_prompts=[],
        injected_prompts=[],
    )

    assert result.prompt is None
    assert result.analysis is None
