"""Event runtime system prompt assembly helpers."""

from dataclasses import dataclass
from typing import Literal

from azents.engine.events.types import (
    SystemPromptAnalysisPayload,
    SystemPromptFragmentPayload,
)
from azents.engine.hooks.types import TurnInjectedPrompt

_PROMPT_SECTION_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class ToolkitPromptInput:
    """Toolkit prompt assembly input."""

    id: str
    label: str
    content: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class SystemPromptBuildResult:
    """Assembled system/developer prompts and debug analysis payload."""

    prompt: str | None
    developer_prompts: list[str]
    analysis: SystemPromptAnalysisPayload | None


def build_system_prompt(
    *,
    agent_prompt: str | None,
    static_toolkit_prompts: list[ToolkitPromptInput],
    dynamic_toolkit_prompts: list[ToolkitPromptInput],
    developer_prompts: list[ToolkitPromptInput],
    injected_prompts: list[TurnInjectedPrompt],
) -> SystemPromptBuildResult:
    """Assemble actual model input and debug payload from same source."""
    fragments: list[SystemPromptFragmentPayload] = []
    agent_fragment = None
    if agent_prompt:
        agent_fragment = _fragment(
            id="agent",
            source="agent",
            label="Agent prompt",
            content=_section("Agent prompt", agent_prompt),
        )
        fragments.append(agent_fragment)

    toolkit_fragments: list[SystemPromptFragmentPayload] = []
    for prompt in static_toolkit_prompts:
        fragment = _toolkit_fragment(prompt, layer="static")
        toolkit_fragments.append(fragment)
        fragments.append(fragment)

    for prompt in dynamic_toolkit_prompts:
        fragment = _toolkit_fragment(prompt, layer="dynamic")
        toolkit_fragments.append(fragment)
        fragments.append(fragment)

    developer_fragments = [
        _fragment(
            id=prompt.id,
            source="developer_prompt",
            label=prompt.label,
            content=prompt.content,
            metadata=prompt.metadata,
        )
        for prompt in developer_prompts
    ]

    injected_fragments: list[SystemPromptFragmentPayload] = []
    for index, prompt in enumerate(injected_prompts):
        fragment = _fragment(
            id=f"turn-injected-{index}",
            source="turn_injected",
            label=_injected_prompt_label(prompt, index),
            content=_section(_injected_prompt_label(prompt, index), prompt.text),
            metadata=_injected_prompt_metadata(prompt),
        )
        injected_fragments.append(fragment)
        fragments.append(fragment)

    final_prompt = _PROMPT_SECTION_SEPARATOR.join(
        fragment.content for fragment in fragments if fragment.content
    )
    developer_prompt_texts = [fragment.content for fragment in developer_fragments]
    if not final_prompt and not developer_prompt_texts:
        return SystemPromptBuildResult(
            prompt=None,
            developer_prompts=[],
            analysis=None,
        )

    final_fragment = (
        _fragment(
            id="final",
            source="final",
            label="Final system prompt",
            content=final_prompt,
        )
        if final_prompt
        else None
    )
    return SystemPromptBuildResult(
        prompt=final_prompt or None,
        developer_prompts=developer_prompt_texts,
        analysis=SystemPromptAnalysisPayload(
            agent_prompt=agent_fragment,
            toolkit_prompts=toolkit_fragments,
            developer_prompts=developer_fragments,
            injected_prompts=injected_fragments,
            final_prompt=final_fragment,
        ),
    )


def _section(title: str, content: str) -> str:
    """Create system prompt section text."""
    return f"## {title}\n\n{content}"


def _toolkit_fragment(
    prompt: ToolkitPromptInput,
    *,
    layer: Literal["static", "dynamic"],
) -> SystemPromptFragmentPayload:
    """Build a toolkit prompt fragment tagged with its prompt layer."""
    title = f"{layer.title()} toolkit prompt: {prompt.label}"
    return _fragment(
        id=prompt.id,
        source="toolkit",
        label=prompt.label,
        content=_section(title, prompt.content),
        metadata={**prompt.metadata, "prompt_layer": layer},
    )


def _fragment(
    *,
    id: str,
    source: Literal[
        "agent",
        "toolkit",
        "developer_prompt",
        "turn_injected",
        "final",
    ],
    label: str,
    content: str,
    metadata: dict[str, str] | None = None,
) -> SystemPromptFragmentPayload:
    """Create system prompt fragment payload."""
    return SystemPromptFragmentPayload(
        id=id,
        source=source,
        label=label,
        content=content,
        preview=_preview(content),
        length=len(content),
        metadata=metadata or {},
    )


def _injected_prompt_label(prompt: TurnInjectedPrompt, index: int) -> str:
    """Return turn injected prompt label."""
    if prompt.hook_provider_slug:
        return f"Turn injected prompt from {prompt.hook_provider_slug}"
    return f"Turn injected prompt {index + 1}"


def _injected_prompt_metadata(prompt: TurnInjectedPrompt) -> dict[str, str]:
    """Return turn injected prompt metadata."""
    metadata = {"persistence": prompt.persistence}
    if prompt.hook_provider_slug is not None:
        metadata["hook_provider_slug"] = prompt.hook_provider_slug
    if prompt.hook_prompt_index is not None:
        metadata["hook_prompt_index"] = str(prompt.hook_prompt_index)
    return metadata


def _preview(text: str, *, max_chars: int = 240) -> str:
    """Return prompt preview string."""
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars]}..."
