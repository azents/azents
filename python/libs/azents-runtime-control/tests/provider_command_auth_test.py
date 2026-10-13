"""Provider command auth ingress contract tests."""

import pytest
from google.protobuf import struct_pb2

from azents_runtime_control.grpc_provider_client import _command
from azents_runtime_control.proto import (
    runtime_configuration_pb2,
    runtime_provider_control_pb2,
)
from azents_runtime_control.provider import JsonValue


def _message(
    payload: dict[str, JsonValue],
) -> runtime_provider_control_pb2.ProviderCommand:
    value = struct_pb2.Struct()
    value.update(payload)
    return runtime_provider_control_pb2.ProviderCommand(
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
        payload=value,
        runtime_configuration=runtime_configuration_pb2.RuntimeConfigurationEnvelope(
            evidence=runtime_configuration_pb2.RuntimeConfigurationEvidence(
                configuration_sequence="1",
                digest="d" * 64,
                desired_generation=5,
            ),
            resolved_configuration_json="{}",
        ),
    )


@pytest.mark.parametrize("insecure", [False, True])
@pytest.mark.parametrize("ca", [None, "", "   ", "  CA material  "])
def test_owner_shaped_payload_survives_protobuf_serialization(
    insecure: bool, ca: str | None
) -> None:
    """Preserve current backend encoder fields and optional CA normalization."""
    message = _message(
        {
            "identity": {
                "runtime_id": "runtime-1",
                "agent_id": "agent-1",
                "workspace_id": "workspace-1",
            },
            "runner_image": "runner:latest",
            "auth": {
                "control_endpoint": "runtime-control:8020",
                "transfer_endpoint": "runtime-transfer:8030",
                "runner_auth_credential_id": "runner-credential-1",
                "control_tls_ca_pem": ca,
                "allow_insecure_control": insecure,
            },
        }
    )
    encoded = message.SerializeToString(deterministic=True)
    command = _command(runtime_provider_control_pb2.ProviderCommand.FromString(encoded))

    assert command.identity.runtime_id == "runtime-1"
    assert command.identity.agent_id == "agent-1"
    assert command.identity.workspace_id == "workspace-1"
    assert command.runner_image == "runner:latest"
    assert command.auth.control_endpoint == "runtime-control:8020"
    assert command.auth.transfer_endpoint == "runtime-transfer:8030"
    assert command.auth.runner_auth_token == "runner-token"
    assert command.auth.runner_auth_credential_id == "runner-credential-1"
    assert command.auth.control_tls_ca_pem == (ca.strip() or None if ca else None)
    assert command.auth.allow_insecure_control is insecure
    assert command.runtime_configuration.evidence.configuration_sequence == 1
    assert command.runtime_configuration.resolved_configuration_json == "{}"
    assert message.SerializeToString(deterministic=True) == encoded


def test_missing_optional_auth_fields_keep_current_defaults() -> None:
    command = _command(
        _message({"auth": {"runner_auth_credential_id": "  runner-credential-1  "}})
    )

    assert command.auth.runner_auth_credential_id == "runner-credential-1"
    assert command.auth.control_tls_ca_pem is None
    assert command.auth.allow_insecure_control is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runner_auth_credential_id", None),
        ("runner_auth_credential_id", ""),
        ("runner_auth_credential_id", "  "),
        ("runner_auth_credential_id", False),
        ("runner_auth_credential_id", 1),
        ("runner_auth_credential_id", []),
        ("runner_auth_credential_id", {}),
        ("control_tls_ca_pem", False),
        ("control_tls_ca_pem", 1),
        ("control_tls_ca_pem", []),
        ("control_tls_ca_pem", {}),
        ("allow_insecure_control", None),
        ("allow_insecure_control", "false"),
        ("allow_insecure_control", "true"),
        ("allow_insecure_control", 0),
        ("allow_insecure_control", 1),
        ("allow_insecure_control", []),
        ("allow_insecure_control", {}),
        ("unknown", "secret-like value"),
    ],
)
def test_auth_rejects_malformed_primitives_and_unknown_fields(
    field: str, value: JsonValue
) -> None:
    auth: dict[str, JsonValue] = {
        "runner_auth_credential_id": "runner-credential-1",
    }
    auth[field] = value
    message = _message({"auth": auth})
    original = message.SerializeToString(deterministic=True)

    with pytest.raises(ValueError) as error:
        _command(message)

    assert "secret-like value" not in str(error.value)
    assert message.SerializeToString(deterministic=True) == original


@pytest.mark.parametrize("auth", [None, False, 1, "auth", [], {}])
def test_auth_object_and_credential_are_required(auth: JsonValue) -> None:
    with pytest.raises(ValueError):
        _command(_message({"auth": auth}))


def test_auth_field_is_required() -> None:
    with pytest.raises(ValueError, match="auth must be an object"):
        _command(_message({}))


def test_unknown_outer_payload_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="payload contains unknown"):
        _command(
            _message(
                {
                    "auth": {"runner_auth_credential_id": "runner-credential-1"},
                    "extra": "secret-like value",
                }
            )
        )


def test_redundant_known_payload_values_do_not_override_protobuf_authority() -> None:
    """The opaque mirrored fields cannot select identities or endpoints."""
    command = _command(
        _message(
            {
                "identity": {"runtime_id": "other", "opaque": {"value": True}},
                "runner_image": {"opaque": "ignored"},
                "auth": {
                    "runner_auth_credential_id": "runner-credential-1",
                    "control_endpoint": {"opaque": "ignored"},
                    "transfer_endpoint": ["ignored"],
                },
            }
        )
    )

    assert command.identity.runtime_id == "runtime-1"
    assert command.runner_image == "runner:latest"
    assert command.auth.control_endpoint == "runtime-control:8020"
    assert command.auth.transfer_endpoint == "runtime-transfer:8030"
