"""Provider-neutral hosted-tool semantic rendering."""

import json
from typing import assert_never

from azents.engine.events.output_parts import lower_output_to_text
from azents.engine.events.types import (
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolResultPayload,
)


def render_provider_tool_semantic(
    payload: ProviderToolCallPayload | ProviderToolResultPayload,
) -> str:
    """Render canonical provider-tool semantics as deterministic readable text."""
    match payload:
        case ProviderToolCallPayload(name=name, status=status, semantic=semantic):
            event_label = "call"
        case ProviderToolResultPayload(name=name, status=status, semantic=semantic):
            event_label = "result"
        case _:
            assert_never(payload)

    rendered_name = name or "unknown"
    status_suffix = f" {status}" if status is not None else ""
    lines = [f"[Provider tool {event_label}: {rendered_name}{status_suffix}]"]
    if semantic.input:
        lines.extend(["Input:", semantic.input])

    output = lower_output_to_text(semantic.output)
    if output:
        lines.extend(["Output:", output])

    if semantic.references:
        lines.append("References:")
        for reference in semantic.references:
            lines.extend(_render_reference(reference))
    return "\n".join(lines)


def _render_reference(reference: ProviderToolReference) -> list[str]:
    """Render one typed provider-tool reference."""
    primary = reference.uri or reference.title
    first_line = f"- {reference.kind}"
    if primary:
        first_line += f": {primary}"
    lines = [first_line]
    if reference.uri is not None and reference.title is not None:
        lines.append(f"  Title: {reference.title}")
    if reference.excerpt is not None:
        lines.append("  Excerpt:")
        lines.extend(f"    {line}" for line in reference.excerpt.splitlines())
    if reference.metadata:
        metadata = json.dumps(
            reference.metadata,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        lines.append(f"  Metadata: {metadata}")
    return lines
