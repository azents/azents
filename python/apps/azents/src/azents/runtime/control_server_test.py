"""Runtime Control server settings tests."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from azents.runtime.control_server import (
    RuntimeControlSettings,
    runtime_control_transport,
    runtime_web_trusted_transport,
    validate_runtime_control_web_settings,
)


def _settings() -> RuntimeControlSettings:
    return RuntimeControlSettings(
        runtime_control_allow_insecure=True,
        runtime_runner_image="runner:test",
        runtime_runner_control_endpoint="runtime-control:8030",
        runtime_runner_transfer_endpoint="runtime-transfer:8031",
        credential_encryption_key=Fernet.generate_key().decode(),
    )


def test_runtime_control_heartbeat_interval_defaults_to_production_value() -> None:
    assert _settings().testenv_runtime_control_heartbeat_interval_seconds == 20
    assert not _settings().runtime_control_web_transport_enabled
    assert _settings().runtime_control_web_max_active_connections == 128


def test_runtime_control_heartbeat_interval_accepts_positive_testenv_override() -> None:
    settings = _settings().model_copy(
        update={"testenv_runtime_control_heartbeat_interval_seconds": 2}
    )

    assert settings.testenv_runtime_control_heartbeat_interval_seconds == 2


def test_runtime_control_heartbeat_interval_rejects_non_positive_value() -> None:
    with pytest.raises(ValidationError):
        RuntimeControlSettings(
            runtime_control_allow_insecure=True,
            runtime_runner_image="runner:test",
            runtime_runner_control_endpoint="runtime-control:8030",
            runtime_runner_transfer_endpoint="runtime-transfer:8031",
            credential_encryption_key=Fernet.generate_key().decode(),
            testenv_runtime_control_heartbeat_interval_seconds=0,
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


def test_runtime_web_trusted_transport_isolated_mode_matches_control_security(
    tmp_path: Path,
) -> None:
    """Trusted Gateway/Control traffic requires mutual TLS outside local mode."""
    insecure = runtime_web_trusted_transport(_settings())
    assert insecure.server_credentials is None
    assert insecure.channel_credentials is None
    assert insecure.allow_insecure

    certificate = tmp_path / "tls.crt"
    private_key = tmp_path / "tls.key"
    ca = tmp_path / "ca.crt"
    certificate.write_text("certificate")
    private_key.write_text("private-key")
    ca.write_text("ca-certificate")
    secure = runtime_web_trusted_transport(
        _settings().model_copy(
            update={
                "runtime_control_allow_insecure": False,
                "runtime_control_tls_certificate_file": str(certificate),
                "runtime_control_tls_private_key_file": str(private_key),
                "runtime_control_tls_ca_file": str(ca),
            }
        )
    )

    assert secure.server_credentials is not None
    assert secure.channel_credentials is not None
    assert not secure.allow_insecure


def test_runtime_web_settings_reject_unsafe_owner_leases() -> None:
    """Owner polling remains bounded to the committed revocation window."""
    with pytest.raises(ValueError, match="within 1 to 60 seconds"):
        validate_runtime_control_web_settings(
            _settings().model_copy(
                update={
                    "runtime_control_web_transport_enabled": True,
                    "runtime_control_trusted_advertise_address": "127.0.0.1:8032",
                    "runtime_control_web_route_lease_seconds": 61,
                }
            )
        )

    with pytest.raises(ValueError, match="must be host:port"):
        validate_runtime_control_web_settings(
            _settings().model_copy(
                update={"runtime_control_web_transport_enabled": True}
            )
        )
