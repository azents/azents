"""Pure, user-safe terminal Run result text."""

from azents.core.enums import AgentRunStatus


def terminal_result_content(
    *,
    status: AgentRunStatus,
    message: str | None,
) -> str:
    """Return sanitized terminal text or the existing status fallback."""
    if message is not None:
        sanitized = message.strip()
        if sanitized and not (
            status is AgentRunStatus.FAILED
            and sanitized.startswith("Model provider error:")
        ):
            return sanitized
    match status:
        case AgentRunStatus.COMPLETED:
            return "The agent run completed without a result message."
        case AgentRunStatus.FAILED:
            return "The agent run failed."
        case AgentRunStatus.STOPPED:
            return "The agent run was stopped."
        case AgentRunStatus.INTERRUPTED:
            return "The agent run was interrupted."
        case AgentRunStatus.CANCELLED:
            return "The agent run was cancelled before completing."
        case _:
            raise ValueError("Terminal result content requires a terminal Run")
