"""Docker-free tests for the fixture-fenced Exchange download helper."""

import traceback
from unittest.mock import Mock, call

import pytest
import requests

from support import exchange_download

_SERVER = "https://public.fixture"
_ENDPOINT = "https://172.18.0.1:39443"
_LOCATION = f"{_ENDPOINT}/exchange/original?X-Amz-Signature=test-capability"
_API_URL = f"{_SERVER}/chat/v1/exchange-files/attachment/download"
_HEADERS = {
    "Location": _LOCATION,
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


class _MemoryResponse(requests.Response):
    def close(self) -> None:
        """No transport exists to close for this in-memory HTTP response."""


def _response(status: int, body: bytes, headers: dict[str, str]) -> requests.Response:
    """Build an in-memory HTTP response without transport state."""
    response = _MemoryResponse()
    response.status_code = status
    response._content = body
    response.headers.update(headers)
    return response


@pytest.fixture
def get(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Replace all HTTP I/O with observed in-memory calls."""
    mocked = Mock(
        side_effect=[
            _response(302, b"", _HEADERS),
            _response(200, b"fixture-file", {}),
        ]
    )
    monkeypatch.setattr(exchange_download.requests, "get", mocked)
    return mocked


def _download(endpoint: str = _ENDPOINT) -> bytes:
    """Pass explicit fixture authority to the helper under test."""
    return exchange_download.download_fixture_exchange_file(
        server_url=_SERVER,
        access_token="test-api-token",
        attachment_id="attachment",
        storage_endpoint_url=endpoint,
    )


def test_valid_handoff_returns_only_bytes_without_forwarding_api_auth(
    get: Mock,
) -> None:
    """Verify both no-redirect requests and the exact-origin TLS exception."""
    result = _download()
    assert result == b"fixture-file"
    assert isinstance(result, bytes)
    assert get.call_args_list == [
        call(
            _API_URL,
            headers={"Authorization": "Bearer test-api-token"},
            timeout=10,
            allow_redirects=False,
            verify=True,
        ),
        call(_LOCATION, timeout=10, allow_redirects=False, verify=False),
    ]


def test_default_https_port_is_the_same_origin(get: Mock) -> None:
    """HTTPS default and explicit 443 represent one observed fixture origin."""
    location = "https://storage.fixture:443/exchange/original?test=capability"
    get.side_effect = [
        _response(302, b"", {**_HEADERS, "Location": location}),
        _response(200, b"fixture-file", {}),
    ]
    assert _download("https://storage.fixture/") == b"fixture-file"
    assert get.call_args == call(
        location, timeout=10, allow_redirects=False, verify=False
    )


@pytest.mark.parametrize("status", [200, 301, 307, 401, 403, 404, 410, 500])
def test_non_handoff_response_never_fetches_storage(get: Mock, status: int) -> None:
    """Authorization denials and unexpected status codes cannot reach storage."""
    get.side_effect = [_response(status, b"", _HEADERS)]
    with pytest.raises(AssertionError, match="authorized 302"):
        _download()
    assert get.call_count == 1


def test_nonempty_handoff_body_never_fetches_storage(get: Mock) -> None:
    """The API must hand off a capability instead of streaming file bytes."""
    get.side_effect = [_response(302, b"unexpected-body", _HEADERS)]
    with pytest.raises(AssertionError, match="body must be empty"):
        _download()
    assert get.call_count == 1


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("Cache-Control", None),
        ("Cache-Control", "public"),
        ("Referrer-Policy", None),
        ("Referrer-Policy", "unsafe-url"),
        ("Location", None),
        ("Location", ""),
    ],
)
def test_invalid_handoff_headers_never_fetch_storage(
    get: Mock, name: str, value: str | None
) -> None:
    """Require the explicit no-store/no-referrer policy and a Location."""
    headers = _HEADERS.copy()
    if value is None:
        del headers[name]
    else:
        headers[name] = value
    get.side_effect = [_response(302, b"", headers)]
    with pytest.raises(AssertionError):
        _download()
    assert get.call_count == 1


@pytest.mark.parametrize(
    "location",
    [
        "https://other.fixture:39443/original",
        "https://172.18.0.1:39444/original",
        "http://172.18.0.1:39443/original",
        "https://user@172.18.0.1:39443/original",
        "https://user:password@172.18.0.1:39443/original",
        "//172.18.0.1:39443/original",
        "/exchange/original",
        "https:///exchange/original",
        "https://172.18.0.1:invalid/original",
        "https://172.18.0.1:65536/original",
        "https://[invalid/original",
        f"{_ENDPOINT}/original#fragment",
        f" {_ENDPOINT}/original",
        f"{_ENDPOINT}/original\n",
        f"{_ENDPOINT}/original\x00",
        f"{_ENDPOINT}/original\x7f",
        f"{_ENDPOINT}\\@other.fixture/original",
    ],
)
def test_invalid_or_mismatched_location_never_fetches_storage(
    get: Mock, location: str
) -> None:
    """Fence the TLS exception before any storage GET occurs."""
    get.side_effect = [_response(302, b"", {**_HEADERS, "Location": location})]
    with pytest.raises(AssertionError):
        _download()
    assert get.call_count == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "http://172.18.0.1:39443",
        "https://user@172.18.0.1:39443",
        "https://user:password@172.18.0.1:39443",
        "https://172.18.0.1:invalid",
        "https://172.18.0.1:65536",
        "https://[invalid",
        "https:///missing-host",
        f"{_ENDPOINT}/path",
        f"{_ENDPOINT}?query=value",
        f"{_ENDPOINT}#fragment",
        f"{_ENDPOINT}\n",
        f"{_ENDPOINT}\\",
    ],
)
def test_invalid_fixture_endpoint_fails_before_http(get: Mock, endpoint: str) -> None:
    """Only the explicit observed HTTPS origin is an admissible fixture."""
    with pytest.raises(AssertionError):
        _download(endpoint)
    get.assert_not_called()


@pytest.mark.parametrize("status", [201, 204, 301, 302, 307, 403, 404, 500])
def test_bad_storage_status_fails_without_downstream_redirect(
    get: Mock, status: int
) -> None:
    """Storage redirects and failures are not successful body downloads."""
    get.side_effect = [
        _response(302, b"", _HEADERS),
        _response(status, b"unexpected-body", {"Location": "https://other.fixture"}),
    ]
    with pytest.raises(AssertionError, match="storage GET must return 200"):
        _download()
    assert get.call_count == 2
    assert get.call_args == call(
        _LOCATION, timeout=10, allow_redirects=False, verify=False
    )


@pytest.mark.parametrize(
    "error_type",
    [
        requests.exceptions.SSLError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
        requests.exceptions.ContentDecodingError,
        requests.exceptions.InvalidURL,
    ],
)
@pytest.mark.parametrize("stage", ["api", "storage"])
def test_request_errors_hide_url_query_and_exception_context(
    get: Mock, error_type: type[requests.exceptions.RequestException], stage: str
) -> None:
    """Transport failures remain visible without rendering signed capabilities."""
    error = error_type(f"private request failed: {_LOCATION}")
    get.side_effect = (
        [error] if stage == "api" else [_response(302, b"", _HEADERS), error]
    )
    with pytest.raises(
        AssertionError, match="request failed|storage GET failed"
    ) as caught:
        _download()
    rendered = "".join(traceback.format_exception(caught.value))
    assert _LOCATION not in rendered
    assert "X-Amz-Signature" not in rendered
    assert "test-capability" not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert get.call_count == (1 if stage == "api" else 2)


class _UnreadableResponse(_MemoryResponse):
    @property
    def content(self) -> bytes:
        raise requests.exceptions.ChunkedEncodingError(
            f"private body error: {_LOCATION}"
        )


@pytest.mark.parametrize("stage", ["api", "storage"])
def test_response_body_errors_are_sanitized(get: Mock, stage: str) -> None:
    """Body-read exceptions receive the same bounded error as request failures."""
    response = _UnreadableResponse()
    response.status_code = 302 if stage == "api" else 200
    response.headers.update(_HEADERS)
    get.side_effect = (
        [response] if stage == "api" else [_response(302, b"", _HEADERS), response]
    )
    with pytest.raises(AssertionError) as caught:
        _download()
    assert _LOCATION not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__suppress_context__


def test_unrelated_errors_propagate(get: Mock) -> None:
    """Do not relabel non-HTTP implementation defects as transport failures."""
    get.side_effect = [ValueError("unrelated implementation defect")]
    with pytest.raises(ValueError, match="unrelated implementation defect"):
        _download()
