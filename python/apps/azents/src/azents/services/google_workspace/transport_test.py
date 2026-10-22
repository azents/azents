"""Real public SDK requests against injected synthetic streaming HTTP only."""

import asyncio
import io
import json
import logging
import threading
from collections.abc import Buffer, Callable, Iterator

import anyio
import httpx
import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseDownload
from pydantic import BaseModel

from azents.services.google_workspace.transport import (
    GoogleSdkError,
    GoogleSdkLimits,
    GoogleSdkSession,
    GoogleWorkspaceSdk,
)


class _Stream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


def _response(
    status: int, body: bytes, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, headers=headers, stream=_Stream((body,)))


def _sdk(handler: Callable[[httpx.Request], httpx.Response]) -> GoogleWorkspaceSdk:
    return GoogleWorkspaceSdk(
        capacity=1,
        client_factory=lambda proxy, timeout: httpx.Client(
            transport=httpx.MockTransport(handler), timeout=timeout
        ),
    )


def _limits(maximum: int = 1024) -> GoogleSdkLimits:
    return GoogleSdkLimits(
        maximum_response_bytes=maximum,
        maximum_total_received_bytes=maximum * 2,
        maximum_upload_bytes=1024,
        timeout=5,
    )


def _send(session: GoogleSdkSession) -> object:
    return session.execute(
        session.gmail.users().messages().send(userId="me", body={"raw": "dGVzdA"})
    )


@pytest.mark.parametrize("status", [200, 401, 403, 503])
async def test_sdk_sends_once_without_implicit_credential_refresh(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[httpx.Request] = []
    refreshed = 0

    def refresh(self: Credentials, request: object) -> None:
        nonlocal refreshed
        refreshed += 1
        raise AssertionError("Implicit credential refresh must not run.")

    monkeypatch.setattr(Credentials, "refresh", refresh)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = (
            b'{"id":"sent"}'
            if status == 200
            else b'{"error":{"message":"credential-content-canary"}}'
        )
        return _response(status, body, {"content-type": "application/json"})

    sdk = _sdk(handler)
    if status == 200:
        assert await sdk.run(
            before_request=lambda: None,
            access_token="fixture-access",
            limits=_limits(),
            proxy_url=None,
            operation=_send,
        ) == {"id": "sent"}
    else:
        with pytest.raises(GoogleSdkError) as error:
            await sdk.run(
                before_request=lambda: None,
                access_token="fixture-access",
                limits=_limits(),
                proxy_url=None,
                operation=_send,
            )
        assert error.value.status == status
        assert error.value.dispatched
        assert (
            error.value.code
            == {
                401: "authentication_rejected",
                403: "resource_rejected",
                503: "provider_unavailable",
            }[status]
        )
        assert error.value.provider_error is not None
        assert error.value.provider_error.message == "credential-content-canary"
        assert "fixture-access" not in str(error.value)
    assert len(requests) == 1
    assert refreshed == 0
    assert requests[0].method == "POST"
    assert requests[0].url.host == "gmail.googleapis.com"
    assert requests[0].url.path == "/gmail/v1/users/me/messages/send"
    assert requests[0].headers["authorization"] == "Bearer fixture-access"
    assert requests[0].headers["accept-encoding"] == "identity"
    assert json.loads(requests[0].content) == {"raw": "dGVzdA"}


@pytest.mark.parametrize(
    ("status", "reason"),
    [(403, "accessNotConfigured"), (403, "insufficientPermissions"), (404, "notFound")],
)
async def test_sdk_retains_original_provider_fields_without_request_dump(
    status: int, reason: str
) -> None:
    requests: list[httpx.Request] = []
    message = (
        "Gmail API is disabled for project 123456789. Enable it at "
        "https://console.developers.google.com/apis/api/gmail.googleapis.com/overview"
        "?project=123456789 for owner@example.com; file=resource-42. "
        "Token fixture-access and Bearer reflected-auth; refresh_token=refresh-secret"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(
            status,
            json.dumps(
                {
                    "error": {
                        "status": "PERMISSION_DENIED",
                        "message": message,
                        "errors": [{"reason": reason}],
                        "details": [{"reason": "FUTURE_REASON"}],
                        "private_debug": "never-return-this-field",
                    }
                }
            ).encode(),
            {"content-type": "application/json"},
        )

    with pytest.raises(GoogleSdkError) as caught:
        await _sdk(handler).run(
            before_request=lambda: None,
            access_token="fixture-access",
            limits=_limits(2048),
            proxy_url=None,
            operation=_send,
        )
    error = caught.value
    assert error.status == status and error.dispatched
    assert len(requests) == 1
    assert error.provider_error is not None
    assert error.provider_error.message == message
    output = error.provider_error.describe(error.status)
    for text in (
        "HTTP " + str(status),
        "PERMISSION_DENIED",
        reason,
        "FUTURE_REASON",
        "project 123456789",
        "?project=123456789",
        "owner@example.com",
        "resource-42",
        "fixture-access",
        "reflected-auth",
        "refresh-secret",
    ):
        assert text in output
    assert "never-return-this-field" not in output


async def test_static_resources_build_without_network_or_ambient_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Static discovery must perform no HTTP request.")

    def build(session: GoogleSdkSession) -> tuple[str, ...]:
        return (
            session.gmail.users().messages().list(userId="me").uri,
            session.calendar.freebusy()
            .query(
                body={
                    "timeMin": "2026-10-21T00:00:00Z",
                    "timeMax": "2026-10-22T00:00:00Z",
                    "items": [{"id": "primary"}],
                }
            )
            .uri,
            session.drive.files().get(fileId="fixture-file").uri,
        )

    result = await _sdk(handler).run(
        before_request=lambda: None,
        access_token="fixture-access",
        limits=_limits(),
        proxy_url=None,
        operation=build,
    )
    assert len(result) == 3
    assert result[0].startswith("https://gmail.googleapis.com/gmail/v1/")
    assert result[1].startswith("https://www.googleapis.com/calendar/v3/")
    assert result[2].startswith("https://www.googleapis.com/drive/v3/")


@pytest.mark.parametrize("headers", [{}, {"content-length": "2048"}])
async def test_receive_limit_is_enforced_without_trusting_metadata(
    headers: dict[str, str],
) -> None:
    stream = _Stream((b"x" * 512, b"x" * 512, b"x" * 1024))
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers=headers, stream=stream)

    with pytest.raises(GoogleSdkError) as error:
        await _sdk(handler).run(
            before_request=lambda: None,
            access_token="fixture",
            limits=_limits(1024),
            proxy_url=None,
            operation=_send,
        )
    assert error.value.code == "receive_limit"
    assert requests == 1
    assert stream.closed


@pytest.mark.parametrize(
    "headers,body,reason",
    [
        ({"content-length": "2"}, b"abc", "invalid_response_length"),
        ({"content-length": "invalid"}, b"abc", "invalid_response_length"),
        ({"content-length": "-1"}, b"abc", "receive_limit"),
        (
            {"content-encoding": "gzip"},
            b"compressed-canary",
            "unsupported_content_encoding",
        ),
    ],
)
async def test_invalid_transfer_metadata_never_becomes_a_success(
    headers: dict[str, str], body: bytes, reason: str
) -> None:
    with pytest.raises(GoogleSdkError) as error:
        await _sdk(lambda request: _response(200, body, headers)).run(
            before_request=lambda: None,
            access_token="fixture",
            limits=_limits(),
            proxy_url=None,
            operation=_send,
        )
    assert error.value.code == reason
    assert error.value.dispatched


async def test_aggregate_receive_budget_applies_across_sdk_requests() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return _response(200, b'{"id":"1234567890"}')

    def twice(session: GoogleSdkSession) -> None:
        _send(session)
        _send(session)

    limits = GoogleSdkLimits(
        maximum_response_bytes=25,
        maximum_total_received_bytes=30,
        maximum_upload_bytes=1024,
        timeout=5,
    )
    with pytest.raises(GoogleSdkError) as error:
        await _sdk(handler).run(
            before_request=lambda: None,
            access_token="fixture",
            limits=limits,
            proxy_url=None,
            operation=twice,
        )
    assert error.value.code == "receive_limit"
    assert requests == 2


async def test_oversized_outgoing_body_is_rejected_before_provider_dispatch() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return _response(200, b"{}")

    limits = GoogleSdkLimits(
        maximum_response_bytes=1024,
        maximum_total_received_bytes=1024,
        maximum_upload_bytes=4,
        timeout=5,
    )
    with pytest.raises(GoogleSdkError) as error:
        await _sdk(handler).run(
            before_request=lambda: None,
            access_token="fixture",
            limits=limits,
            proxy_url=None,
            operation=_send,
        )
    assert error.value.code == "upload_limit"
    assert not error.value.dispatched
    assert requests == 0


async def test_media_download_cannot_follow_untrusted_content_location() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return _response(
            206,
            b"first",
            {
                "content-range": "bytes 0-4/10",
                "content-location": "https://attacker.invalid/steal",
            },
        )

    def download(session: GoogleSdkSession) -> None:
        with io.BytesIO() as sink:
            request = session.drive.files().get_media(fileId="fixture-file")
            downloader = MediaIoBaseDownload(sink, request, chunksize=5)
            _, done = downloader.next_chunk(num_retries=0)
            assert not done
            downloader.next_chunk(num_retries=0)

    with pytest.raises(GoogleSdkError) as error:
        await _sdk(handler).run(
            before_request=lambda: None,
            access_token="fixture",
            limits=_limits(),
            proxy_url=None,
            operation=download,
        )
    assert error.value.code == "invalid_provider_endpoint"
    assert requests == 1


async def test_ignored_media_range_is_bounded_before_sdk_sink_write() -> None:
    writes: list[bytes] = []

    class Sink(io.BytesIO):
        def write(self, data: Buffer, /) -> int:
            writes.append(bytes(data))
            return super().write(data)

    def download(session: GoogleSdkSession) -> None:
        with Sink() as sink:
            downloader = MediaIoBaseDownload(
                sink, session.drive.files().get_media(fileId="fixture"), chunksize=5
            )
            downloader.next_chunk(num_retries=0)

    with pytest.raises(GoogleSdkError) as error:
        await _sdk(lambda request: _response(200, b"x" * 2048)).run(
            before_request=lambda: None,
            access_token="fixture",
            limits=_limits(1024),
            proxy_url=None,
            operation=download,
        )
    assert error.value.code == "receive_limit"
    assert not writes


@pytest.mark.parametrize("body", [b"{invalid-json", b"null"])
async def test_json_or_typed_result_decode_failure_is_not_reported_as_success(
    body: bytes,
) -> None:
    class Message(BaseModel):
        id: str

    def send(session: GoogleSdkSession) -> Message:
        return Message.model_validate(_send(session))

    with pytest.raises(GoogleSdkError) as error:
        await _sdk(lambda request: _response(200, body)).run(
            before_request=lambda: None,
            access_token="fixture",
            limits=_limits(),
            proxy_url=None,
            operation=send,
        )
    assert error.value.code == "invalid_provider_response"
    assert error.value.dispatched


async def test_proxy_configuration_and_client_lifetime_are_call_local() -> None:
    calls: list[tuple[str | None, float]] = []
    clients: list[httpx.Client] = []

    def factory(proxy: str | None, timeout: float) -> httpx.Client:
        calls.append((proxy, timeout))
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: _response(200, b'{"id":"one"}')
            )
        )
        clients.append(client)
        return client

    sdk = GoogleWorkspaceSdk(capacity=1, client_factory=factory)
    for proxy in ("http://proxy.invalid:8080", None):
        await sdk.run(
            before_request=lambda: None,
            access_token="fixture",
            limits=_limits(),
            proxy_url=proxy,
            operation=_send,
        )
    assert calls == [("http://proxy.invalid:8080", 5), (None, 5)]
    assert clients[0] is not clients[1]
    assert all(client.is_closed for client in clients)


async def test_cancellation_blocks_followup_and_keeps_actual_worker_bound() -> None:
    first_entered = asyncio.Event()
    first_released = asyncio.Event()
    release_first = threading.Event()
    first_done = threading.Event()
    active = 0
    maximum_active = 0
    requests: list[str] = []
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            index = len(requests)
            requests.append(request.url.path)
        try:
            if index == 0:
                anyio.from_thread.run_sync(first_entered.set)
                assert release_first.wait(5)
                first_done.set()
                anyio.from_thread.run_sync(first_released.set)
            return _response(200, b'{"id":"sent"}')
        finally:
            with lock:
                active -= 1

    def compound(session: GoogleSdkSession) -> None:
        _send(session)
        _send(session)

    sdk = _sdk(handler)
    first = asyncio.create_task(
        sdk.run(
            before_request=lambda: None,
            access_token="fixture",
            limits=_limits(),
            proxy_url=None,
            operation=compound,
        )
    )
    await first_entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(
        sdk.run(
            before_request=lambda: None,
            access_token="fixture",
            limits=_limits(),
            proxy_url=None,
            operation=_send,
        )
    )
    release_first.set()
    await first_released.wait()
    assert await second == {"id": "sent"}
    assert first_done.is_set()
    assert len(requests) == 2  # first effect, then separately admitted second call
    assert maximum_active == 1


@pytest.mark.parametrize("service", ["gmail", "calendar", "drive"])
async def test_sdk_resource_lifetime_is_inside_offloaded_worker(service: str) -> None:
    parent_thread = threading.get_ident()
    worker_threads: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        worker_threads.append(threading.get_ident())
        return _response(200, b"{}")

    def execute(session: GoogleSdkSession) -> object:
        match service:
            case "gmail":
                return session.execute(session.gmail.users().labels().list(userId="me"))
            case "calendar":
                return session.execute(session.calendar.calendarList().list())
            case "drive":
                return session.execute(session.drive.files().list())
            case _:
                raise AssertionError("Unsupported fixture service.")

    await _sdk(handler).run(
        before_request=lambda: None,
        access_token="fixture",
        limits=_limits(),
        proxy_url=None,
        operation=execute,
    )
    assert len(worker_threads) == 1
    assert worker_threads[0] != parent_thread


async def test_each_sdk_request_rechecks_current_admission_before_effect() -> None:
    admissions = 0
    requests = 0

    def admit() -> None:
        nonlocal admissions
        admissions += 1
        if admissions == 2:
            raise PermissionError("Current Google service is disabled.")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return _response(200, b'{"id":"first"}')

    def compound(session: GoogleSdkSession) -> None:
        _send(session)
        _send(session)

    with pytest.raises(PermissionError, match="service is disabled"):
        await _sdk(handler).run(
            access_token="fixture",
            limits=_limits(),
            proxy_url=None,
            before_request=admit,
            operation=compound,
        )
    assert admissions == 2
    assert requests == 1


async def test_third_party_sdk_diagnostics_do_not_log_content_or_capability_urls(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    # Existing model factories intentionally lower these SDK logger levels.
    # Force detail logging here so confidentiality checks cannot pass vacuously,
    # and let caplog restore the previous levels after this test.
    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="googleapiclient.discovery")

    def operation(session: GoogleSdkSession) -> object:
        logging.getLogger("googleapiclient.discovery").debug(
            "SDK diagnostic body %s", "message-content-canary"
        )
        logging.getLogger("httpx").info(
            "HTTP Request %s",
            "https://www.googleapis.com/upload/drive/v3?upload_id=canary",
        )
        return _send(session)

    await _sdk(lambda request: _response(200, b'{"id":"sent"}')).run(
        access_token="fixture-access-canary",
        limits=_limits(),
        proxy_url=None,
        before_request=lambda: None,
        operation=operation,
    )
    assert "message-content-canary" not in caplog.text
    assert "fixture-access-canary" not in caplog.text
    assert "upload_id=canary" not in caplog.text
    assert "gmail.googleapis.com" not in caplog.text
    # A separate context retains ordinary HTTP observability.
    logging.getLogger("httpx").info("Unrelated request remains observable.")
    assert "Unrelated request remains observable." in caplog.text
