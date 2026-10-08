"""Request-local native compatibility, independent from Memory access authority."""

import hashlib
import json
from collections.abc import Mapping, Sequence


def native_replay_schema_version(
    instructions: str | None, *, native_replay_context: str | None
) -> str:
    """Bind opaque state to prepared text and already admitted selection identity."""
    if instructions is None:
        return "2-unbound"
    material = json.dumps(
        [instructions, native_replay_context],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"2-prefix-{digest}"


def responses_replay_schema_version(
    items: Sequence[Mapping[str, object]],
    options: Mapping[str, object],
    *,
    native_replay_context: str | None,
) -> str:
    """Inspect actual Responses instructions or the input-owned system prefix."""
    instructions = options.get("instructions")
    if isinstance(instructions, str):
        return native_replay_schema_version(
            instructions, native_replay_context=native_replay_context
        )
    if items:
        first = items[0]
        content = first.get("content")
        if first.get("role") == "system" and isinstance(content, str):
            return native_replay_schema_version(
                content, native_replay_context=native_replay_context
            )
    return native_replay_schema_version(
        None, native_replay_context=native_replay_context
    )
