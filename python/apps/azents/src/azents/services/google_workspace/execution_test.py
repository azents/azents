"""Async current-owner admission wraps every real SDK HTTP request without replay."""

import dataclasses
import json
import threading
from collections.abc import Callable, Iterator
from types import TracebackType
from unittest.mock import NonCallableMock

import httpx
import pytest

from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_runtime import (
    GoogleExecutionState,
    GoogleOperationAuthorization,
)
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.services.google_oauth.runtime_test import _harness
from azents.services.google_workspace import calendar
from azents.services.google_workspace.calendar_models import CalendarRsvpInput
from azents.services.google_workspace.execution import GoogleWorkspaceExecution
from azents.services.google_workspace.transport import (
    GoogleSdkError,
    GoogleSdkLimits,
    GoogleSdkSession,
    GoogleWorkspaceSdk,
)


class _Stream(httpx.SyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __iter__(self) -> Iterator[bytes]:
        yield self.body


def _execution(
    handler: Callable[[httpx.Request], httpx.Response],
) -> GoogleWorkspaceExecution:
    h = _harness(expired=False)
    sdk = GoogleWorkspaceSdk(
        capacity=1,
        client_factory=lambda proxy, timeout: httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
    )
    return GoogleWorkspaceExecution(h.service, sdk)


def _limits() -> GoogleSdkLimits:
    return GoogleSdkLimits(65536, 131072, 65536, 5)


def _read(s: GoogleSdkSession) -> object:
    return s.execute(s.calendar.events().get(calendarId="primary", eventId="event"))


def _receipt(execution: GoogleWorkspaceExecution) -> GoogleOperationAuthorization:
    # The existing runtime harness establishes real service policy and provider
    # mocks; receipt construction below is only this test's initial stage.
    repo = execution.runtime.repository
    assert isinstance(repo, NonCallableMock)
    current = repo.load.return_value
    assert isinstance(current, GoogleExecutionState)
    return GoogleOperationAuthorization(
        SessionExecutionOwner("session", 7), Op.CALENDAR_GET_EVENT, (), current
    )


async def test_current_admission_runs_on_event_loop_before_each_sdk_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=_Stream(b'{"id":"event"}'))

    execution = _execution(handler)
    admitted = _receipt(execution)
    checked = 0

    async def inputs() -> None:
        nonlocal checked
        checked += 1

    result = await execution.execute(
        admitted=admitted,
        limits=_limits(),
        proxy_url=None,
        operation=_read,
        revalidate_inputs=inputs,
    )
    assert result == {"id": "event"}
    assert len(requests) == 1 and checked == 3


async def test_input_loss_after_first_request_retains_dispatched_uncertainty() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=_Stream(b'{"id":"event"}'))

    execution = _execution(handler)

    async def inputs() -> None:
        if requests:
            raise GoogleSdkError("file_source_changed", dispatched=False, status=None)

    def compound(sdk: GoogleSdkSession) -> object:
        _read(sdk)
        return _read(sdk)

    with pytest.raises(GoogleSdkError) as error:
        await execution.execute(
            admitted=_receipt(execution),
            limits=_limits(),
            proxy_url=None,
            operation=compound,
            revalidate_inputs=inputs,
        )
    assert error.value.code == "file_source_changed"
    assert error.value.dispatched and len(requests) == 1


async def test_post_sdk_input_loss_retains_dispatched_uncertainty() -> None:
    requests: list[httpx.Request] = []
    closed = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=_Stream(b'{"id":"event"}'))

    class ClosingClient(httpx.Client):
        def __exit__(
            self,
            exc_type: type[BaseException] | None = None,
            exc_value: BaseException | None = None,
            traceback: TracebackType | None = None,
        ) -> None:
            super().__exit__(exc_type, exc_value, traceback)
            closed.set()

    execution = dataclasses.replace(
        _execution(handler),
        sdk=GoogleWorkspaceSdk(
            capacity=1,
            client_factory=lambda proxy, timeout: ClosingClient(
                transport=httpx.MockTransport(handler)
            ),
        ),
    )

    async def inputs() -> None:
        # The client closes after the SDK's final in-thread admission, precisely
        # before the execution wrapper's final event-loop input check.
        if closed.is_set():
            raise GoogleSdkError("file_source_changed", dispatched=False, status=None)

    with pytest.raises(GoogleSdkError) as error:
        await execution.execute(
            admitted=_receipt(execution),
            limits=_limits(),
            proxy_url=None,
            operation=_read,
            revalidate_inputs=inputs,
        )
    assert error.value.code == "file_source_changed"
    assert error.value.dispatched and len(requests) == 1


async def test_revoked_input_blocks_request_even_with_current_google_grant() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=_Stream(b"{}"))

    execution = _execution(handler)

    async def deny() -> None:
        raise GoogleOAuthError("file_unavailable", "Current file access withdrawn.")

    with pytest.raises(GoogleOAuthError):
        await execution.execute(
            admitted=_receipt(execution),
            limits=_limits(),
            proxy_url=None,
            operation=_read,
            revalidate_inputs=deny,
        )
    assert not requests


@pytest.mark.parametrize("status", [401, 403, 503])
async def test_only_401_finalizes_original_admitted_snapshot(status: int) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            stream=_Stream(
                json.dumps({"error": {"message": "private-google-response"}}).encode()
            ),
        )

    execution = _execution(handler)
    admitted = _receipt(execution)
    with pytest.raises(GoogleSdkError) as error:
        await execution.execute(
            admitted=admitted,
            limits=_limits(),
            proxy_url=None,
            operation=_read,
            revalidate_inputs=None,
        )
    assert len(requests) == 1 and error.value.status == status
    repo = execution.runtime.repository
    assert isinstance(repo, NonCallableMock)
    if status == 401:
        repo.finalize_refresh.assert_awaited_once_with(
            admitted.owner, snapshot=admitted.snapshot, refreshed=None, rejected=True
        )
    else:
        repo.finalize_refresh.assert_not_awaited()
    assert "private-google-response" not in str(error.value)


async def test_config_change_during_first_request_blocks_followup_patch() -> None:
    execution = _execution(lambda request: httpx.Response(200, stream=_Stream(b"{}")))
    admitted = _receipt(execution)
    repo = execution.runtime.repository
    assert isinstance(repo, NonCallableMock)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        repo.load.return_value = dataclasses.replace(
            admitted.snapshot, revision=admitted.snapshot.revision + 1
        )
        return httpx.Response(
            200,
            stream=_Stream(
                b'{"id":"event","attendees":[{"email":"connected@example.com","self":true}]}'
            ),
        )

    execution = dataclasses.replace(
        execution,
        sdk=GoogleWorkspaceSdk(
            capacity=1,
            client_factory=lambda proxy, timeout: httpx.Client(
                transport=httpx.MockTransport(handler)
            ),
        ),
    )
    # Fixture grants are expanded for this exact RSVP scope; never requested scopes.
    candidate = admitted.snapshot.connection.candidate
    updated = dataclasses.replace(
        admitted.snapshot,
        connection=dataclasses.replace(
            admitted.snapshot.connection,
            candidate=candidate.model_copy(
                update={
                    "tokens": candidate.tokens.model_copy(
                        update={
                            "granted_scopes": (
                                "https://www.googleapis.com/auth/calendar.events",
                            )
                        }
                    )
                }
            ),
        ),
    )
    admitted = dataclasses.replace(
        admitted, operation=Op.CALENDAR_RESPOND_EVENT, snapshot=updated
    )
    repo.load.return_value = updated
    with pytest.raises(GoogleOAuthError):
        await execution.execute(
            admitted=admitted,
            limits=_limits(),
            proxy_url=None,
            operation=lambda s: calendar.respond_event(
                s,
                CalendarRsvpInput(
                    calendar_id="primary",
                    event_id="event",
                    response_status="accepted",
                    comment=None,
                    send_updates="all",
                ),
            ),
            revalidate_inputs=None,
        )
    assert len(requests) == 1 and requests[0].method == "GET"


async def test_result_after_authority_loss_is_not_surfaced_as_success() -> None:
    execution = _execution(lambda request: httpx.Response(200, stream=_Stream(b"{}")))
    admitted = _receipt(execution)
    repo = execution.runtime.repository
    assert isinstance(repo, NonCallableMock)

    def handler(request: httpx.Request) -> httpx.Response:
        repo.load.return_value = dataclasses.replace(
            admitted.snapshot, revision=admitted.snapshot.revision + 1
        )
        return httpx.Response(200, stream=_Stream(b'{"id":"event"}'))

    execution = dataclasses.replace(
        execution,
        sdk=GoogleWorkspaceSdk(
            capacity=1,
            client_factory=lambda proxy, timeout: httpx.Client(
                transport=httpx.MockTransport(handler)
            ),
        ),
    )
    with pytest.raises(GoogleSdkError) as error:
        await execution.execute(
            admitted=admitted,
            limits=_limits(),
            proxy_url=None,
            operation=_read,
            revalidate_inputs=None,
        )
    assert error.value.code == "result_authority_changed" and error.value.dispatched
