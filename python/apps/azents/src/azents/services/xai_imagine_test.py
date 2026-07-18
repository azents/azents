"""xAI Imagine API client tests."""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

import azents.services.xai_imagine as xai_imagine
from azents.services.xai_imagine import (
    XAI_IMAGINE_MODEL,
    XaiImagineAuthenticationError,
    XaiImagineClient,
    XaiImagineInvalidResponseError,
    XaiImaginePermissionError,
    XaiImagineRateLimitError,
    XaiImagineRequest,
    XaiImagineUnavailableError,
)


async def _no_sleep(_delay: float) -> None:
    """Skip retry delay in deterministic tests."""


def _request() -> XaiImagineRequest:
    return XaiImagineRequest(
        prompt="A moonlit harbor",
        aspect_ratio="16:9",
        resolution="2k",
    )


async def test_generate_uses_bearer_auth_and_base64_response() -> None:
    """Send the documented generation contract without exposing a URL fetch."""

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.x.ai/v1/images/generations"
        assert request.headers["authorization"] == "Bearer secret-token"
        body = json.loads(request.content)
        assert body == {
            "model": XAI_IMAGINE_MODEL,
            "prompt": "A moonlit harbor",
            "n": 1,
            "aspect_ratio": "16:9",
            "resolution": "2k",
            "response_format": "b64_json",
        }
        return httpx.Response(200, json={"data": [{"b64_json": "aW1hZ2U="}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        result = await XaiImagineClient(http_client).generate(
            _request(),
            access_token="secret-token",
        )

    assert result == "aW1hZ2U="


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, XaiImagineAuthenticationError),
        (403, XaiImaginePermissionError),
        (429, XaiImagineRateLimitError),
    ],
)
async def test_generate_classifies_provider_errors(
    status: int,
    error_type: type[Exception],
) -> None:
    """Map auth, entitlement, and rate-limit responses without response bodies."""

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "sensitive provider detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        with pytest.raises(error_type) as raised:
            await XaiImagineClient(http_client).generate(
                _request(),
                access_token="secret-token",
            )

    assert "sensitive provider detail" not in str(raised.value)
    assert "secret-token" not in str(raised.value)


async def test_generate_retries_one_server_failure() -> None:
    """Retry a transient server failure once before succeeding."""
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"b64_json": "aW1hZ2U="}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        result = await XaiImagineClient(
            http_client,
            sleep=_no_sleep,
        ).generate(_request(), access_token="secret-token")

    assert result == "aW1hZ2U="
    assert calls == 2


async def test_generate_fails_after_bounded_server_retries() -> None:
    """Stop after the configured bounded provider-unavailable retry."""
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        with pytest.raises(XaiImagineUnavailableError):
            await XaiImagineClient(
                http_client,
                sleep=_no_sleep,
            ).generate(_request(), access_token="secret-token")

    assert calls == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json={"data": [{"url": "https://example.test/image"}]}),
    ],
)
async def test_generate_rejects_invalid_success_response(
    response: httpx.Response,
) -> None:
    """Require exactly one inline Base64 image result."""

    def respond(_request: httpx.Request) -> httpx.Response:
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        with pytest.raises(XaiImagineInvalidResponseError):
            await XaiImagineClient(http_client).generate(
                _request(),
                access_token="secret-token",
            )


class _ChunkedOversizedStream(httpx.AsyncByteStream):
    """Expose whether the client stops reading after the byte cap is crossed."""

    def __init__(self) -> None:
        self.yielded = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in (b"1234", b"5", b"unread"):
            self.yielded += 1
            yield chunk


async def test_generate_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop streaming response bytes as soon as the configured cap is crossed."""
    monkeypatch.setattr(xai_imagine, "_MAX_RESPONSE_BYTES", 4)
    stream = _ChunkedOversizedStream()

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        with pytest.raises(XaiImagineInvalidResponseError, match="size limit"):
            await XaiImagineClient(http_client).generate(
                _request(),
                access_token="secret-token",
            )

    assert stream.yielded == 2


class _CancellingTransport(httpx.AsyncBaseTransport):
    """Cancel the in-flight HTTP request."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        del request
        raise asyncio.CancelledError


async def test_generate_propagates_cancellation() -> None:
    """Do not convert run cancellation into a retryable provider failure."""
    async with httpx.AsyncClient(transport=_CancellingTransport()) as http_client:
        with pytest.raises(asyncio.CancelledError):
            await XaiImagineClient(http_client).generate(
                _request(),
                access_token="secret-token",
            )
