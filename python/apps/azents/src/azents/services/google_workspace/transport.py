"""Public Google SDK execution with bounded transport and no implicit renewal/retry."""

import asyncio
import dataclasses
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cached_property
from typing import TYPE_CHECKING, NamedTuple, Protocol, runtime_checkable
from urllib.parse import urlsplit

import anyio
import httplib2
import httpx
from google.auth.exceptions import GoogleAuthError
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

if TYPE_CHECKING:
    from googleapiclient._apis.calendar.v3.resources import CalendarResource
    from googleapiclient._apis.drive.v3.resources import DriveResource
    from googleapiclient._apis.gmail.v1.resources import GmailResource


class GoogleSdkError(ValueError):
    """Redacted failure; an admitted remote effect is never automatically replayed."""

    def __init__(self, code: str, *, dispatched: bool, status: int | None) -> None:
        self.code = code
        self.dispatched = dispatched
        self.status = status
        super().__init__(
            "Google operation could not be confirmed. No automatic replay was made."
            if dispatched
            else "Google operation was not dispatched."
        )


class GoogleEmptyResponse(BaseModel):
    """Typed empty successful response; an error-shaped HTTP 200 is invalid."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def decode_sdk_void_response(cls, value: object) -> object:
        # Methods without a discovery response schema use the SDK's RawModel,
        # including the empty string returned for a successful HTTP 204.
        if isinstance(value, str | bytes):
            if not value:
                return {}
            try:
                decoded: object = json.loads(value)
            except json.JSONDecodeError, UnicodeDecodeError:
                raise ValueError("Expected an empty Google SDK response.") from None
            return decoded
        return value


@runtime_checkable
class GoogleUploadReader(Protocol):
    """Public SDK media stream contract, including its bounded upload slices."""

    def read(self, size: int = -1) -> bytes: ...


class GoogleHttpResponse(NamedTuple):
    response: httplib2.Response
    content: bytes


@dataclasses.dataclass(frozen=True)
class GoogleSdkLimits:
    """Call-local budgets; no durable provider configuration or mode is created."""

    maximum_response_bytes: int
    maximum_total_received_bytes: int
    maximum_upload_bytes: int
    timeout: float

    def __post_init__(self) -> None:
        if (
            min(
                self.maximum_response_bytes,
                self.maximum_total_received_bytes,
                self.maximum_upload_bytes,
            )
            < 1
            or not 0 < self.timeout <= 300
        ):
            raise ValueError("Google SDK budgets must be positive and bounded.")


@dataclasses.dataclass
class _JobState:
    deadline: float
    cancelled: threading.Event
    before_request: Callable[[], None]
    dispatched: bool = False
    received: int = 0

    def require_current(self) -> None:
        if self.cancelled.is_set() or time.monotonic() >= self.deadline:
            raise GoogleSdkError(
                "cancelled_or_timeout", dispatched=self.dispatched, status=None
            )


_ALLOWED_API_PATHS = {
    "gmail.googleapis.com": ("/gmail/v1/", "/upload/gmail/v1/"),
    "www.googleapis.com": (
        "/gmail/v1/",
        "/upload/gmail/v1/",
        "/calendar/v3/",
        "/drive/v3/",
        "/upload/drive/v3/",
    ),
}


def _require_api_url(uri: str, state: _JobState) -> None:
    try:
        parsed = urlsplit(uri)
        valid = (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
            and not parsed.fragment
            and any(
                parsed.path.startswith(path)
                for path in _ALLOWED_API_PATHS.get(parsed.hostname or "", ())
            )
        )
    except ValueError:
        valid = False
    if not valid:
        raise GoogleSdkError(
            "invalid_provider_endpoint", dispatched=state.dispatched, status=None
        )


class _BoundedHttp(httplib2.Http):
    """Compatible public transport injection; SDK owns every method/body/route."""

    def __init__(
        self, client: httpx.Client, limits: GoogleSdkLimits, state: _JobState
    ) -> None:
        super().__init__(timeout=limits.timeout)
        self.client = client
        self.limits = limits
        self.state = state

    def _upload(self, source: GoogleUploadReader) -> Iterator[bytes]:
        total = 0
        while True:
            self.state.require_current()
            chunk = source.read(65536)
            if not chunk:
                return
            total += len(chunk)
            if total > self.limits.maximum_upload_bytes:
                raise GoogleSdkError(
                    "upload_limit", dispatched=self.state.dispatched, status=None
                )
            yield chunk

    def request(
        self,
        uri: str,
        method: str = "GET",
        body: str | bytes | GoogleUploadReader | None = None,
        headers: dict[str, str] | None = None,
        redirections: int = 5,
        connection_type: type[httplib2.HTTPConnectionWithTimeout] | None = None,
    ) -> GoogleHttpResponse:
        self.state.require_current()
        _require_api_url(uri, self.state)
        if connection_type is not None:
            raise GoogleSdkError(
                "invalid_transport", dispatched=self.state.dispatched, status=None
            )
        request_headers = dict(headers or {})
        # Refuse unexpected content coding instead of decoding unbounded compressed
        # chunks. Original binary payloads remain supported without content scanning.
        request_headers["accept-encoding"] = "identity"
        content: str | bytes | Iterator[bytes] | None
        if isinstance(body, GoogleUploadReader):
            content = self._upload(body)
        else:
            content = body
            size = (
                len(body.encode("utf-8")) if isinstance(body, str) else len(body or b"")
            )
            if size > self.limits.maximum_upload_bytes:
                raise GoogleSdkError(
                    "upload_limit", dispatched=self.state.dispatched, status=None
                )
        self.state.require_current()
        self.state.before_request()
        self.state.require_current()
        self.state.dispatched = True
        remaining_time = max(self.state.deadline - time.monotonic(), 0.001)
        with self.client.stream(
            method,
            uri,
            content=content,
            headers=request_headers,
            timeout=min(self.limits.timeout, remaining_time),
            follow_redirects=False,
        ) as response:
            if response.headers.get("content-encoding", "identity").lower() not in {
                "",
                "identity",
            }:
                raise GoogleSdkError(
                    "unsupported_content_encoding",
                    dispatched=True,
                    status=response.status_code,
                )
            expected: int | None = None
            raw_length = response.headers.get("content-length")
            if raw_length is not None:
                try:
                    expected = int(raw_length)
                except ValueError:
                    raise GoogleSdkError(
                        "invalid_response_length",
                        dispatched=True,
                        status=response.status_code,
                    ) from None
                if expected < 0 or expected > self.limits.maximum_response_bytes:
                    raise GoogleSdkError(
                        "receive_limit", dispatched=True, status=response.status_code
                    )
            chunks = bytearray()
            for chunk in response.iter_raw(chunk_size=65536):
                self.state.require_current()
                self.state.received += len(chunk)
                if (
                    len(chunks) + len(chunk) > self.limits.maximum_response_bytes
                    or self.state.received > self.limits.maximum_total_received_bytes
                ):
                    raise GoogleSdkError(
                        "receive_limit", dispatched=True, status=response.status_code
                    )
                chunks.extend(chunk)
            if expected is not None and len(chunks) != expected:
                raise GoogleSdkError(
                    "invalid_response_length",
                    dispatched=True,
                    status=response.status_code,
                )
            result_headers = dict(response.headers)
            result_headers["status"] = str(response.status_code)
            result_headers["reason"] = response.reason_phrase
            return GoogleHttpResponse(httplib2.Response(result_headers), bytes(chunks))


class _AccessOnlyHttp(httplib2.Http):
    """Typed Http facade over the supported access-only authorization bridge."""

    def __init__(self, token: str, transport: _BoundedHttp) -> None:
        super().__init__(timeout=transport.limits.timeout)
        self.authorized = AuthorizedHttp(
            Credentials(token=token),
            http=transport,
            max_refresh_attempts=0,
        )

    def request(
        self,
        uri: str,
        method: str = "GET",
        body: str | bytes | GoogleUploadReader | None = None,
        headers: dict[str, str] | None = None,
        redirections: int = 5,
        connection_type: type[httplib2.HTTPConnectionWithTimeout] | None = None,
    ) -> GoogleHttpResponse:
        response, content = self.authorized.request(
            uri,
            method=method,
            body=body,
            headers=headers,
            redirections=redirections,
            connection_type=connection_type,
        )
        return GoogleHttpResponse(response, content)


@contextmanager
def _sdk_errors(state: _JobState) -> Iterator[None]:
    try:
        yield
    except GoogleSdkError as error:
        # A later file/authority check may fail before its own request while an
        # earlier compound step was already dispatched. Retain that uncertainty
        # without discarding typed partial-operation receipts.
        error.dispatched = error.dispatched or state.dispatched
        raise
    except HttpError as error:
        status = int(error.resp.status)
        code = (
            "authentication_rejected"
            if status == 401
            else "resource_rejected"
            if status in {400, 403, 404, 409, 412}
            else "provider_unavailable"
        )
        raise GoogleSdkError(code, dispatched=state.dispatched, status=status) from None
    except httpx.HTTPError, httplib2.HttpLib2Error:
        raise GoogleSdkError(
            "transport_uncertain", dispatched=state.dispatched, status=None
        ) from None
    except GoogleAuthError:
        raise GoogleSdkError(
            "authentication_unavailable", dispatched=state.dispatched, status=None
        ) from None
    except json.JSONDecodeError, UnicodeDecodeError, ValidationError:
        raise GoogleSdkError(
            "invalid_provider_response", dispatched=state.dispatched, status=None
        ) from None


@dataclasses.dataclass
class GoogleSdkSession:
    """One worker job and transport lifetime; never share a Resource across threads."""

    http: _AccessOnlyHttp
    state: _JobState

    @cached_property
    def gmail(self) -> "GmailResource":
        return build(
            "gmail",
            "v1",
            http=self.http,
            static_discovery=True,
            cache_discovery=False,
            num_retries=0,
        )

    @cached_property
    def calendar(self) -> "CalendarResource":
        return build(
            "calendar",
            "v3",
            http=self.http,
            static_discovery=True,
            cache_discovery=False,
            num_retries=0,
        )

    @cached_property
    def drive(self) -> "DriveResource":
        return build(
            "drive",
            "v3",
            http=self.http,
            static_discovery=True,
            cache_discovery=False,
            num_retries=0,
        )

    def execute(self, request: HttpRequest) -> object:
        self.state.require_current()
        with _sdk_errors(self.state):
            return request.execute(num_retries=0)

    def decode[T: BaseModel](self, model: type[T], request: HttpRequest) -> T:
        with _sdk_errors(self.state):
            payload = self.execute(request)
            # Reject a malformed success-status failure envelope before optional
            # provider fields can normalize it into an empty successful result.
            if isinstance(payload, dict) and "error" in payload:
                raise GoogleSdkError(
                    "invalid_provider_response",
                    dispatched=self.state.dispatched,
                    status=None,
                )
            return model.model_validate(payload)

    def require_current(self) -> None:
        self.state.require_current()


def create_google_http_client(proxy_url: str | None, timeout: float) -> httpx.Client:
    return httpx.Client(proxy=proxy_url, timeout=timeout, follow_redirects=False)


class _SdkDetailFilter(logging.Filter):
    """Suppress sensitive third-party details only in the current SDK context."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not _SDK_DIAGNOSTICS_SUPPRESSED.get()


_SDK_DIAGNOSTICS_SUPPRESSED = ContextVar(
    "google_sdk_diagnostics_suppressed", default=False
)
_SDK_DETAIL_FILTER = _SdkDetailFilter()
for _logger_name in (
    "googleapiclient.discovery",
    "googleapiclient.http",
    "googleapiclient.model",
    "google_auth_httplib2",
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
    # Python logger filters do not filter descendant records. Cover the pinned
    # parser's warning/error modules explicitly; successful parsing can log
    # document-controlled font, stream and object values at WARNING level.
    "pypdf._reader",
    "pypdf._page",
    "pypdf._codecs._codecs",
    "pypdf._crypt_providers._cryptography",
    "pypdf._crypt_providers._pycryptodome",
    "pypdf._doc_common",
    "pypdf._encryption",
    "pypdf._page_labels",
    "pypdf._text_extraction",
    "pypdf._text_extraction._layout_mode._fixed_width_page",
    "pypdf._cmap",
    "pypdf._utils",
    "pypdf._writer",
    "pypdf.actions._actions",
    "pypdf.annotations._non_markup_annotations",
    "pypdf.generic._appearance_stream",
    "pypdf.generic._base",
    "pypdf.generic._data_structures",
    "pypdf.generic._files",
    "pypdf.generic._font",
    "pypdf.generic._image_inline",
    "pypdf.generic._image_xobject",
    "pypdf.generic._link",
    "pypdf.generic._utils",
    "pypdf.filters",
):
    logging.getLogger(_logger_name).addFilter(_SDK_DETAIL_FILTER)


@contextmanager
def _without_sensitive_sdk_diagnostics() -> Iterator[None]:
    # SDK debug output includes bodies; HTTPX info includes capability URLs.
    # Context-local diagnostics avoid mutating logger levels/filter lists while
    # other SDK requests run, and never suppress an unrelated request's logging.
    token = _SDK_DIAGNOSTICS_SUPPRESSED.set(True)
    try:
        yield
    finally:
        _SDK_DIAGNOSTICS_SUPPRESSED.reset(token)


class GoogleWorkspaceSdk:
    """Injected bounded offload; no DB transaction or hidden provider retries."""

    def __init__(
        self,
        *,
        capacity: int,
        client_factory: Callable[[str | None, float], httpx.Client],
    ) -> None:
        if capacity < 1:
            raise ValueError("Google SDK concurrency must be positive.")
        self.limiter = anyio.CapacityLimiter(capacity)
        self.thread_limiter = anyio.CapacityLimiter(capacity)
        self.client_factory = client_factory

    async def run[T](
        self,
        *,
        access_token: str,
        limits: GoogleSdkLimits,
        proxy_url: str | None,
        before_request: Callable[[], None],
        operation: Callable[[GoogleSdkSession], T],
    ) -> T:
        state = _JobState(
            time.monotonic() + limits.timeout, threading.Event(), before_request
        )
        loop = asyncio.get_running_loop()
        borrower = object()
        ownership_lock = threading.Lock()
        acquired = False
        started = False
        released = False

        def release_permit() -> None:
            nonlocal released
            with ownership_lock:
                if released:
                    return
                released = True
            if not loop.is_closed():
                loop.call_soon_threadsafe(self.limiter.release_on_behalf_of, borrower)

        def invoke() -> T:
            nonlocal started
            with ownership_lock:
                started = True
            try:
                state.require_current()
                with (
                    _without_sensitive_sdk_diagnostics(),
                    self.client_factory(proxy_url, limits.timeout) as client,
                ):
                    transport = _BoundedHttp(client, limits, state)
                    session = GoogleSdkSession(
                        _AccessOnlyHttp(access_token, transport), state
                    )
                    with _sdk_errors(state):
                        result = operation(session)
                        state.require_current()
                        return result
            finally:
                # The actual job retains its permit even when a native asyncio
                # cancellation has already released the awaiting thread token.
                release_permit()

        try:
            async with asyncio.timeout(limits.timeout):
                await self.limiter.acquire_on_behalf_of(borrower)
                acquired = True
                return await anyio.to_thread.run_sync(
                    invoke, limiter=self.thread_limiter, abandon_on_cancel=False
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise GoogleSdkError(
                "timeout_uncertain", dispatched=state.dispatched, status=None
            ) from None
        finally:
            state.cancelled.set()
            with ownership_lock:
                release_unstarted = acquired and not started
            if release_unstarted:
                release_permit()
