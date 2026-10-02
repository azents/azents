"""Deterministic transport contracts for the inert model catalog collector."""

import hashlib
from collections.abc import AsyncIterator

import anyio
import httpx2
import pytest

from azents.services.catalog_source_collection import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CatalogCollectionPolicy,
    CatalogSourceCollector,
    validate_catalog_source_url,
)

_BODY = (
    b'{"exact-model":{"litellm_provider":"openai","mode":"chat",'
    b'"supports_reasoning":true,"supports_xhigh_reasoning_effort":true}}'
)


def _policy(*, max_bytes: int, timeout_seconds: float) -> CatalogCollectionPolicy:
    return CatalogCollectionPolicy(
        source_url="https://catalog.example/data.json",
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        allow_testenv_endpoint=False,
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://raw.githubusercontent.com/BerriAI/litellm/main/data.json",
        "http://localhost:8080/data.json",
        "http://127.0.0.1/data.json",
        "http://[::1]/data.json",
    ],
)
def test_collection_url_allows_https_and_loopback(url: str) -> None:
    validate_catalog_source_url(url, allow_testenv_endpoint=False)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@catalog.example/data.json",
        "https://catalog.example/data.json?token=secret",
        "https://catalog.example/data.json#fragment",
        "http://remote.example/data.json",
        "file:///tmp/catalog.json",
        "https://",
        "https://catalog.example:invalid/data.json",
        "http://openai-proxy/data.json",
        "https://catalog.example:0/data.json",
        "https://catalog.example/ white.json",
        "https://catalog.example/\ndata.json",
    ],
)
def test_collection_url_rejects_credential_or_untrusted_endpoints(url: str) -> None:
    with pytest.raises(ValueError):
        validate_catalog_source_url(url, allow_testenv_endpoint=False)


def test_testenv_endpoint_requires_explicit_opt_in() -> None:
    validate_catalog_source_url(
        "http://openai-proxy/data.json", allow_testenv_endpoint=True
    )


@pytest.mark.parametrize("limit", [0, -1, True, 12 * 1024 * 1024 + 1])
def test_response_limit_must_be_positive_and_bounded(limit: int) -> None:
    with pytest.raises(ValueError):
        _policy(max_bytes=limit, timeout_seconds=20.0)


@pytest.mark.parametrize("timeout", [0.0, -1.0, 21.0, float("inf"), float("nan"), True])
def test_operation_timeout_is_bounded(timeout: float) -> None:
    with pytest.raises(ValueError):
        _policy(max_bytes=4096, timeout_seconds=timeout)


@pytest.mark.asyncio
async def test_collect_decodes_payload_and_records_both_hashes() -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200, content=_BODY, headers={"etag": '"data-v1"'}, request=request
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        result = await CatalogSourceCollector(
            http_client=http, policy=_policy(max_bytes=len(_BODY), timeout_seconds=20.0)
        ).collect()
    assert len(requests) == 1
    assert requests[0].headers["accept"] == "application/json"
    assert result.source_key == CATALOG_SOURCE_KEY
    assert result.source_kind == CATALOG_SOURCE_KIND
    assert result.raw_document_hash == hashlib.sha256(_BODY).hexdigest()
    assert result.source_hash == result.payload.content_hash
    assert result.etag == '"data-v1"'
    assert result.payload.model_count == 1
    assert result.payload.provider_count == 1
    assert (
        result.payload.lookup_exact(provider="openai", model_key="exact-model")
        is not None
    )
    assert (
        result.payload.lookup_exact(provider="chatgpt", model_key="exact-model") is None
    )


class _ChunkStream(httpx2.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_chunked_body_is_limited_without_content_length() -> None:
    stream = _ChunkStream((b" " * 32, b" " * 32))

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, stream=stream, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        with pytest.raises(ValueError, match="exceeds"):
            await CatalogSourceCollector(
                http_client=http, policy=_policy(max_bytes=63, timeout_seconds=20.0)
            ).collect()
    assert stream.closed


@pytest.mark.parametrize("length", ["999999", "invalid", "-1"])
@pytest.mark.asyncio
async def test_invalid_or_excessive_declared_size_is_rejected(length: str) -> None:
    stream = _ChunkStream((_BODY,))

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, stream=stream, headers={"content-length": length}, request=request
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        with pytest.raises(ValueError):
            await CatalogSourceCollector(
                http_client=http, policy=_policy(max_bytes=4096, timeout_seconds=20.0)
            ).collect()
    assert stream.closed


@pytest.mark.asyncio
async def test_redirect_not_followed_even_when_client_follows_redirects() -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            302,
            headers={"location": "https://unexpected.example/other.json"},
            request=request,
        )

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(respond), follow_redirects=True
    ) as http:
        with pytest.raises((ValueError, httpx2.HTTPStatusError)):
            await CatalogSourceCollector(
                http_client=http, policy=_policy(max_bytes=4096, timeout_seconds=20.0)
            ).collect()
    assert len(requests) == 1


@pytest.mark.parametrize("status", [204, 206, 304, 401, 500])
@pytest.mark.asyncio
async def test_source_requires_complete_success(status: int) -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, content=_BODY, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        with pytest.raises((ValueError, httpx2.HTTPStatusError)):
            await CatalogSourceCollector(
                http_client=http, policy=_policy(max_bytes=4096, timeout_seconds=20.0)
            ).collect()


@pytest.mark.parametrize("body", [b"not json", b"\xff", b'{"key": {}, "key": {}}'])
@pytest.mark.asyncio
async def test_payload_decode_failure_is_not_success(body: bytes) -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=body, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        with pytest.raises((ValueError, UnicodeDecodeError)):
            await CatalogSourceCollector(
                http_client=http, policy=_policy(max_bytes=4096, timeout_seconds=20.0)
            ).collect()


class _StalledStream(httpx2.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        await anyio.sleep_forever()
        yield b""

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_total_deadline_bounds_stalled_mock_stream() -> None:
    stream = _StalledStream()

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, stream=stream, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        with pytest.raises(TimeoutError):
            await CatalogSourceCollector(
                http_client=http, policy=_policy(max_bytes=4096, timeout_seconds=0.01)
            ).collect()
    assert stream.closed
