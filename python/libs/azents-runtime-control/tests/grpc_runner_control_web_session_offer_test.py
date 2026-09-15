"""Runner Control replacement Runtime Web session offer tests."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    runner_session_offer_from_message,
    runner_session_offer_to_message,
)
from azents_runtime_control.proto import runtime_runner_control_pb2
from azents_runtime_control.runner import RunnerRegistration
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from azents_runtime_control.runtime_web_session import (
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
    RunnerSessionOffer,
)


@pytest.mark.asyncio
async def test_runner_control_delivers_exact_web_session_offer() -> None:
    """Deliver the one replacement offer through the ordinary control stream."""
    received: list[RunnerSessionOffer] = []
    offer_received = asyncio.Event()
    release_stream = asyncio.Event()
    offer = _offer()

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
            request_id="web-session-offer-1",
            web_session_offer=runner_session_offer_to_message(offer),
        )
        offer_received.set()
        await release_stream.wait()

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")

    async def on_offer(value: RunnerSessionOffer) -> None:
        received.append(value)

    client.set_web_session_offer_handler(on_offer)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=datetime.now(UTC),
    )
    await asyncio.wait_for(offer_received.wait(), timeout=1)

    assert accepted.generation == 7
    assert received == [offer]

    release_stream.set()
    await client.close()


def test_web_session_offer_round_trip_preserves_exact_authority() -> None:
    """Preserve every Owner, generation, route, TLS, and deadline field."""
    offer = _offer()

    message = runner_session_offer_to_message(offer)

    assert message.owner_replica_id == "control-1"
    assert message.join_nonce == "join-nonce-1"
    assert message.protocol_fingerprint == RUNTIME_WEB_PROTOCOL_FINGERPRINT
    assert runner_session_offer_from_message(message) == offer


def test_web_session_offer_requires_registration_deadline() -> None:
    """Reject an offer that cannot enforce the bounded join window."""
    message = runner_session_offer_to_message(_offer())
    message.ClearField("registration_deadline_at")

    with pytest.raises(ValueError, match="registration deadline"):
        runner_session_offer_from_message(message)


def _offer() -> RunnerSessionOffer:
    return RunnerSessionOffer(
        owner=OwnerSessionEpoch(
            owner_boot_id="owner-boot-1",
            session_lease_id="session-lease-1",
            lease_generation=3,
            runtime_id="runtime-1",
            desired_generation=5,
            runner_generation=7,
        ),
        owner_replica_id="control-1",
        connect_address="control-1.internal:8030",
        tls_server_name="runtime-control.internal",
        session_nonce="join-nonce-1",
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        deadline_at=datetime(2026, 9, 14, tzinfo=UTC) + timedelta(seconds=10),
    )


def _registration() -> RunnerRegistration:
    return RunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="agent-runtime-runner.v1",
        capabilities=("runtime-web-http",),
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
