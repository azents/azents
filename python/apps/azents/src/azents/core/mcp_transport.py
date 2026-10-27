"""MCP transport layer utilities.

Provides short-lived discovery/probes and the SDK context used by binding-owned
connections. Discovery negotiates HTTP/SSE and retries read-only throttling.
"""

import asyncio
import logging
import math
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import NamedTuple

import httpx2 as httpx
from mcp import MCPError
from mcp.client.session import ClientSession, MessageHandlerFnT
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Tool as McpBaseTool

from azents.core.tools import TestConnectionResult

logger = logging.getLogger(__name__)

# 429 Rate Limit retry settings
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 1.0  # seconds
_DISCOVERY_MAX_RETRY_DELAY = 60.0


class McpToolListResult(NamedTuple):
    """Discovered tools and the selected MCP transport."""

    tools: list[McpBaseTool]
    use_streamable_http: bool


def _is_http_405(exc: Exception) -> bool:
    """Check whether exception is HTTP 405 Method Not Allowed.

    Also checks recursively when wrapped by ExceptionGroup.
    """
    if isinstance(exc, ExceptionGroup):
        subs = exc.exceptions
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
        subs = exc.exceptions
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


def discovery_rate_limit_delay(exc: Exception) -> float | None:
    """Classify discovery throttling without hiding unrelated grouped failures."""
    if isinstance(exc, ExceptionGroup):
        delays = [discovery_rate_limit_delay(sub) for sub in exc.exceptions]
        if any(delay is None for delay in delays):
            return None
        return max(delay for delay in delays if delay is not None)
    if isinstance(exc, MCPError) and exc.message.casefold() == "too many requests":
        return 0.0
    return _extract_rate_limit_delay(exc)


@asynccontextmanager
async def _mcp_session(
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    use_streamable_http: bool = False,
    proxy_url: str | None = None,
    auth: httpx.Auth | None = None,
    message_handler: MessageHandlerFnT | None,
    http_client_type: type[httpx.AsyncClient],
) -> AsyncGenerator[ClientSession]:
    """Create MCP session.

    :param server_url: MCP server URL
    :param headers: Authentication headers
    :param timeout: Timeout in seconds
    :param use_streamable_http: True for Streamable HTTP, False for SSE
    :param proxy_url: Egress proxy URL; direct connection when None
    :param auth: httpx2 Auth handler for per-request signing such as SigV4
    """
    if use_streamable_http:
        async with http_client_type(
            headers=headers,
            timeout=httpx.Timeout(timeout, read=300.0),
            proxy=proxy_url,
            auth=auth,
        ) as client:
            async with streamable_http_client(
                server_url,
                http_client=client,
            ) as (r, w):
                async with ClientSession(
                    r, w, read_timeout_seconds=timeout, message_handler=message_handler
                ) as session:
                    await session.initialize()
                    yield session
    elif proxy_url is not None or http_client_type is not httpx.AsyncClient:

        def _make_httpx_client(
            headers: dict[str, str] | None = None,
            timeout: httpx.Timeout | None = None,
            auth: httpx.Auth | None = None,
        ) -> httpx.AsyncClient:
            return http_client_type(
                headers=headers,
                timeout=timeout,
                auth=auth,
                follow_redirects=True,
                proxy=proxy_url,
            )

        async with sse_client(
            server_url,
            headers=headers,
            timeout=timeout,
            httpx_client_factory=_make_httpx_client,
            auth=auth,
        ) as (r, w):
            async with ClientSession(
                r, w, read_timeout_seconds=timeout, message_handler=message_handler
            ) as session:
                await session.initialize()
                yield session
    else:
        async with sse_client(
            server_url,
            headers=headers,
            timeout=timeout,
            auth=auth,
        ) as (r, w):
            async with ClientSession(
                r, w, read_timeout_seconds=timeout, message_handler=message_handler
            ) as session:
                await session.initialize()
                yield session


async def list_tools(
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    proxy_url: str | None = None,
    auth: httpx.Auth | None = None,
) -> McpToolListResult:
    """Fetch tool list from MCP server.

    Retry throttled discovery at most three times. Try Streamable HTTP first
    and fall back to SSE on HTTP 405. Tool execution is never replayed here.

    :param server_url: MCP server URL
    :param headers: Authentication headers
    :param timeout: Timeout in seconds
    :param proxy_url: Egress proxy URL; direct connection when None
    :param auth: httpx Auth handler
    :return: (tool list, whether streamable_http was used)
    """
    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            return await _list_tools_once(
                server_url, headers, timeout, proxy_url=proxy_url, auth=auth
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = discovery_rate_limit_delay(exc)
            if delay is None or attempt >= _RATE_LIMIT_MAX_RETRIES:
                raise
            if delay == 0.0:
                delay = _RATE_LIMIT_BASE_DELAY * (2**attempt)
            # Do not retry earlier than Retry-After or wait without a bound.
            if not math.isfinite(delay) or not 0 <= delay <= _DISCOVERY_MAX_RETRY_DELAY:
                raise
            logger.warning(
                "MCP discovery rate limited, retrying",
                extra={"attempt": attempt + 1, "retry_after_secs": delay},
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


async def _list_tools_once(
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    proxy_url: str | None,
    auth: httpx.Auth | None,
) -> McpToolListResult:
    """Discover tools once with the existing transport negotiation."""
    try:
        async with _mcp_session(
            server_url,
            headers,
            timeout,
            use_streamable_http=True,
            proxy_url=proxy_url,
            auth=auth,
            message_handler=None,
            http_client_type=httpx.AsyncClient,
        ) as session:
            result = await session.list_tools()
            return McpToolListResult(tools=list(result.tools), use_streamable_http=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if not _is_http_405(exc):
            raise
        logger.info(
            "Streamable HTTP failed, falling back to SSE",
            extra={"server_url": server_url, "error_type": type(exc).__name__},
        )

    async with _mcp_session(
        server_url,
        headers,
        timeout,
        proxy_url=proxy_url,
        auth=auth,
        message_handler=None,
        http_client_type=httpx.AsyncClient,
    ) as session:
        result = await session.list_tools()
        return McpToolListResult(tools=list(result.tools), use_streamable_http=False)


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
        subs = exc.exceptions
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

    Convert network and MCP protocol errors to failure results; re-raise others.

    :param server_url: MCP server URL
    :param headers: Authentication headers
    :param timeout: Timeout in seconds
    :param proxy_url: Egress proxy URL; direct connection when None
    :param auth: httpx Auth handler
    :return: Connection test result
    """
    try:
        result = await list_tools(
            server_url, headers, timeout, proxy_url=proxy_url, auth=auth
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if isinstance(exc, MCPError):
            message = "MCP connection test failed."
        elif isinstance(exc, ExceptionGroup):
            protocol_errors, other_errors = exc.split(MCPError)
            if protocol_errors is not None:
                if other_errors is not None:
                    raise
                message = "MCP connection test failed."
            else:
                message = extract_network_error(exc)
        else:
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

    tool_names = [t.name for t in result.tools]
    tool_list = ", ".join(tool_names)
    return TestConnectionResult(
        success=True,
        message=f"Connected successfully. Found {len(tool_names)} tools: {tool_list}",
        discovered_auth_url=None,
        discovered_token_url=None,
        supports_dcr=None,
    )
