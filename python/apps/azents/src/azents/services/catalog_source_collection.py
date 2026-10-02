"""Bounded collection of descriptive catalog data without a producer library."""

import dataclasses
import hashlib
import ipaddress
from urllib.parse import urlsplit

import anyio
import httpx2

from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CatalogSourcePayload,
    decode_catalog_source,
)

DEFAULT_CATALOG_SOURCE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
CATALOG_SOURCE_MAX_BYTES = 12 * 1024 * 1024
CATALOG_SOURCE_FETCH_TIMEOUT_SECONDS = 20.0


@dataclasses.dataclass(frozen=True)
class CatalogCollectionPolicy:
    """Explicit bounds and controlled endpoint for one collection operation."""

    source_url: str
    max_bytes: int
    timeout_seconds: float
    allow_testenv_endpoint: bool

    def __post_init__(self) -> None:
        validate_catalog_source_url(
            self.source_url, allow_testenv_endpoint=self.allow_testenv_endpoint
        )
        if isinstance(self.max_bytes, bool) or self.max_bytes <= 0:
            raise ValueError("The catalog response limit must be positive.")
        if isinstance(self.timeout_seconds, bool) or not (
            0 < self.timeout_seconds <= CATALOG_SOURCE_FETCH_TIMEOUT_SECONDS
        ):
            raise ValueError("The catalog timeout must be positive and bounded.")
        if self.max_bytes > CATALOG_SOURCE_MAX_BYTES:
            raise ValueError("The catalog response limit exceeds the maximum.")


@dataclasses.dataclass(frozen=True)
class CollectedCatalogSource:
    """Typed source with independent raw and canonical content identities."""

    source_key: str
    source_kind: str
    source_url: str
    source_hash: str
    raw_document_hash: str
    etag: str | None
    payload: CatalogSourcePayload


@dataclasses.dataclass(frozen=True)
class CatalogSourceCollector:
    """Fetch inert JSON using an injected transport and explicit collection policy."""

    http_client: httpx2.AsyncClient
    policy: CatalogCollectionPolicy

    async def collect(self) -> CollectedCatalogSource:
        """Collect, bound and decode one response without publishing authority.

        :returns: Descriptive typed data and source provenance.
        :raises ValueError: If the response violates the configured byte bounds.
        :raises TimeoutError: If the total collection deadline expires.
        """
        # The operation deadline also bounds a slow trickle of small response chunks.
        with anyio.fail_after(self.policy.timeout_seconds):
            async with self.http_client.stream(
                "GET",
                self.policy.source_url,
                follow_redirects=False,
                timeout=httpx2.Timeout(
                    self.policy.timeout_seconds,
                    connect=min(5.0, self.policy.timeout_seconds),
                ),
                headers={"Accept": "application/json"},
            ) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(
                        "The catalog source must return a complete response."
                    )
                length = response.headers.get("content-length")
                if length is not None:
                    try:
                        declared_length = int(length)
                    except ValueError:
                        raise ValueError(
                            "The catalog source returned an invalid content length."
                        ) from None
                    if not 0 <= declared_length <= self.policy.max_bytes:
                        raise ValueError(
                            "The catalog source response exceeds its limit."
                        )
                etag = response.headers.get("etag")
                if etag is not None and len(etag) > 512:
                    raise ValueError("The catalog source returned an invalid ETag.")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    if len(body) + len(chunk) > self.policy.max_bytes:
                        raise ValueError(
                            "The catalog source response exceeds its limit."
                        )
                    body.extend(chunk)
        raw = bytes(body)
        payload = decode_catalog_source(raw)
        return CollectedCatalogSource(
            source_key=CATALOG_SOURCE_KEY,
            source_kind=CATALOG_SOURCE_KIND,
            source_url=self.policy.source_url,
            source_hash=payload.content_hash,
            raw_document_hash=hashlib.sha256(raw).hexdigest(),
            etag=etag,
            payload=payload,
        )


def validate_catalog_source_url(
    source_url: str, *, allow_testenv_endpoint: bool
) -> None:
    """Allow credential-free HTTPS and explicitly bounded local test endpoints."""
    if any(ord(character) < 33 or ord(character) == 127 for character in source_url):
        raise ValueError(
            "The catalog source URL must not contain whitespace or controls."
        )
    parsed = urlsplit(source_url)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("The catalog source URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("The catalog source URL must not contain a query or fragment.")
    # Access validates malformed ports before handing the URL to the HTTP client.
    if parsed.port == 0:
        raise ValueError("The catalog source URL port must be positive.")
    if parsed.scheme == "https" and parsed.hostname is not None:
        return
    if parsed.scheme == "http" and parsed.hostname is not None:
        if allow_testenv_endpoint and parsed.hostname == "openai-proxy":
            return
        if parsed.hostname == "localhost":
            return
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            if address.is_loopback:
                return
    raise ValueError("The catalog source must use HTTPS or a loopback test endpoint.")
