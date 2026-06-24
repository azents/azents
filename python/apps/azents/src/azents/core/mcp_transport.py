"""MCP transport layer utilities.

Abstracts SSE and Streamable HTTP transport protocols. Tries Streamable HTTP
first and falls back to SSE on failure. On 429 Rate Limit, respects Retry-After
header and retries with exponential backoff.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import cast

import httpx
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult
from mcp.types import Tool as McpBaseTool

from azents.core.tools import TestConnectionResult

logger = logging.getLogger(__name__)

# 429 Rate Limit retry settings
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 1.0  # seconds


def _is_http_405(exc: Exception) -> bool:
    """Check whether exception is HTTP 405 Method Not Allowed.

    Also checks recursively when wrapped by ExceptionGroup.
    """
    if isinstance(exc, ExceptionGroup):
        subs = cast(
            tuple[Exception, ...],
            exc.exceptions,
        )
        return any(_is_http_405(sub) for sub in subs)
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 405
    return False


def _extract_rate_limit_delay(exc: Exception) -> float | None:
    """Find HTTP 429 in ExceptionGroup and return wait time in seconds.

    Return Retry-After value when present, otherwise default 0.
    Return None for non-429 errors.

    :param exc: Raised exception
    :return: Wait time in seconds. None when not 429.
    """
    if isinstance(exc, ExceptionGroup):
        subs = cast(
            tuple[Exception, ...],
            exc.exceptions,
        )
        for sub in subs:
            delay = _extract_rate_limit_delay(sub)
            if delay is not None:
                return delay
        return None
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        retry_after = exc.response.headers.get("retry-after")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return 0.0  # 429 without Retry-After; caller applies backoff
    return None


@asynccontextmanager
async def _mcp_session(
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    use_streamable_http: bool = False,
    proxy_url: str | None = None,
    auth: httpx.Auth | None = None,
) -> AsyncGenerator[ClientSession]:
    """Create MCP session.

    :param server_url: MCP server URL
    :param headers: Authentication headers
    :param timeout: Timeout in seconds
    :param use_streamable_http: True for Streamable HTTP, False for SSE
    :param proxy_url: Egress proxy URL; direct connection when None
    :param auth: httpx Auth handler for per-request signing such as SigV4
    """
    timeout_td = timedelta(seconds=timeout)

    if use_streamable_http:
        client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout, read=300.0),
            proxy=proxy_url,
            auth=auth,
        )
        try:
            async with streamable_http_client(server_url, http_client=client) as (
                r,
                w,
                _,
            ):
                async with ClientSession(
                    r, w, read_timeout_seconds=timeout_td
                ) as session:
                    await session.initialize()
                    yield session
        finally:
            await client.aclose()
    elif proxy_url or auth:
        outer_auth = auth

        def _make_httpx_client(
            headers: dict[str, str] | None = None,
            timeout: httpx.Timeout | None = None,
            auth: httpx.Auth | None = None,
        ) -> httpx.AsyncClient:
            return httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=auth or outer_auth,
                follow_redirects=True,
                proxy=proxy_url,
            )

        async with sse_client(
            server_url,
            headers=headers,
            timeout=timeout,
            httpx_client_factory=_make_httpx_client,
        ) as (r, w):
            async with ClientSession(r, w, read_timeout_seconds=timeout_td) as session:
                await session.initialize()
                yield session
    else:
        async with sse_client(server_url, headers=headers, timeout=timeout) as (r, w):
            async with ClientSession(r, w, read_timeout_seconds=timeout_td) as session:
                await session.initialize()
                yield session


async def list_tools(
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    proxy_url: str | None = None,
    auth: httpx.Auth | None = None,
) -> tuple[list[McpBaseTool], bool]:
    """Fetch tool list from MCP server.

    Try Streamable HTTP first and fall back to SSE on HTTP 405.

    :param server_url: MCP server URL
    :param headers: Authentication headers
    :param timeout: Timeout in seconds
    :param proxy_url: Egress proxy URL; direct connection when None
    :param auth: httpx Auth handler
    :return: (tool list, whether streamable_http was used)
    """
    try:
        async with _mcp_session(
            server_url,
            headers,
            timeout,
            use_streamable_http=True,
            proxy_url=proxy_url,
            auth=auth,
        ) as session:
            result = await session.list_tools()
            return list(result.tools), True
    except Exception as exc:
        if not _is_http_405(exc):
            raise
        logger.info(
            "Streamable HTTP failed, falling back to SSE",
            extra={"server_url": server_url, "error_type": type(exc).__name__},
        )

    async with _mcp_session(
        server_url, headers, timeout, proxy_url=proxy_url, auth=auth
    ) as session:
        result = await session.list_tools()
        return list(result.tools), False


async def call_tool(
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    tool_name: str,
    arguments: dict[str, object],
    *,
    use_streamable_http: bool = False,
    proxy_url: str | None = None,
    auth: httpx.Auth | None = None,
) -> CallToolResult:
    """Call MCP tool.

    On 429 Rate Limit, respect Retry-After header and retry up to 3 times.
    When Retry-After is absent, apply exponential backoff of 1s, 2s, 4s.

    :param server_url: MCP server URL
    :param headers: Authentication headers
    :param timeout: Timeout in seconds
    :param tool_name: Tool name to call
    :param arguments: Tool arguments
    :param use_streamable_http: True for Streamable HTTP, False for SSE
    :param proxy_url: Egress proxy URL; direct connection when None
    :param auth: httpx Auth handler
    """
    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            async with _mcp_session(
                server_url,
                headers,
                timeout,
                use_streamable_http=use_streamable_http,
                proxy_url=proxy_url,
                auth=auth,
            ) as session:
                return await session.call_tool(tool_name, arguments=arguments)
        except Exception as exc:
            delay = _extract_rate_limit_delay(exc)
            if delay is None or attempt >= _RATE_LIMIT_MAX_RETRIES:
                raise
            # When Retry-After is absent (0.0), use exponential backoff
            if delay == 0.0:
                delay = _RATE_LIMIT_BASE_DELAY * (2**attempt)
            logger.warning(
                "MCP tool rate limited, retrying",
                extra={
                    "tool_name": tool_name,
                    "server_url": server_url,
                    "attempt": attempt + 1,
                    "retry_after_secs": delay,
                },
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Connection test utilities
# ---------------------------------------------------------------------------


def extract_network_error(exc: Exception) -> str | None:
    """Extract user-facing message from network errors.

    Return a message for network-related errors such as DNS, timeout, connection
    refusal, or HTTP status, and return None for other errors.

    :param exc: Raised exception
    :return: Network error message or None
    """
    # Extract actual error from ExceptionGroup when wrapped by asyncio TaskGroup
    if isinstance(exc, ExceptionGroup):
        subs = cast(
            tuple[Exception, ...],
            exc.exceptions,
        )
        if subs:
            return extract_network_error(subs[0])
        return None

    # httpx errors
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        try:
            body = exc.response.text[:200]
        except httpx.ResponseNotRead:
            body = ""
        return f"HTTP {code}: {body}" if body else f"HTTP {code}"
    if isinstance(exc, httpx.TimeoutException):
        return "Connection timed out."
    if isinstance(exc, httpx.InvalidURL):
        return f"Invalid server URL: {exc}"
    if isinstance(exc, httpx.TransportError):
        return f"Network error: {exc}"

    # Python built-in network errors
    if isinstance(exc, TimeoutError):
        return "Connection timed out."
    if isinstance(exc, ConnectionError):
        return f"Connection error: {exc}"
    if isinstance(exc, OSError):
        return f"Network error: {exc}"

    return None


async def test_mcp_transport(
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    proxy_url: str | None = None,
    auth: httpx.Auth | None = None,
) -> TestConnectionResult:
    """Connect to MCP server and call list_tools.

    Convert network errors to failure result and re-raise other errors.

    :param server_url: MCP server URL
    :param headers: Authentication headers
    :param timeout: Timeout in seconds
    :param proxy_url: Egress proxy URL; direct connection when None
    :param auth: httpx Auth handler
    :return: Connection test result
    """
    try:
        tools, _ = await list_tools(
            server_url, headers, timeout, proxy_url=proxy_url, auth=auth
        )
    except Exception as exc:
        message = extract_network_error(exc)
        if message is not None:
            return TestConnectionResult(
                success=False,
                message=message,
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )
        raise

    tool_names = [t.name for t in tools]
    tool_list = ", ".join(tool_names)
    return TestConnectionResult(
        success=True,
        message=f"Connected successfully. Found {len(tool_names)} tools: {tool_list}",
        discovered_auth_url=None,
        discovered_token_url=None,
        supports_dcr=None,
    )
