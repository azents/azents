"""Free-form submitted Markdown and independently bounded historical framing."""

import dataclasses
import re

from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
)

MAX_CONSOLIDATION_RENDERED_BYTES = 10_000
_BOUNDARY = re.compile(r"HISTORICAL MEMORY DATA (?:BEGINS|ENDS)")
_CONTROL = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")


class MemorySubmissionError(ValueError):
    """Correctable artifact feedback, not a terminal execution failure."""

    def __init__(self, message: str, rendered_bytes: int | None) -> None:
        super().__init__(message)
        self.rendered_bytes = rendered_bytes


@dataclasses.dataclass(frozen=True)
class RenderedMemoryResult:
    """Exact authored Markdown and safe complete model-facing result."""

    markdown: str
    rendered_block: str
    empty: bool


def render_submitted_markdown(
    *, key: ConsolidationUnitKey, markdown: str
) -> RenderedMemoryResult:
    """Frame arbitrary Markdown without requiring sections, routes or a ledger."""
    try:
        markdown.encode("utf-8")
    except UnicodeEncodeError:
        raise MemorySubmissionError(
            "Submitted Markdown must be valid UTF-8.", None
        ) from None
    if "\x00" in markdown:
        raise MemorySubmissionError("Submitted Markdown must not contain NUL.", None)
    if not markdown.strip():
        return RenderedMemoryResult("", "", True)
    # Preserve the authored document; only its untrusted model-facing framing
    # escapes boundary tokens and otherwise invisible control characters.
    body = _BOUNDARY.sub(
        lambda match: match.group().replace("DATA", "D\\u200bATA"), markdown
    )
    body = _CONTROL.sub(lambda match: f"\\u{ord(match.group()):04x}", body)
    scope = "Team" if key.scope is ConsolidationScope.TEAM else "Personal"
    rendered = (
        "HISTORICAL MEMORY DATA BEGINS\n"
        f"Scope: {scope}; Agent: {key.agent_id}; Workspace: {key.workspace_id}\n"
        "Historical data may be incomplete, stale, or wrong.\n"
        "Current instructions and verified current evidence take precedence.\n\n"
        f"{body}\n"
        "HISTORICAL MEMORY DATA ENDS\n"
    )
    size = len(rendered.encode("utf-8"))
    if size > MAX_CONSOLIDATION_RENDERED_BYTES:
        raise MemorySubmissionError(
            f"Submitted result uses {size:,} UTF-8 bytes including framing; "
            "the allowance is 10,000 bytes. "
            "Shorten the authored file and submit again.",
            size,
        )
    return RenderedMemoryResult(markdown, rendered, False)
