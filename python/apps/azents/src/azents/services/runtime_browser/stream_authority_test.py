"""Shared API/Owner current Browser stream scope and selected-resource tests."""

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple
from unittest.mock import AsyncMock

import pytest
from azents_runtime_control.browser_contract import BrowserPage, BrowserResult
from azents_runtime_control.browser_viewer_contract import ViewerTarget
from azents_runtime_control.runtime_stream_session import BrowserStreamAuthority

from azents.repos.runtime_browser_authority_read import (
    RuntimeBrowserAuthorityReadRepository,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
)
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget
from azents.services.runtime_browser.authority import (
    DatabaseRuntimeBrowserStreamScopeValidator,
    RuntimeBrowserAuthorityResolver,
)
from azents.services.runtime_browser.data import (
    RuntimeBrowserAuthority,
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
    RuntimeBrowserTargetUnavailable,
    RuntimeBrowserUnavailable,
)

_NOW = datetime(2026, 10, 15, tzinfo=UTC)
_RESOURCE = RuntimeBrowserResource("joined-handle", "agent-1", "concrete-session")
_TARGET = ViewerTarget("task-1", "page-1", "inc-1")
_CURRENT = RuntimeBrowserAuthority(
    _RESOURCE,
    "user-a",
    "auth-a",
    _NOW + timedelta(hours=2),
    RuntimeOperationTarget("runtime-1", 3, 8, 5, 2, "digest", "/reported"),
    "/reported/.azents/sessions/concrete-session",
    True,
)
_PAGE = BrowserPage("page-1", "task-1", "inc-1", "https://private.test/", "Private", ())


class _Harness(NamedTuple):
    validator: DatabaseRuntimeBrowserStreamScopeValidator
    repository: AsyncMock
    resolver: AsyncMock
    runner: AsyncMock


def _scope() -> BrowserStreamAuthority:
    return BrowserStreamAuthority(
        correlation_id="correlation-1",
        authentication_session_id="auth-a",
        user_id="user-a",
        agent_id="agent-1",
        runtime_id="runtime-1",
        desired_generation=8,
        runner_generation=5,
        open_deadline_at=_NOW + timedelta(seconds=10),
        transport_deadline_at=_NOW + timedelta(hours=1),
        session_id="concrete-session",
        task_id="task-1",
        page_id="page-1",
        resource_incarnation="inc-1",
        allow_input=True,
    )


def _harness() -> _Harness:
    repository = AsyncMock(spec=RuntimeBrowserAuthorityReadRepository)
    repository.read_stream_workspace_handle.return_value = "joined-handle"
    resolver = AsyncMock(spec=RuntimeBrowserAuthorityResolver)
    resolver.resolve.return_value = _CURRENT
    runner = AsyncMock(spec=RuntimeRunnerOperationClient)
    runner.run_browser_command.return_value = BrowserResult(
        (), _PAGE, None, False, (), None, None, None, None, "none"
    )
    return _Harness(
        DatabaseRuntimeBrowserStreamScopeValidator(
            repository,
            resolver,
            runner,
            lambda: _NOW,
        ),
        repository,
        resolver,
        runner,
    )


async def test_live_scope_checks_authority_without_reentrant_browser_rpc() -> None:
    h = _harness()
    h.runner.run_browser_command.side_effect = AssertionError(
        "An input authority check must not issue a nested Browser operation"
    )
    assert await h.validator(_scope())
    h.resolver.resolve.assert_awaited_once_with(
        resource=_RESOURCE,
        user_id="user-a",
        authentication_session_id="auth-a",
        resolved_at=_NOW,
    )
    h.resolver.resolve.return_value = RuntimeBrowserUnavailable("browser_disabled")
    assert not await h.validator(_scope())
    assert h.resolver.resolve.await_count == 2
    h.runner.run_browser_command.assert_not_awaited()


async def test_owner_callback_uses_current_joined_resource() -> None:
    h = _harness()
    assert await h.validator(_scope())
    h.repository.read_stream_workspace_handle.assert_awaited_once_with(
        agent_id="agent-1", session_id="concrete-session"
    )
    assert h.resolver.resolve.call_args.kwargs["resource"] == _RESOURCE


async def test_admission_uses_typed_selected_status() -> None:
    h = _harness()
    assert (
        await h.validator.admit(
            resource=_RESOURCE,
            user_id="user-a",
            authentication_session_id="auth-a",
            target=_TARGET,
        )
        == _CURRENT
    )
    call = h.runner.run_browser_command.call_args.kwargs
    assert call["owner_session_id"] == "concrete-session"
    assert call["runtime_id"] == "runtime-1" and call["runner_generation"] == 5
    command = call["command"]
    assert command.view == "status" and command.target.page_id == "page-1"
    assert (
        command.target.resource_incarnation == "inc-1"
        and command.target.frame_id is None
    )
    assert command.authority.working_directory == _CURRENT.working_directory


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_invalid_identity_or_resource_never_queries_title_or_selected_page(
    status: Literal[401, 403, 404],
) -> None:
    h = _harness()
    h.resolver.resolve.side_effect = RuntimeBrowserRequestError(status, "Denied")
    assert not await h.validator(_scope())
    h.runner.run_browser_command.assert_not_awaited()


async def test_missing_joined_resource_cannot_take_a_client_header_route() -> None:
    h = _harness()
    h.repository.read_stream_workspace_handle.return_value = None
    assert not await h.validator(_scope())
    h.resolver.resolve.assert_not_awaited()
    h.runner.run_browser_command.assert_not_awaited()


@pytest.mark.parametrize(
    "changed",
    [
        dataclasses.replace(_CURRENT, allow_input=False),
        dataclasses.replace(
            _CURRENT, target=dataclasses.replace(_CURRENT.target, id="runtime-2")
        ),
        dataclasses.replace(
            _CURRENT, target=dataclasses.replace(_CURRENT.target, desired_generation=9)
        ),
        dataclasses.replace(
            _CURRENT, target=dataclasses.replace(_CURRENT.target, runner_generation=6)
        ),
        dataclasses.replace(
            _CURRENT, authentication_session_expires_at=_NOW + timedelta(minutes=5)
        ),
        RuntimeBrowserUnavailable("runtime_unavailable"),
    ],
)
async def test_scope_and_expiry_changes_deny_existing_attachment(
    changed: RuntimeBrowserAuthority | RuntimeBrowserUnavailable,
) -> None:
    h = _harness()
    h.resolver.resolve.return_value = changed
    assert not await h.validator(_scope())


@pytest.mark.parametrize(
    "updates",
    [
        {"task_id": "other-task"},
        {"id": "other-page"},
        {"resource_incarnation": "old-incarnation"},
    ],
)
async def test_selected_page_status_must_match_all_target_identifiers(
    updates: dict[str, str],
) -> None:
    h = _harness()
    h.runner.run_browser_command.return_value = BrowserResult(
        (),
        dataclasses.replace(_PAGE, **updates),
        None,
        False,
        (),
        None,
        None,
        None,
        None,
        "none",
    )
    with pytest.raises(RuntimeBrowserTargetUnavailable):
        await h.validator.admit(
            resource=_RESOURCE,
            user_id="user-a",
            authentication_session_id="auth-a",
            target=_TARGET,
        )
    assert h.runner.run_browser_command.await_count == 1


@pytest.mark.parametrize("deadline", [_NOW, _NOW + timedelta(hours=2)])
async def test_expired_or_overlong_authority_denied_before_repository(
    deadline: datetime,
) -> None:
    h = _harness()
    authority = dataclasses.replace(
        _scope(), transport_deadline_at=deadline, open_deadline_at=min(_NOW, deadline)
    )
    assert not await h.validator(authority)
    h.repository.read_stream_workspace_handle.assert_not_awaited()


async def test_admission_revalidates_account_after_status_before_source_content() -> (
    None
):
    h = _harness()
    h.resolver.resolve.side_effect = [
        _CURRENT,
        RuntimeBrowserRequestError(401, "Revoked"),
    ]
    with pytest.raises(RuntimeBrowserRequestError):
        await h.validator.admit(
            resource=_RESOURCE,
            user_id="user-a",
            authentication_session_id="auth-a",
            target=_TARGET,
        )
    assert h.runner.run_browser_command.await_count == 1


async def test_runner_failure_denies_admission_without_retry_or_raw_error() -> None:
    h = _harness()
    h.runner.run_browser_command.side_effect = RuntimeRunnerOperationFailedError(
        "private signed URL", code="browser_stale_target"
    )
    with pytest.raises(RuntimeBrowserTargetUnavailable):
        await h.validator.admit(
            resource=_RESOURCE,
            user_id="user-a",
            authentication_session_id="auth-a",
            target=_TARGET,
        )
    assert h.runner.run_browser_command.await_count == 1


async def test_cancelled_scope_check_propagates_without_replay() -> None:
    h = _harness()
    h.resolver.resolve.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await h.validator(_scope())
    h.resolver.resolve.assert_awaited_once()
    h.runner.run_browser_command.assert_not_awaited()
