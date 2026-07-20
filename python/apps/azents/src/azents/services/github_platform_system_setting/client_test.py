"""Platform GitHub App external validation client tests."""

import httpx
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


async def test_validate_accepts_expected_bad_verification_code() -> None:
    """GitHub's bad-code response proves the OAuth client was authenticated."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={"id": 123, "client_id": "Iv1.client", "slug": "azents-test"},
            )
        return httpx.Response(200, json={"error": "bad_verification_code"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PlatformGitHubAppValidationClient(client).validate(_effective())

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
        result = await PlatformGitHubAppValidationClient(client).validate(_effective())

    assert result.status is SystemSettingValidationStatus.INVALID
    assert result.code == "github_oauth_credentials_invalid"
    assert "provider body" not in repr(result)
    assert "client-secret" not in repr(result)


async def test_validate_classifies_provider_outage_as_unavailable() -> None:
    """Provider outages remain retryable and distinct from invalid credentials."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "secret provider diagnostics"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PlatformGitHubAppValidationClient(client).validate(_effective())

    assert result.status is SystemSettingValidationStatus.UNAVAILABLE
    assert result.code == "github_unavailable"
    assert "provider diagnostics" not in repr(result)
