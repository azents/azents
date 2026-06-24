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
    """Assembled system prompt and debug analysis payload."""

    prompt: str | None
    analysis: SystemPromptAnalysisPayload | None


def build_system_prompt(
    *,
    agent_prompt: str | None,
    toolkit_prompts: list[ToolkitPromptInput],
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
    for prompt in toolkit_prompts:
        fragment = _fragment(
            id=prompt.id,
            source="toolkit",
            label=prompt.label,
            content=_section(f"Toolkit prompt: {prompt.label}", prompt.content),
            metadata=prompt.metadata,
        )
        toolkit_fragments.append(fragment)
        fragments.append(fragment)

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
    if not final_prompt:
        return SystemPromptBuildResult(prompt=None, analysis=None)

    final_fragment = _fragment(
        id="final",
        source="final",
        label="Final system prompt",
        content=final_prompt,
    )
    return SystemPromptBuildResult(
        prompt=final_prompt,
        analysis=SystemPromptAnalysisPayload(
            agent_prompt=agent_fragment,
            toolkit_prompts=toolkit_fragments,
            injected_prompts=injected_fragments,
            final_prompt=final_fragment,
        ),
    )


def _section(title: str, content: str) -> str:
    """Create system prompt section text."""
    return f"## {title}\n\n{content}"


def _fragment(
    *,
    id: str,
    source: Literal["agent", "toolkit", "turn_injected", "final"],
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
