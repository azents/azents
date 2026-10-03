"""Credential-free health transport and unexpected-failure regressions."""

import httpx
import pytest

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_oauth import external_account_oauth_endpoints

from .service import _check_provider_endpoint, _ProviderOAuthUnavailable


async def test_health_probe_checks_all_endpoints_without_credentials() -> None:
    """Preserve provider HTTP rejection tolerance and omit authorization."""
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "authorization" not in request.headers
        return httpx.Response(401)

    endpoints = external_account_oauth_endpoints(ExternalChannelProvider.DISCORD)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await _check_provider_endpoint("discord", endpoints, http_client=client)
    assert [str(request.url) for request in requests] == [
        endpoints.authorization_url,
        endpoints.token_url,
        endpoints.userinfo_url,
    ]


@pytest.mark.parametrize("status", [500, 503])
async def test_health_probe_maps_provider_unavailability(status: int) -> None:
    """Represent known provider server failures without exposing response data."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(
            _ProviderOAuthUnavailable, match="provider_endpoint_unreachable"
        ):
            await _check_provider_endpoint("discord", None, http_client=client)


async def test_health_probe_maps_transport_failure() -> None:
    """Known HTTP transport errors retain the existing unavailable category."""

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider refused connection", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(
            _ProviderOAuthUnavailable, match="provider_endpoint_unreachable"
        ):
            await _check_provider_endpoint("discord", None, http_client=client)


async def test_health_probe_propagates_unrelated_error() -> None:
    """An implementation defect is not reported as provider unavailability."""

    def handle(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("health transport defect")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RuntimeError, match="health transport defect"):
            await _check_provider_endpoint("discord", None, http_client=client)
