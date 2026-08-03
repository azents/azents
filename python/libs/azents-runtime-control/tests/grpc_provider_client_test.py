"""gRPC Provider Control client tests."""

# pyright: reportAttributeAccessIssue=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest
from google.protobuf import struct_pb2

from azents_runtime_control.grpc_provider_client import (
    PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    PROVIDER_AUTH_METHOD_KUBERNETES_SERVICE_ACCOUNT,
    GrpcProviderControlClient,
    RuntimeProviderControlStreamClosed,
)
from azents_runtime_control.proto import (
    runtime_configuration_pb2,
    runtime_provider_control_pb2,
)
from azents_runtime_control.provider import (
    ProviderCommandCompletion,
    ProviderRegistration,
    RuntimeProviderObservedState,
    RuntimeProviderReport,
)
from azents_runtime_control.runtime_configuration import (
    JsonValue,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
    parse_runtime_configuration_envelope,
)


@pytest.mark.asyncio
async def test_grpc_client_registers_heartbeats_claims_and_completes() -> None:
    """The client maps the gRPC stream onto the ProviderControlClient protocol."""
    sent: list[runtime_provider_control_pb2.ProviderMessage] = []

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del metadata
        register = await anext(requests)
        sent.append(register)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id=register.register.provider_id,
                connection_id=register.connection_id,
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )
        command_payload = struct_pb2.Struct()
        command_payload.update(
            {"auth": {"runner_auth_credential_id": "runner-credential-1"}}
        )
        runtime_configuration = _runtime_configuration_document()
        yield runtime_provider_control_pb2.ControlMessage(
            request_id="req-1",
            provider_command=runtime_provider_control_pb2.ProviderCommand(
                runtime_id="runtime-1",
                agent_id="agent-1",
                workspace_id="workspace-1",
                desired_generation=5,
                provider_generation=3,
                command_type="start",
                runner_image="runner:latest",
                control_endpoint="runtime-control:8020",
                transfer_endpoint="runtime-transfer:8030",
                runner_auth_token="runner-token",
                payload=command_payload,
                runtime_configuration=runtime_configuration_pb2.RuntimeConfigurationEnvelope(
                    evidence=runtime_configuration_pb2.RuntimeConfigurationEvidence(
                        revision_id="revision-1",
                        digest="d" * 64,
                        desired_generation=5,
                    ),
                    resolved_configuration_json=canonical_runtime_configuration_json(
                        runtime_configuration
                    ),
                ),
            ),
        )
        heartbeat = await anext(requests)
        sent.append(heartbeat)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=heartbeat.request_id,
            heartbeat_ack=runtime_provider_control_pb2.ProviderHeartbeatAck(
                monotonic_sequence=heartbeat.heartbeat.monotonic_sequence,
            ),
        )
        completion = await anext(requests)
        sent.append(completion)

    client = GrpcProviderControlClient(
        stream,
        provider_credential="provider-secret",
        provider_auth_method=PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    )
    accepted = await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    command = await client.claim_next_provider_command(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="consumer-1",
        block_ms=100,
    )

    assert accepted.generation == 3
    assert sent[0].register.capability_contract["schema_version"] == 1
    assert command is not None
    assert command.command.identity.runtime_id == "runtime-1"
    assert command.command.auth.control_endpoint == "runtime-control:8020"
    assert command.command.auth.transfer_endpoint == "runtime-transfer:8030"
    assert command.command.auth.runner_auth_token == "runner-token"
    assert command.command.auth.runner_auth_credential_id == "runner-credential-1"
    parsed = parse_runtime_configuration_envelope(
        command.command.runtime_configuration,
        desired_generation=5,
        expected_provider_kind="docker",
    )
    assert parsed.provider.logical_id == "provider-1"
    assert await client.heartbeat_provider(
        provider_id="provider-1",
        generation=accepted.generation,
        heartbeat_at=_now(),
    )

    await client.complete_provider_command(
        ProviderCommandCompletion(
            request_id=command.request_id,
            generation=accepted.generation,
            success=True,
            report=_report(),
            error_code=None,
            error_message=None,
            completed_at=_now(),
        )
    )
    for _ in range(10):
        if len(sent) >= 3:
            break
        await asyncio.sleep(0)

    assert sent[0].WhichOneof("payload") == "register"
    assert sent[1].WhichOneof("payload") == "heartbeat"
    assert sent[2].command_completion.runtime_id == "runtime-1"
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_close_suppresses_completed_stream_failure() -> None:
    """A control-plane stream close should not escape during client cleanup."""
    closed = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id=register.register.provider_id,
                connection_id=register.connection_id,
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )
        closed.set()
        raise RuntimeProviderControlStreamClosed("stream closed")

    client = GrpcProviderControlClient(
        stream,
        provider_credential="provider-secret",
        provider_auth_method=PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    )
    await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(closed.wait(), timeout=1)
    await asyncio.sleep(0)

    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_sends_explicit_provider_auth_metadata() -> None:
    """The client sends bearer evidence with one explicit Provider auth method."""
    observed_metadata: list[tuple[str, str]] = []

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del requests
        observed_metadata.extend(metadata or ())
        yield runtime_provider_control_pb2.ControlMessage(
            request_id="register",
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id="provider-1",
                connection_id="connection-1",
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )

    client = GrpcProviderControlClient(
        stream,
        provider_credential="provider-secret",
        provider_auth_method=PROVIDER_AUTH_METHOD_KUBERNETES_SERVICE_ACCOUNT,
    )
    await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await client.close()

    assert observed_metadata == [
        ("authorization", "Bearer provider-secret"),
        (
            "x-azents-runtime-provider-auth-method",
            "kubernetes_service_account",
        ),
    ]


def _registration() -> ProviderRegistration:
    return ProviderRegistration(
        provider_id="provider-1",
        provider_type="docker",
        scope="system",
        workspace_id=None,
        protocol_version="agent-runtime-provider.v1",
        capabilities=("lifecycle", "observe"),
        config_schema_version="v1",
        metadata={"region": "test"},
        capability_contract={"schema_version": 1},
    )


def _report() -> RuntimeProviderReport:
    return RuntimeProviderReport(
        runtime_id="runtime-1",
        provider_id="provider-1",
        provider_generation=3,
        observed_state=RuntimeProviderObservedState.RUNNING,
        observed_desired_generation=5,
        provider_runtime_id="runtime-provider-id",
        reason="container_running",
        diagnostic={},
        reported_at=_now(),
        terminal_delete_acknowledged=False,
        runtime_configuration=_runtime_configuration_evidence(),
    )


def _runtime_configuration_evidence() -> RuntimeConfigurationEvidence:
    return RuntimeConfigurationEvidence(
        revision_id="revision-1",
        digest="d" * 64,
        desired_generation=5,
    )


def _runtime_configuration_document() -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "provider": {
            "id": "provider-resource-1",
            "logical_id": "provider-1",
            "kind": "docker",
            "capability_revision_id": "capability-1",
            "capability_digest": "a" * 64,
        },
        "infrastructure_profile": {
            "id": "infrastructure-1",
            "version": 1,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "workspace-profile-1",
            "version": 1,
            "digest": "c" * 64,
        },
        "effective_profile": {
            "profile_kind": "docker_container",
            "contract_family": "docker.container-profile",
            "schema_version": 1,
            "runner_resources": {
                "cpu_reservation_millicores": None,
                "cpu_limit_millicores": None,
                "memory_reservation_bytes": None,
                "memory_limit_bytes": None,
            },
            "network_name": "azents",
        },
    }


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
