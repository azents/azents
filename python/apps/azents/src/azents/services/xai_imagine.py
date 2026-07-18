"""xAI Imagine image-generation API client."""

import asyncio
import dataclasses
import json
from collections.abc import Awaitable, Callable

import httpx

XAI_IMAGINE_MODEL = "grok-imagine-image-quality"
_MAX_RESPONSE_BYTES = 30 * 1024 * 1024
_MAX_TRANSPORT_ATTEMPTS = 2


class XaiImagineError(Exception):
    """Base class for sanitized xAI Imagine failures."""


class XaiImagineAuthenticationError(XaiImagineError):
    """Imagine rejected the supplied credential."""


class XaiImaginePermissionError(XaiImagineError):
    """Imagine access is not permitted for the account."""


class XaiImagineRateLimitError(XaiImagineError):
    """Imagine rejected the request because of rate limiting."""


class XaiImagineUnavailableError(XaiImagineError):
    """Imagine was temporarily unavailable."""


class XaiImagineInvalidResponseError(XaiImagineError):
    """Imagine returned an unusable response."""


@dataclasses.dataclass(frozen=True)
class XaiImagineRequest:
    """One xAI Imagine image-generation request."""

    prompt: str
    aspect_ratio: str
    resolution: str


class XaiImagineClient:
    """Invoke the xAI Imagine API with a dependency-injected HTTP client."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        base_url: str,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.sleep = sleep

    async def generate(
        self,
        request: XaiImagineRequest,
        *,
        access_token: str,
    ) -> str:
        """Generate one image and return its Base64 payload."""
        for attempt in range(_MAX_TRANSPORT_ATTEMPTS):
            try:
                async with self.http_client.stream(
                    "POST",
                    f"{self.base_url}/images/generations",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": XAI_IMAGINE_MODEL,
                        "prompt": request.prompt,
                        "n": 1,
                        "aspect_ratio": request.aspect_ratio,
                        "resolution": request.resolution,
                        "response_format": "b64_json",
                    },
                ) as response:
                    if response.status_code == 401:
                        raise XaiImagineAuthenticationError(
                            "xAI Imagine rejected the integration credential."
                        )
                    if response.status_code == 403:
                        raise XaiImaginePermissionError(
                            "xAI Imagine access is not permitted for this account."
                        )
                    if response.status_code == 429:
                        raise XaiImagineRateLimitError(
                            "xAI Imagine rate limit was exceeded."
                        )
                    if 500 <= response.status_code:
                        if attempt + 1 < _MAX_TRANSPORT_ATTEMPTS:
                            await self._backoff(attempt)
                            continue
                        raise XaiImagineUnavailableError(
                            "xAI Imagine is temporarily unavailable."
                        )
                    if not response.is_success:
                        raise XaiImagineInvalidResponseError(
                            f"xAI Imagine returned HTTP {response.status_code}."
                        )
                    return _image_base64(await _read_response_body(response))
            except asyncio.CancelledError:
                raise
            except httpx.HTTPError as exc:
                if attempt + 1 < _MAX_TRANSPORT_ATTEMPTS:
                    await self._backoff(attempt)
                    continue
                raise XaiImagineUnavailableError(
                    "xAI Imagine is temporarily unavailable."
                ) from exc

        raise AssertionError("Imagine transport attempts exhausted unexpectedly")

    async def _backoff(self, attempt: int) -> None:
        """Wait briefly before one bounded transport retry."""
        delay = 0.1 * (attempt + 1)
        if self.sleep is None:
            await asyncio.sleep(delay)
            return
        await self.sleep(delay)


async def _read_response_body(response: httpx.Response) -> bytes:
    """Read one response while enforcing the decoded byte limit."""
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise XaiImagineInvalidResponseError(
                "xAI Imagine returned an invalid response size."
            ) from exc
        if declared_size > _MAX_RESPONSE_BYTES:
            raise XaiImagineInvalidResponseError(
                "xAI Imagine response exceeded the size limit."
            )
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
            raise XaiImagineInvalidResponseError(
                "xAI Imagine response exceeded the size limit."
            )
        body.extend(chunk)
    return bytes(body)


def _image_base64(content: bytes) -> str:
    """Validate and extract one Base64 image from an Imagine response."""
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise XaiImagineInvalidResponseError(
            "xAI Imagine returned invalid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise XaiImagineInvalidResponseError(
            "xAI Imagine returned an invalid response."
        )
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise XaiImagineInvalidResponseError(
            "xAI Imagine returned an invalid image result."
        )
    encoded = data[0].get("b64_json")
    if not isinstance(encoded, str) or not encoded:
        raise XaiImagineInvalidResponseError(
            "xAI Imagine response did not include image data."
        )
    return encoded
