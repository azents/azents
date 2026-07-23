"""Runtime Control server settings tests."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from azents.runtime.control_server import (
    RuntimeControlSettings,
    runtime_control_transport,
)


def _settings() -> RuntimeControlSettings:
    return RuntimeControlSettings(
        runtime_control_allow_insecure=True,
        runtime_runner_image="runner:test",
        runtime_runner_control_endpoint="runtime-control:8030",
        credential_encryption_key=Fernet.generate_key().decode(),
    )


def test_runtime_control_transport_allows_explicit_insecure_mode() -> None:
    """Local/test settings may explicitly select insecure transport."""
    transport = runtime_control_transport(_settings())

    assert transport.server_credentials is None
    assert transport.ca_pem is None
    assert transport.allow_insecure


def test_runtime_control_transport_requires_tls_files() -> None:
    """Deployed secure transport fails closed without operator TLS material."""
    settings = _settings().model_copy(update={"runtime_control_allow_insecure": False})

    with pytest.raises(RuntimeError, match="TLS_CERTIFICATE_FILE"):
        runtime_control_transport(settings)


def test_runtime_control_transport_loads_operator_tls(
    tmp_path: Path,
) -> None:
    """Operator files configure server TLS and the Runner trust bundle."""
    certificate = tmp_path / "tls.crt"
    private_key = tmp_path / "tls.key"
    ca = tmp_path / "ca.crt"
    certificate.write_text("certificate")
    private_key.write_text("private-key")
    ca.write_text("ca-certificate")
    settings = _settings().model_copy(
        update={
            "runtime_control_allow_insecure": False,
            "runtime_control_tls_certificate_file": str(certificate),
            "runtime_control_tls_private_key_file": str(private_key),
            "runtime_control_tls_ca_file": str(ca),
        }
    )

    transport = runtime_control_transport(settings)

    assert transport.server_credentials is not None
    assert transport.ca_pem == "ca-certificate"
    assert not transport.allow_insecure
