"""Tests for Runtime Web Gateway deployment configuration."""

import pytest
from azcommon.logging import RuntimeEnvironment
from pydantic import ValidationError

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.runtime_web_gateway.settings import (
    RuntimeWebGatewayConfig,
    RuntimeWebGatewaySettings,
)


def _settings(**updates: object) -> RuntimeWebGatewaySettings:
    values: dict[str, object] = {
        "runtime_env": RuntimeEnvironment.DEPLOYED,
        "runtime_web_gateway_enabled": True,
        "runtime_web_gateway_auth_mode": RuntimeWebAuthMode.SEPARATE_DOMAIN,
        "runtime_web_gateway_main_web_origin": "https://app.example.com",
        "runtime_web_gateway_broker_origin": "https://auth.services.example.net",
        "runtime_web_gateway_service_suffix": "services.example.net",
        "runtime_web_gateway_cookie_domain": ".services.example.net",
        "runtime_web_gateway_control_endpoint": "runtime-control:8032",
        "runtime_web_gateway_control_tls_ca_file": "/tls/ca.crt",
        "runtime_web_gateway_control_tls_certificate_file": "/tls/tls.crt",
        "runtime_web_gateway_control_tls_private_key_file": "/tls/tls.key",
    }
    values.update(updates)
    return RuntimeWebGatewaySettings.model_validate(values)


def test_enabled_gateway_normalizes_exact_origins_and_domain() -> None:
    settings = _settings()

    config = RuntimeWebGatewayConfig.from_settings(settings)

    assert config.main_web_origin == "https://app.example.com"
    assert config.broker_origin == "https://auth.services.example.net"
    assert config.service_suffix == "services.example.net"
    assert config.cookie_domain == "services.example.net"
    assert len(settings.security_fingerprint()) == 64


def test_shared_cookie_mode_accepts_one_parent_domain_for_main_and_services() -> None:
    settings = _settings(
        runtime_web_gateway_auth_mode=RuntimeWebAuthMode.SHARED_COOKIE,
        runtime_web_gateway_main_web_origin="https://app.example.com",
        runtime_web_gateway_broker_origin="https://auth.services.example.com",
        runtime_web_gateway_service_suffix="services.example.com",
        runtime_web_gateway_cookie_domain="example.com",
    )

    config = RuntimeWebGatewayConfig.from_settings(settings)

    assert config.cookie_domain == "example.com"
    assert config.service_suffix == "services.example.com"


@pytest.mark.parametrize(
    "updates",
    [
        {"runtime_web_gateway_main_web_origin": None},
        {"runtime_web_gateway_main_web_origin": "http://app.example.com"},
        {"runtime_web_gateway_broker_origin": "https://broker.example.net"},
        {"runtime_web_gateway_cookie_domain": "example.net"},
        {"runtime_web_gateway_control_tls_private_key_file": None},
        {"runtime_web_gateway_identity_cookie_name": "__Secure-unsafe"},
        {"runtime_web_gateway_chromium_min_version": 153},
    ],
)
def test_enabled_gateway_rejects_incomplete_security_configuration(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _settings(**updates)


def test_insecure_control_is_local_only() -> None:
    with pytest.raises(ValidationError):
        _settings(
            runtime_web_gateway_control_allow_insecure=True,
            runtime_web_gateway_control_tls_ca_file=None,
            runtime_web_gateway_control_tls_certificate_file=None,
            runtime_web_gateway_control_tls_private_key_file=None,
        )
