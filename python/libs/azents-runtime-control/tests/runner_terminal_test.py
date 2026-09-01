"""Shared Runtime Runner Terminal contract tests."""

from datetime import UTC, datetime

import pytest

from azents_runtime_control.runner_terminal import (
    MAX_TERMINAL_DATA_CHUNK_BYTES,
    RunnerTerminalIdentity,
    RunnerTerminalInputFrame,
    RunnerTerminalOpenIntent,
    RunnerTerminalStreamRegistration,
)


def test_terminal_stream_registration_accepts_exact_partial_input_resume() -> None:
    """A partial input frame must be the next sequence after completed input."""
    registration = RunnerTerminalStreamRegistration(
        identity=RunnerTerminalIdentity(
            terminal_id="terminal-1",
            runtime_id="runtime-1",
            runner_generation=7,
        ),
        stream_generation=2,
        stream_nonce="nonce-1",
        last_control_acknowledged_output_sequence=11,
        highest_completely_applied_input_sequence=4,
        partial_input_sequence=5,
        partial_input_bytes_written=9,
    )

    assert registration.partial_input_sequence == 5
    assert registration.partial_input_bytes_written == 9


@pytest.mark.parametrize(
    ("partial_sequence", "partial_offset", "message"),
    [
        (None, 1, "requires partial_input_sequence"),
        (7, None, "requires partial_input_bytes_written"),
        (7, 1, "must follow the highest applied sequence"),
        (5, MAX_TERMINAL_DATA_CHUNK_BYTES, "must be within one Terminal data chunk"),
    ],
)
def test_terminal_stream_registration_rejects_inconsistent_partial_input_resume(
    partial_sequence: int | None,
    partial_offset: int | None,
    message: str,
) -> None:
    """Resume evidence cannot permit duplicate or ambiguous PTY input writes."""
    with pytest.raises(ValueError, match=message):
        RunnerTerminalStreamRegistration(
            identity=RunnerTerminalIdentity(
                terminal_id="terminal-1",
                runtime_id="runtime-1",
                runner_generation=7,
            ),
            stream_generation=2,
            stream_nonce="nonce-1",
            last_control_acknowledged_output_sequence=11,
            highest_completely_applied_input_sequence=4,
            partial_input_sequence=partial_sequence,
            partial_input_bytes_written=partial_offset,
        )


@pytest.mark.parametrize("size", (0, MAX_TERMINAL_DATA_CHUNK_BYTES + 1))
def test_terminal_input_rejects_outside_bounded_wire_chunk(size: int) -> None:
    """Terminal input bytes remain bounded before they reach gRPC."""
    with pytest.raises(ValueError, match="Terminal data"):
        RunnerTerminalInputFrame(sequence=1, data=b"x" * size)


def test_terminal_open_intent_requires_timezone_aware_deadlines() -> None:
    """Time-bound Terminal admission never accepts a naive deadline."""
    deadline = datetime(2026, 9, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="idle_deadline_at must be timezone-aware"):
        RunnerTerminalOpenIntent(
            identity=RunnerTerminalIdentity(
                terminal_id="terminal-1",
                runtime_id="runtime-1",
                runner_generation=7,
            ),
            owner_session_id="session-1",
            working_directory="/workspace/agent",
            columns=80,
            rows=24,
            idle_deadline_at=deadline.replace(tzinfo=None),
            maximum_deadline_at=deadline,
            data_stream_grace_deadline_at=deadline,
            stream_nonce="nonce-1",
            initial_stream_generation=1,
        )
