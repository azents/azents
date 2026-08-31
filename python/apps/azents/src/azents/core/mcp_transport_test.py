"""MCP v2 transport compatibility tests."""

import httpx2 as httpx

from azents.core.mcp_transport import (
    _extract_rate_limit_delay,
    _is_http_405,
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
