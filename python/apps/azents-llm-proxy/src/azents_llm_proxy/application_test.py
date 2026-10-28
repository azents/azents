"""Standalone process configuration cannot supply a shared provider account."""

import logging

import pytest

from azents_llm_proxy.application import validate_environment
from azents_llm_proxy.privacy import VendorDiagnostics


@pytest.mark.parametrize(
    "name",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_PROFILE",
        "AWS_SESSION_TOKEN",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "CHATGPT_AUTH_FILE",
        "XAI_API_KEY",
        "LITELLM_MASTER_KEY",
        "LITELLM_LICENSE",
        "WORKER_CONFIG",
        "CONFIG_FILE_PATH",
        "DATABASE_URL",
        "REDIS_URL",
        "SENTRY_DSN",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ],
)
def test_ambient_accounts_config_and_exporters_fail_closed(name: str) -> None:
    secret = "environment-secret-sentinel"
    with pytest.raises(RuntimeError) as caught:
        validate_environment({name: secret})
    assert secret not in str(caught.value)


def test_only_deployment_inputs_and_offline_cost_map_are_accepted() -> None:
    validate_environment(
        {
            "PATH": "/usr/bin",
            "SSL_CERT_FILE": "/run/ca.pem",
            "AZ_LLM_PROXY_RESOLVER_KEY": "resolver-secret-sentinel",
            "AZ_LLM_PROXY_AUTHORITY_URL": "https://authority/internal/llm",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        }
    )
    with pytest.raises(RuntimeError):
        validate_environment({"LITELLM_LOCAL_MODEL_COST_MAP": "False"})


def test_vendor_filter_retains_origin_and_severity_but_not_payload_or_extras() -> None:
    error = ValueError("exception-secret-sentinel")
    record = logging.LogRecord(
        "LiteLLM",
        logging.ERROR,
        "/vendor/codec.py",
        42,
        "prompt-secret-sentinel %s",
        ("argument-secret-sentinel",),
        (ValueError, error, None),
        "transform",
    )
    record.__dict__["provider_body"] = "provider-secret-sentinel"
    assert VendorDiagnostics().filter(record)
    assert record.levelno == logging.ERROR and record.lineno == 42
    assert record.funcName == "transform" and record.name == "LiteLLM"
    assert record.exc_info is None and record.__dict__["exception_type"] == "ValueError"
    for secret in (
        "prompt-secret",
        "argument-secret",
        "exception-secret",
        "provider-secret",
    ):
        assert secret not in repr(record.__dict__)
