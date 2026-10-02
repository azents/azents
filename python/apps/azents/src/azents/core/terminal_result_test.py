"""User-safe terminal result text shared by finalization and repair."""

import pytest

from azents.core.enums import AgentRunStatus
from azents.core.terminal_result import terminal_result_content


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (AgentRunStatus.COMPLETED, "The agent run completed without a result message."),
        (AgentRunStatus.FAILED, "The agent run failed."),
        (AgentRunStatus.STOPPED, "The agent run was stopped."),
        (AgentRunStatus.INTERRUPTED, "The agent run was interrupted."),
        (AgentRunStatus.CANCELLED, "The agent run was cancelled before completing."),
    ],
)
@pytest.mark.parametrize("message", [None, "", " \n\t "])
def test_terminal_status_fallbacks(
    status: AgentRunStatus,
    expected: str,
    message: str | None,
) -> None:
    assert terminal_result_content(status=status, message=message) == expected


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (AgentRunStatus.FAILED, " Safe runtime failure. ", "Safe runtime failure."),
        (
            AgentRunStatus.FAILED,
            " Model provider error: provider-private detail ",
            "The agent run failed.",
        ),
        (
            AgentRunStatus.COMPLETED,
            "Model provider error: quoted user-safe result",
            "Model provider error: quoted user-safe result",
        ),
    ],
)
def test_safe_terminal_message_projection(
    status: AgentRunStatus,
    message: str,
    expected: str,
) -> None:
    assert terminal_result_content(status=status, message=message) == expected


def test_empty_nonterminal_projection_requires_terminal_status() -> None:
    with pytest.raises(ValueError, match="requires a terminal Run"):
        terminal_result_content(status=AgentRunStatus.RUNNING, message=None)
