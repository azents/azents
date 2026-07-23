"""gRPC client transport security tests."""

from unittest.mock import Mock, patch

import pytest

from azents_runtime_control.grpc_tls import (
    GrpcClientTlsConfig,
    create_grpc_aio_channel,
)


def test_tls_config_rejects_empty_trust_bundle() -> None:
    """A secure channel requires a non-empty trust bundle."""
    with pytest.raises(ValueError, match="root_certificates"):
        GrpcClientTlsConfig(root_certificates=b" \n")


def test_channel_requires_tls_or_explicit_insecure_mode() -> None:
    """Implicit plaintext transport is rejected."""
    with pytest.raises(ValueError, match="explicitly allowed"):
        create_grpc_aio_channel(
            "runtime-control:8030",
            tls=None,
            allow_insecure=False,
        )


def test_channel_uses_server_authenticated_tls() -> None:
    """Configured roots create a secure gRPC channel."""
    channel = Mock()
    credentials = Mock()
    with (
        patch(
            "azents_runtime_control.grpc_tls.grpc.ssl_channel_credentials",
            return_value=credentials,
        ) as create_credentials,
        patch(
            "azents_runtime_control.grpc_tls.grpc.aio.secure_channel",
            return_value=channel,
        ) as create_channel,
    ):
        result = create_grpc_aio_channel(
            "runtime-control:8030",
            tls=GrpcClientTlsConfig(root_certificates=b"test-ca"),
            allow_insecure=False,
        )

    assert result is channel
    create_credentials.assert_called_once_with(root_certificates=b"test-ca")
    create_channel.assert_called_once_with("runtime-control:8030", credentials)


def test_channel_allows_explicit_local_insecure_mode() -> None:
    """Local/test callers can opt into plaintext transport."""
    channel = Mock()
    with patch(
        "azents_runtime_control.grpc_tls.grpc.aio.insecure_channel",
        return_value=channel,
    ) as create_channel:
        result = create_grpc_aio_channel(
            "localhost:8030",
            tls=None,
            allow_insecure=True,
        )

    assert result is channel
    create_channel.assert_called_once_with("localhost:8030")
