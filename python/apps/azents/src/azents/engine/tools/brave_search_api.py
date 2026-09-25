"""Bounded direct Brave Search API client and fixed-host thumbnail admission."""

import asyncio
import base64
import json
import logging
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError

from azents.engine.events.generated_files import GeneratedFileOutput
from azents.engine.events.provider_output import generated_image_output
from azents.engine.run.errors import ModelCallError
from azents.engine.run.types import FunctionToolError

_API_BASE = "https://api.search.brave.com"
_THUMBNAIL_HOST = "imgs.search.brave.com"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_THUMBNAIL_BYTES = 6 * 1024 * 1024
_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
logger = logging.getLogger(__name__)
type _SearchPath = Literal[
    "/res/v1/web/search",
    "/res/v1/llm/context",
    "/res/v1/news/search",
    "/res/v1/images/search",
    "/res/v1/videos/search",
]


class SearchEntry(BaseModel):
    """Source-attributable normalized search result."""

    title: str = Field(max_length=400)
    url: str = Field(max_length=2048)
    description: str = Field(max_length=1500)
    source: str = Field(max_length=200)
    age: str = Field(max_length=80)


class _WebResult(BaseModel):
    """Brave Web result fields used by the Toolkit."""

    title: str | None = None
    url: str | None = None
    description: str | None = None
    age: str | None = None
    page_age: str | None = None


class _WebResults(BaseModel):
    results: list[_WebResult] = Field(default_factory=list)


class _WebResponse(BaseModel):
    web: _WebResults | None = None


class _ResultProfile(BaseModel):
    name: str | None = None


class _ResultMetaUrl(BaseModel):
    hostname: str | None = None


class _NewsVideoResult(BaseModel):
    title: str | None = None
    url: str | None = None
    description: str | None = None
    age: str | None = None
    page_age: str | None = None
    profile: _ResultProfile | None = None
    meta_url: _ResultMetaUrl | None = None


class _NewsVideoResponse(BaseModel):
    results: list[_NewsVideoResult] = Field(default_factory=list)


class _ContextResult(BaseModel):
    title: str | None = None
    url: str | None = None
    snippets: list[str] | None = None


class _ContextGrounding(BaseModel):
    generic: list[_ContextResult] = Field(default_factory=list)


class _ContextResponse(BaseModel):
    grounding: _ContextGrounding


class _Thumbnail(BaseModel):
    src: str | None = None


class _ImageProperties(BaseModel):
    url: str | None = None


class _ImageResult(BaseModel):
    title: str | None = None
    url: str | None = None
    thumbnail: _Thumbnail | None = None
    properties: _ImageProperties | None = None


class _ImageResponse(BaseModel):
    results: list[_ImageResult]


class ImageEntry(BaseModel):
    """Ranked image metadata and optional acquired thumbnail bytes."""

    rank: int
    title: str
    page_url: str
    image_url: str
    thumbnail_url: str
    attachment: GeneratedFileOutput | None
    unavailable_reason: str | None


class BraveSearchApi:
    """Restrict search to Brave's API and downloads to its image proxy."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    async def _get(
        self,
        path: _SearchPath,
        params: dict[str, str | int],
    ) -> object:
        """Fetch a single fixed endpoint and reject oversized or broken responses."""
        started = time.monotonic()
        status = 0
        failure: str | None = None
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(
                    base_url=_API_BASE,
                    timeout=self._timeout,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "GET",
                        path,
                        params=params,
                        headers={
                            "Accept": "application/json",
                            "X-Subscription-Token": self._api_key,
                        },
                    ) as response:
                        status = response.status_code
                        if response.status_code != 200:
                            failure = "upstream_status"
                            raise FunctionToolError(
                                _safe_api_error(response.status_code)
                            )
                        body = await _bounded_body(response, _MAX_RESPONSE_BYTES)
            return json.loads(body)
        except (TimeoutError, httpx.TimeoutException, httpx.TransportError) as exc:
            failure = "network"
            raise FunctionToolError("Brave Search is temporarily unreachable.") from exc
        except (ValueError, UnicodeError) as exc:
            failure = "invalid_response"
            raise FunctionToolError(
                "Brave Search returned an invalid response."
            ) from exc
        except FunctionToolError:
            failure = failure or "response_limit"
            raise
        finally:
            logger.info(
                "Brave Search API request completed",
                extra={
                    "operation": path,
                    "status_class": status // 100 if status else None,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "failure_category": failure,
                },
            )

    async def search(
        self,
        kind: Literal["web", "context", "news", "videos"],
        params: dict[str, str | int],
    ) -> list[SearchEntry]:
        """Decode one endpoint's bounded attributable search entries."""
        paths: dict[str, _SearchPath] = {
            "web": "/res/v1/web/search",
            "context": "/res/v1/llm/context",
            "news": "/res/v1/news/search",
            "videos": "/res/v1/videos/search",
        }
        payload = await self._get(paths[kind], params)
        try:
            if kind == "web":
                web = _WebResponse.model_validate(payload).web
                rows = web.results if web is not None else []
                candidates = (
                    (
                        row.title or "",
                        row.url,
                        row.description or "",
                        "",
                        row.page_age or row.age or "",
                    )
                    for row in rows
                )
            elif kind == "context":
                rows = _ContextResponse.model_validate(payload).grounding.generic
                candidates = (
                    (
                        row.title or "",
                        row.url,
                        " ".join((row.snippets or [])[:3]),
                        "",
                        "",
                    )
                    for row in rows
                )
            else:
                rows = _NewsVideoResponse.model_validate(payload).results
                candidates = (
                    (
                        row.title or "",
                        row.url,
                        row.description or "",
                        (
                            (row.profile.name if row.profile is not None else None)
                            or (
                                row.meta_url.hostname
                                if row.meta_url is not None
                                else None
                            )
                            or ""
                        ),
                        row.page_age or row.age or "",
                    )
                    for row in rows
                )
            results = [
                SearchEntry(
                    title=title[:400],
                    url=url or "",
                    description=description[:1500],
                    source=source[:200],
                    age=age[:80],
                )
                for title, url, description, source, age in candidates
                if url is not None and _public_url(url)
            ][:20]
            logger.info(
                "Brave Search results decoded",
                extra={"operation": kind, "returned_count": len(results)},
            )
            return results
        except ValidationError as exc:
            raise FunctionToolError("Brave Search returned malformed results.") from exc

    async def search_images(
        self,
        params: dict[str, str | int],
        *,
        attachment_count: int,
    ) -> list[ImageEntry]:
        """Decode ranked images and acquire only a bounded thumbnail selection."""
        payload = await self._get("/res/v1/images/search", params)
        try:
            rows = _ImageResponse.model_validate(payload).results
        except ValidationError as exc:
            raise FunctionToolError(
                "Brave Search returned malformed image results."
            ) from exc
        results: list[ImageEntry] = []
        total_bytes = 0
        for rank, row in enumerate(rows[:20]):
            page_url = row.url if row.url is not None and _public_url(row.url) else ""
            thumbnail_url = (
                row.thumbnail.src
                if row.thumbnail is not None and row.thumbnail.src
                else ""
            )
            original_url = (
                row.properties.url
                if row.properties is not None and row.properties.url
                else ""
            )
            image_url = original_url if _public_url(original_url) else thumbnail_url
            if not page_url or not _public_url(image_url):
                continue
            title = (row.title or "")[:400]
            attachment: GeneratedFileOutput | None = None
            reason: str | None = None
            if len(results) < attachment_count:
                if _allowed_thumbnail(thumbnail_url):
                    try:
                        attachment = await self._thumbnail(thumbnail_url, rank=rank)
                        total_bytes += len(attachment.body)
                        if total_bytes > _MAX_TOTAL_THUMBNAIL_BYTES:
                            attachment = None
                            reason = "Thumbnail aggregate size limit exceeded."
                    except FunctionToolError, ModelCallError, httpx.HTTPError:
                        reason = "Thumbnail was unavailable or unsafe."
                else:
                    reason = "Thumbnail URL was unavailable or unsafe."
            results.append(
                ImageEntry(
                    rank=rank,
                    title=title,
                    page_url=page_url,
                    image_url=image_url,
                    thumbnail_url=thumbnail_url if _public_url(thumbnail_url) else "",
                    attachment=attachment,
                    unavailable_reason=reason,
                )
            )
        logger.info(
            "Brave Search image results decoded",
            extra={
                "operation": "images",
                "returned_count": len(results),
                "images_admitted": sum(row.attachment is not None for row in results),
                "images_skipped": sum(
                    row.unavailable_reason is not None for row in results
                ),
            },
        )
        return results

    async def _thumbnail(self, url: str, *, rank: int) -> GeneratedFileOutput:
        """Fetch a proxy-host image without forwarding authentication or cookies."""
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code != 200:
                            raise FunctionToolError("Thumbnail fetch failed.")
                        media_type = (
                            response.headers.get("content-type", "")
                            .split(";")[0]
                            .lower()
                        )
                        if media_type not in _IMAGE_TYPES:
                            raise FunctionToolError(
                                "Thumbnail content type is not an image."
                            )
                        body = await _bounded_body(response, _MAX_THUMBNAIL_BYTES)
            return generated_image_output(
                f"data:{media_type};base64,{base64.b64encode(body).decode('ascii')}",
                output_index=rank,
            )
        except (TimeoutError, httpx.TimeoutException, httpx.TransportError) as exc:
            raise FunctionToolError("Thumbnail fetch failed.") from exc


def _public_url(url: str) -> bool:
    """Allow only bounded HTTP(S) result references without userinfo."""
    if not url or len(url) > 2048 or any(ord(ch) < 32 for ch in url):
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and not (parsed.username or parsed.password)
        )
    except ValueError:
        return False


def _allowed_thumbnail(url: str) -> bool:
    """Keep all thumbnail I/O on Brave's fixed HTTPS proxy host."""
    if not _public_url(url):
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == _THUMBNAIL_HOST
            and parsed.port in {None, 443}
            and "@" not in parsed.netloc
        )
    except ValueError:
        return False


async def _bounded_body(response: httpx.Response, limit: int) -> bytes:
    """Abort a response before it exceeds the operation-specific size budget."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise FunctionToolError("Brave Search response exceeds the size limit.")
    return bytes(body)


def _safe_api_error(status: int) -> str:
    """Report provider failures without echoing headers or response bodies."""
    if status in {401, 403}:
        return "Brave Search key is invalid or this subscription lacks access."
    if status == 429:
        return "Brave Search rate or quota limit reached; retry later."
    if status in {400, 422}:
        return "Brave Search rejected the query or its region, language, or filters."
    return "Brave Search request failed."
