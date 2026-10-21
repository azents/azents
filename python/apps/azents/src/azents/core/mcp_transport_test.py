"""MCP v2 transport compatibility tests."""

import asyncio
from unittest.mock import AsyncMock

import httpx2 as httpx
import pytest
from mcp import MCPError

from azents.core import mcp_transport
from azents.core.mcp_transport import (
    McpToolListResult,
    _extract_rate_limit_delay,
    _is_http_405,
    discovery_rate_limit_delay,
    extract_network_error,
)


def _status_error(
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
    content: bytes = b"",
) -> httpx.HTTPStatusError:
    """Create an httpx2 status error fixture."""
    request = httpx.Request("POST", "https://example.com/mcp")
    response = httpx.Response(
        status_code,
        headers=headers,
        content=content,
        request=request,
    )
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


def test_http_405_is_found_in_exception_group() -> None:
    """Streamable HTTP fallback recognizes nested httpx2 status errors."""
    error = ExceptionGroup("transport", [RuntimeError("other"), _status_error(405)])

    assert _is_http_405(error) is True


def test_rate_limit_uses_retry_after_from_httpx2_response() -> None:
    """Rate limit retry delay comes from the v2 transport response."""
    error = ExceptionGroup(
        "transport",
        [_status_error(429, headers={"retry-after": "2.5"})],
    )

    assert _extract_rate_limit_delay(error) == 2.5


def test_network_error_includes_httpx2_response_body() -> None:
    """Connection tests preserve concise HTTP response details."""
    error = _status_error(503, content=b"temporarily unavailable")

    assert extract_network_error(error) == "HTTP 503: temporarily unavailable"


def _mcp_throttle() -> ExceptionGroup:
    return ExceptionGroup(
        "transport",
        [ExceptionGroup("session", [MCPError(-32000, "Too many requests")])],
    )


@pytest.mark.parametrize(
    "failure", [_mcp_throttle(), _status_error(429, headers={"retry-after": "2.5"})]
)
async def test_discovery_recovers_from_throttling(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    result = McpToolListResult(tools=[], use_streamable_http=True)
    discover = AsyncMock(side_effect=[failure, result])
    sleep = AsyncMock()
    monkeypatch.setattr(mcp_transport, "_list_tools_once", discover)
    monkeypatch.setattr(mcp_transport.asyncio, "sleep", sleep)
    auth = httpx.BasicAuth("user", "password")
    assert (
        await mcp_transport.list_tools(
            "https://example.com/mcp",
            {"X-Test": "header"},
            30,
            proxy_url="https://proxy.test",
            auth=auth,
        )
        is result
    )
    assert discover.await_count == 2
    assert discover.await_args_list[0] == discover.await_args_list[1]
    assert discover.await_args_list[1].kwargs == {
        "proxy_url": "https://proxy.test",
        "auth": auth,
    }
    sleep.assert_awaited_once_with(
        2.5 if isinstance(failure, httpx.HTTPStatusError) else 1.0
    )


async def test_discovery_throttling_exhaustion_preserves_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = _mcp_throttle()
    discover = AsyncMock(side_effect=failure)
    sleep = AsyncMock()
    monkeypatch.setattr(mcp_transport, "_list_tools_once", discover)
    monkeypatch.setattr(mcp_transport.asyncio, "sleep", sleep)
    with pytest.raises(ExceptionGroup) as caught:
        await mcp_transport.list_tools("https://example.com/mcp", {}, 30)
    assert caught.value is failure
    assert discover.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    "failure",
    [
        MCPError(-32602, "Invalid params"),
        _status_error(401),
        ExceptionGroup("mixed", [_mcp_throttle(), ValueError("bug")]),
        ExceptionGroup("mixed", [_mcp_throttle(), _status_error(500)]),
        asyncio.CancelledError(),
    ],
)
async def test_discovery_does_not_retry_unrelated_errors_or_cancellation(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    discover = AsyncMock(side_effect=failure)
    sleep = AsyncMock()
    monkeypatch.setattr(mcp_transport, "_list_tools_once", discover)
    monkeypatch.setattr(mcp_transport.asyncio, "sleep", sleep)
    with pytest.raises(type(failure)) as caught:
        await mcp_transport.list_tools("https://example.com/mcp", {}, 30)
    assert caught.value is failure
    discover.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.parametrize("retry_after", ["-1", "nan", "inf", "3600"])
async def test_discovery_refuses_unbounded_or_invalid_retry_delay(
    monkeypatch: pytest.MonkeyPatch, retry_after: str
) -> None:
    failure = _status_error(429, headers={"retry-after": retry_after})
    discover = AsyncMock(side_effect=failure)
    sleep = AsyncMock()
    monkeypatch.setattr(mcp_transport, "_list_tools_once", discover)
    monkeypatch.setattr(mcp_transport.asyncio, "sleep", sleep)
    with pytest.raises(httpx.HTTPStatusError):
        await mcp_transport.list_tools("https://example.com/mcp", {}, 30)
    discover.assert_awaited_once()
    sleep.assert_not_awaited()


def test_discovery_classification_does_not_change_tool_execution_retries() -> None:
    failure = _mcp_throttle()
    assert discovery_rate_limit_delay(failure) == 0
    assert _extract_rate_limit_delay(failure) is None
