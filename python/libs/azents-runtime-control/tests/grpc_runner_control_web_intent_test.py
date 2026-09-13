"""Runner Control Runtime Web intent delivery tests."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    runner_web_cancel_intent_from_message,
    runner_web_cancel_intent_to_message,
    runner_web_open_intent_to_message,
)
from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_web_transport_pb2,
)
from azents_runtime_control.runner import RunnerRegistration
from azents_runtime_control.runner_web import (
    RunnerWebCancelIntent,
    RunnerWebCancelReason,
    RunnerWebIdentity,
    RunnerWebOpenIntent,
)
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence


async def test_runner_control_client_delivers_web_open_and_cancel_intents() -> None:
    """Runtime Web admission metadata stays on the existing control stream."""
    opened: list[RunnerWebOpenIntent] = []
    cancelled: list[RunnerWebCancelIntent] = []
    received = asyncio.Event()
    release = asyncio.Event()
    intent = RunnerWebOpenIntent(identity=_identity())

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
            request_id="web-open-1",
            web_open_intent=runner_web_open_intent_to_message(intent),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="web-cancel-1",
            web_cancel_intent=runner_web_cancel_intent_to_message(
                RunnerWebCancelIntent(
                    identity=intent.identity,
                    reason=RunnerWebCancelReason.CALLER,
                )
            ),
        )
        received.set()
        await release.wait()

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_web_open_intent_handler(lambda value: _append(opened, value))
    client.set_web_cancel_intent_handler(lambda value: _append(cancelled, value))
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=datetime.now(UTC),
    )
    await asyncio.wait_for(received.wait(), timeout=1)

    assert accepted.generation == 7
    assert opened == [intent]
    assert cancelled == [
        RunnerWebCancelIntent(
            identity=intent.identity,
            reason=RunnerWebCancelReason.CALLER,
        )
    ]

    release.set()
    await client.close()


def test_runner_control_web_intent_rejects_unspecified_reason() -> None:
    message = runner_web_cancel_intent_to_message(
        RunnerWebCancelIntent(
            identity=_identity(),
            reason=RunnerWebCancelReason.CALLER,
        )
    )
    message.reason = runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_UNSPECIFIED

    with pytest.raises(KeyError):
        runner_web_cancel_intent_from_message(message)


async def _append[T](items: list[T], value: T) -> None:
    items.append(value)


def _identity() -> RunnerWebIdentity:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    return RunnerWebIdentity(
        tunnel_id="tunnel-1",
        endpoint_id="endpoint-1",
        cycle_id="cycle-1",
        endpoint_authority_revision=4,
        close_barrier=1,
        runtime_id="runtime-1",
        desired_generation=5,
        runner_generation=7,
        port=3000,
        join_nonce="nonce-1",
        registration_deadline_at=now + timedelta(seconds=15),
        approval_deadline_at=now + timedelta(minutes=30),
        transport_deadline_at=now + timedelta(minutes=30),
    )


def _registration() -> RunnerRegistration:
    return RunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="agent-runtime-runner.v1",
        capabilities=("runtime-web-http.v1",),
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
