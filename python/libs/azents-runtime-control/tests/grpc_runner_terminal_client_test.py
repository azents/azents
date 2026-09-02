"""Typed Runtime Runner Terminal gRPC client tests."""

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest

import azents_runtime_control.grpc_runner_terminal_client as terminal_client_module
from azents_runtime_control.grpc_runner_terminal_client import (
    GrpcRunnerTerminalClient,
    runner_terminal_control_to_message,
    runner_terminal_event_from_message,
    runner_terminal_event_to_message,
    runner_terminal_stream_accepted_to_message,
)
from azents_runtime_control.proto import runtime_runner_terminal_pb2
from azents_runtime_control.runner_terminal import (
    RunnerTerminalEventFrame,
    RunnerTerminalExit,
    RunnerTerminalHeartbeatAcknowledgement,
    RunnerTerminalIdentity,
    RunnerTerminalInputAcknowledgement,
    RunnerTerminalInputFrame,
    RunnerTerminalOutputAcknowledgement,
    RunnerTerminalOutputFrame,
    RunnerTerminalResize,
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamError,
    RunnerTerminalStreamErrorCode,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminate,
    RunnerTerminalTerminationReason,
)


@pytest.mark.asyncio
async def test_terminal_client_registers_resumes_and_dispatches_control_frames() -> (
    None
):
    """One Terminal RPC preserves generation and input/output resume evidence."""
    sent: list[runtime_runner_terminal_pb2.RunnerTerminalMessage] = []
    controls: list[object] = []
    controls_received = asyncio.Event()
    event_received = asyncio.Event()
    release_stream = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_runner_terminal_pb2.RunnerTerminalMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_terminal_pb2.TerminalControlMessage]:
        assert metadata == (("authorization", "Bearer runner-token"),)
        register = await anext(requests)
        sent.append(register)
        yield runner_terminal_stream_accepted_to_message(
            RunnerTerminalStreamAccepted(
                stream_generation=2,
                resume_from_output_sequence=11,
                next_input_sequence=6,
            )
        )
        yield runner_terminal_control_to_message(
            RunnerTerminalInputFrame(sequence=6, data=b"echo ready\n")
        )
        yield runner_terminal_control_to_message(
            RunnerTerminalResize(sequence=3, columns=120, rows=40)
        )
        yield runner_terminal_control_to_message(
            RunnerTerminalOutputAcknowledgement(sequence=15)
        )
        yield runner_terminal_control_to_message(
            RunnerTerminalTerminate(reason=RunnerTerminalTerminationReason.CALLER)
        )
        yield runner_terminal_control_to_message(
            RunnerTerminalHeartbeatAcknowledgement(monotonic_sequence=2)
        )
        yield runner_terminal_control_to_message(
            RunnerTerminalStreamError(
                code=RunnerTerminalStreamErrorCode.STALE_AUTHORITY
            )
        )
        controls_received.set()
        event = await anext(requests)
        sent.append(event)
        event_received.set()
        await release_stream.wait()

    client = GrpcRunnerTerminalClient(stream, runner_auth_token="runner-token")

    async def handle_control(frame: object) -> None:
        controls.append(frame)

    client.set_control_handler(handle_control)
    accepted = await client.start(_registration())
    await asyncio.wait_for(controls_received.wait(), timeout=1)
    await client.send(RunnerTerminalOutputFrame(sequence=16, data=b"ready\r\n"))
    await asyncio.wait_for(event_received.wait(), timeout=1)

    assert accepted == RunnerTerminalStreamAccepted(
        stream_generation=2,
        resume_from_output_sequence=11,
        next_input_sequence=6,
    )
    assert sent[0].register.identity.terminal_id == "terminal-1"
    assert sent[0].register.highest_completely_applied_input_sequence == 4
    assert sent[0].register.partial_input_sequence == 5
    assert sent[0].register.partial_input_bytes_written == 3
    assert controls == [
        RunnerTerminalInputFrame(sequence=6, data=b"echo ready\n"),
        RunnerTerminalResize(sequence=3, columns=120, rows=40),
        RunnerTerminalOutputAcknowledgement(sequence=15),
        RunnerTerminalTerminate(reason=RunnerTerminalTerminationReason.CALLER),
        RunnerTerminalHeartbeatAcknowledgement(monotonic_sequence=2),
        RunnerTerminalStreamError(code=RunnerTerminalStreamErrorCode.STALE_AUTHORITY),
    ]
    assert sent[1].output.sequence == 16
    assert sent[1].output.data == b"ready\r\n"

    release_stream.set()
    await client.close()


@pytest.mark.parametrize(
    "frame",
    [
        RunnerTerminalOutputFrame(sequence=1, data=b"output"),
        RunnerTerminalInputAcknowledgement(sequence=2),
        RunnerTerminalExit(
            reason=RunnerTerminalTerminationReason.PROTOCOL_VIOLATION,
            exit_code=1,
        ),
        RunnerTerminalExit(
            reason=RunnerTerminalTerminationReason.PROCESS_EXIT,
            exit_code=0,
        ),
        RunnerTerminalStreamError(code=RunnerTerminalStreamErrorCode.TERMINATED),
    ],
)
def test_terminal_event_codec_round_trips_event_frames(
    frame: RunnerTerminalEventFrame,
) -> None:
    """The Control servicer can decode all content-free Runner event variants."""
    assert (
        runner_terminal_event_from_message(runner_terminal_event_to_message(frame))
        == frame
    )


@pytest.mark.parametrize(
    "message",
    [
        runtime_runner_terminal_pb2.RunnerTerminalMessage(
            exit=runtime_runner_terminal_pb2.TerminalExit(
                reason=(
                    runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_UNSPECIFIED
                )
            )
        ),
        runtime_runner_terminal_pb2.RunnerTerminalMessage(
            error=runtime_runner_terminal_pb2.TerminalStreamError(
                code=runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_UNSPECIFIED
            )
        ),
    ],
)
def test_terminal_event_codec_rejects_unspecified_enums(
    message: runtime_runner_terminal_pb2.RunnerTerminalMessage,
) -> None:
    with pytest.raises(ValueError):
        runner_terminal_event_from_message(message)


@pytest.mark.parametrize(
    "message",
    [
        runtime_runner_terminal_pb2.TerminalControlMessage(
            terminate=runtime_runner_terminal_pb2.TerminalTerminate(
                reason=(
                    runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_UNSPECIFIED
                )
            )
        ),
        runtime_runner_terminal_pb2.TerminalControlMessage(
            error=runtime_runner_terminal_pb2.TerminalStreamError(
                code=runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_UNSPECIFIED
            )
        ),
    ],
)
def test_terminal_control_codec_rejects_unspecified_enums(
    message: runtime_runner_terminal_pb2.TerminalControlMessage,
) -> None:
    with pytest.raises(ValueError):
        terminal_client_module._control_frame_from_message(
            message,
            message.WhichOneof("payload"),
        )


def _registration() -> RunnerTerminalStreamRegistration:
    return RunnerTerminalStreamRegistration(
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
        partial_input_bytes_written=3,
    )
