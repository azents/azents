"""Platform GitHub App external validation client tests."""

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from azents.core.github_system_setting import PlatformGitHubAppEffective
from azents.core.system_setting import SystemSettingValidationStatus

from .client import PlatformGitHubAppValidationClient


def _effective() -> PlatformGitHubAppEffective:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return PlatformGitHubAppEffective(
        app_id="123",
        client_id="Iv1.client",
        private_key=private_key,
        client_secret="client-secret",
    )


async def test_validate_uses_injected_urls_and_accepts_bad_verification_code() -> None:
    """Injected provider URLs support deterministic OAuth credential validation."""
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/app":
            return httpx.Response(
                200,
                json={"id": 123, "client_id": "Iv1.client", "slug": "azents-test"},
            )
        return httpx.Response(200, json={"error": "bad_verification_code"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PlatformGitHubAppValidationClient(
            client,
            app_url="https://validation.example/app",
            oauth_token_url="https://validation.example/login/oauth/access_token",
        ).validate(_effective())

    assert requested_urls == [
        "https://validation.example/app",
        "https://validation.example/login/oauth/access_token",
    ]
    assert result.status is SystemSettingValidationStatus.VALID
    assert result.metadata == {"app_slug": "azents-test"}


async def test_validate_classifies_oauth_credentials_without_raw_response() -> None:
    """Incorrect client credentials become a stable sanitized invalid result."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={"id": 123, "client_id": "Iv1.client", "slug": "azents-test"},
            )
        return httpx.Response(
            200,
            json={
                "error": "incorrect_client_credentials",
                "error_description": "provider body must not escape",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PlatformGitHubAppValidationClient(
            client,
            app_url="https://api.github.com/app",
            oauth_token_url="https://github.com/login/oauth/access_token",
        ).validate(_effective())

    assert result.status is SystemSettingValidationStatus.INVALID
    assert result.code == "github_oauth_credentials_invalid"
    assert "provider body" not in repr(result)
    assert "client-secret" not in repr(result)


async def test_validate_classifies_provider_outage_as_unavailable() -> None:
    """Provider outages remain retryable and distinct from invalid credentials."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "secret provider diagnostics"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PlatformGitHubAppValidationClient(
            client,
            app_url="https://api.github.com/app",
            oauth_token_url="https://github.com/login/oauth/access_token",
        ).validate(_effective())

    assert result.status is SystemSettingValidationStatus.UNAVAILABLE
    assert result.code == "github_unavailable"
    assert "provider diagnostics" not in repr(result)


@pytest.mark.parametrize(
    ("status", "content", "expected"),
    [
        (200, b"not-json", SystemSettingValidationStatus.INVALID),
        (200, b"4", SystemSettingValidationStatus.INVALID),
        (200, b"[]", SystemSettingValidationStatus.INVALID),
        (
            400,
            b'{"error":"incorrect_client_credentials"}',
            SystemSettingValidationStatus.INVALID,
        ),
        (
            401,
            b'{"error":"incorrect_client_credentials"}',
            SystemSettingValidationStatus.INVALID,
        ),
        (
            429,
            b'{"error":"bad_verification_code"}',
            SystemSettingValidationStatus.UNAVAILABLE,
        ),
        (
            503,
            b'{"error":"bad_verification_code"}',
            SystemSettingValidationStatus.UNAVAILABLE,
        ),
    ],
)
async def test_sdk_oauth_retains_sanitized_status_contract(
    status: int, content: bytes, expected: SystemSettingValidationStatus
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.extensions["timeout"] == httpx.Timeout(7).as_dict()
        if request.url.path == "/app":
            return httpx.Response(
                200, json={"id": 123, "client_id": "Iv1.client", "slug": "azents-test"}
            )
        return httpx.Response(
            status, content=content, headers={"Content-Type": "application/json"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), timeout=7
    ) as client:
        result = await PlatformGitHubAppValidationClient(
            client,
            app_url="https://validation.example/app",
            oauth_token_url="https://validation.example/login/oauth/access_token",
        ).validate(_effective())
        assert not client.is_closed
    assert len(requests) == 2
    assert result.status is expected
    assert "incorrect_client_credentials" not in repr(result)
    assert "client-secret" not in repr(result)
