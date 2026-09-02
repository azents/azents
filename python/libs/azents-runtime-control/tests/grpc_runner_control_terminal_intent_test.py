"""Runner Control Terminal intent delivery tests."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    runner_terminal_open_intent_to_message,
    runner_terminal_terminate_intent_from_message,
    runner_terminal_terminate_intent_to_message,
)
from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_runner_terminal_pb2,
)
from azents_runtime_control.runner import RunnerRegistration
from azents_runtime_control.runner_terminal import (
    RunnerTerminalIdentity,
    RunnerTerminalOpenIntent,
    RunnerTerminalTerminateIntent,
    RunnerTerminalTerminationReason,
)
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence


@pytest.mark.asyncio
async def test_runner_control_client_delivers_terminal_open_and_terminate_intents() -> (
    None
):
    """Terminal admission metadata stays on the existing Runner Control stream."""
    opened: list[RunnerTerminalOpenIntent] = []
    terminated: list[RunnerTerminalTerminateIntent] = []
    intents_received = asyncio.Event()
    release_stream = asyncio.Event()
    intent = _open_intent()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        assert metadata == (("authorization", "Bearer runner-token"),)
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id="runtime-1",
                runner_id="runner-1",
                connection_id="connection-1",
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="terminal-open-1",
            terminal_open_intent=runner_terminal_open_intent_to_message(intent),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="terminal-stop-1",
            terminal_terminate_intent=runner_terminal_terminate_intent_to_message(
                RunnerTerminalTerminateIntent(
                    identity=intent.identity,
                    reason=RunnerTerminalTerminationReason.CALLER,
                )
            ),
        )
        intents_received.set()
        await release_stream.wait()

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")

    async def on_open(value: RunnerTerminalOpenIntent) -> None:
        opened.append(value)

    async def on_terminate(value: RunnerTerminalTerminateIntent) -> None:
        terminated.append(value)

    client.set_terminal_open_intent_handler(on_open)
    client.set_terminal_terminate_intent_handler(on_terminate)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=datetime.now(UTC),
    )
    await asyncio.wait_for(intents_received.wait(), timeout=1)

    assert accepted.generation == 7
    assert opened == [intent]
    assert terminated == [
        RunnerTerminalTerminateIntent(
            identity=intent.identity,
            reason=RunnerTerminalTerminationReason.CALLER,
        )
    ]

    release_stream.set()
    await client.close()


def test_runner_control_terminal_intent_rejects_unspecified_reason() -> None:
    intent = _open_intent()
    message = runner_terminal_terminate_intent_to_message(
        RunnerTerminalTerminateIntent(
            identity=intent.identity,
            reason=RunnerTerminalTerminationReason.CALLER,
        )
    )
    message.reason = runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_UNSPECIFIED

    with pytest.raises(ValueError):
        runner_terminal_terminate_intent_from_message(message)


def _open_intent() -> RunnerTerminalOpenIntent:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return RunnerTerminalOpenIntent(
        identity=RunnerTerminalIdentity(
            terminal_id="terminal-1",
            runtime_id="runtime-1",
            runner_generation=7,
        ),
        owner_session_id="session-1",
        working_directory="/workspace/agent/.azents/sessions/session-1",
        columns=80,
        rows=24,
        idle_deadline_at=now + timedelta(minutes=30),
        maximum_deadline_at=now + timedelta(hours=8),
        data_stream_grace_deadline_at=now + timedelta(minutes=2),
        stream_nonce="nonce-1",
        initial_stream_generation=1,
    )


def _registration() -> RunnerRegistration:
    return RunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="agent-runtime-runner.v1",
        capabilities=("terminal.v1",),
        health="ok",
        workspace_path="/workspace/agent",
        metadata={},
        auth_credential_id="credential-1",
        runtime_configuration=RuntimeConfigurationEvidence(
            configuration_sequence=1,
            digest="d" * 64,
            desired_generation=5,
        ),
    )
