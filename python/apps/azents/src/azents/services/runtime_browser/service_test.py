"""Public Browser command admission, current evidence and failure semantics."""

import asyncio
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple
from unittest.mock import AsyncMock

import pytest
from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserObserveCommand,
    BrowserOpenCommand,
    BrowserPage,
    BrowserResult,
    BrowserTask,
    encode_browser_command,
)

from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationCanceledError,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget
from azents.services.runtime_browser.authority import RuntimeBrowserAuthorityResolver
from azents.services.runtime_browser.data import (
    RuntimeBrowserAuthority,
    RuntimeBrowserCreatedPage,
    RuntimeBrowserOperationError,
    RuntimeBrowserProjection,
    RuntimeBrowserReasonCode,
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
    RuntimeBrowserUnavailable,
)
from azents.services.runtime_browser.service import (
    RuntimeBrowserCommandRunner,
    RuntimeBrowserService,
)

_NOW = datetime(2026, 10, 15, tzinfo=UTC)
_RESOURCE = RuntimeBrowserResource("workspace", "agent-1", "concrete-session")
_AUTHORITY = RuntimeBrowserAuthority(
    _RESOURCE,
    "user-1",
    "auth-1",
    _NOW + timedelta(hours=1),
    RuntimeOperationTarget("runtime-1", 3, 8, 5, 2, "digest", "/runner-workspace"),
    "/runner-workspace/.azents/sessions/concrete-session",
    True,
)
_PAGE = BrowserPage("page-1", "task-1", "inc-1", "https://example.test/", "Page", ())
_TASK = BrowserTask("task-1", "Research", "task-inc", (_PAGE,))
_RESULT = BrowserResult((_TASK,), None, None, False, (), None, None, None, None, "none")


class _Harness(NamedTuple):
    service: RuntimeBrowserService
    resolver: AsyncMock
    runner: AsyncMock


def _service() -> _Harness:
    resolver = AsyncMock(spec=RuntimeBrowserAuthorityResolver)
    resolver.resolve.return_value = _AUTHORITY
    runner = AsyncMock(spec=RuntimeBrowserCommandRunner)
    runner.run_browser_command.return_value = _RESULT
    return _Harness(
        RuntimeBrowserService(resolver, runner, lambda: _NOW), resolver, runner
    )


async def _projection(service: RuntimeBrowserService) -> RuntimeBrowserProjection:
    return await service.projection(
        user_id="user-1", authentication_session_id="auth-1", resource=_RESOURCE
    )


async def _close(service: RuntimeBrowserService) -> RuntimeBrowserProjection:
    return await service.close_page(
        user_id="user-1",
        authentication_session_id="auth-1",
        resource=_RESOURCE,
        task_id="task-1",
        page_id="page-1",
        resource_incarnation="inc-1",
    )


async def _create(service: RuntimeBrowserService) -> RuntimeBrowserCreatedPage:
    return await service.create_page(
        user_id="user-1", authentication_session_id="auth-1", resource=_RESOURCE
    )


async def test_create_blank_page_uses_current_authority_and_confirmed_page() -> None:
    service, resolver, runner = _service()
    runner.run_browser_command.return_value = dataclasses.replace(_RESULT, page=_PAGE)
    created = await _create(service)
    assert created.page == _PAGE and created.projection.tasks == (_TASK,)
    command = runner.run_browser_command.call_args.kwargs["command"]
    assert isinstance(command, BrowserOpenCommand)
    assert command.task_id is None and command.url is None
    assert command.authority.session_id == _RESOURCE.session_id
    assert command.authority.working_directory == _AUTHORITY.working_directory
    assert resolver.resolve.await_count == 2


@pytest.mark.parametrize("read_only", [False, True])
async def test_create_denies_unavailable_and_read_only_before_allocation(
    read_only: bool,
) -> None:
    service, resolver, runner = _service()
    resolver.resolve.return_value = (
        dataclasses.replace(_AUTHORITY, allow_input=False)
        if read_only
        else RuntimeBrowserUnavailable("browser_disabled")
    )
    with pytest.raises(RuntimeBrowserRequestError):
        await _create(service)
    runner.run_browser_command.assert_not_awaited()


async def test_create_rejects_unconfirmed_result_and_never_retries() -> None:
    service, _, runner = _service()
    with pytest.raises(RuntimeBrowserOperationError, match="not confirmed"):
        await _create(service)
    assert runner.run_browser_command.await_count == 1


async def test_create_capacity_failure_is_a_conflict_without_retry() -> None:
    service, _, runner = _service()
    runner.run_browser_command.side_effect = RuntimeRunnerOperationFailedError(
        "private", code="browser_resource_exhausted"
    )
    with pytest.raises(RuntimeBrowserRequestError) as error:
        await _create(service)
    assert error.value.status_code == 409
    assert "private" not in str(error.value)
    assert runner.run_browser_command.await_count == 1


async def test_create_revalidates_authority_after_dispatch() -> None:
    service, resolver, runner = _service()
    runner.run_browser_command.return_value = dataclasses.replace(_RESULT, page=_PAGE)
    resolver.resolve.side_effect = [
        _AUTHORITY,
        RuntimeBrowserUnavailable("browser_disabled"),
    ]
    with pytest.raises(RuntimeBrowserRequestError, match="authority changed"):
        await _create(service)
    assert runner.run_browser_command.await_count == 1


async def test_projection_uses_only_status_and_concrete_bound_session() -> None:
    service, resolver, runner = _service()
    projection = await _projection(service)
    assert (
        projection.available and projection.tasks == (_TASK,) and projection.allow_input
    )
    call = runner.run_browser_command.call_args.kwargs
    assert call["runtime_id"] == "runtime-1" and call["runner_generation"] == 5
    assert call["owner_session_id"] == "concrete-session"
    command = call["command"]
    assert isinstance(command, BrowserObserveCommand)
    assert command.target is None and command.view == "status"
    assert command.authority.session_id == "concrete-session"
    assert command.authority.working_directory == _AUTHORITY.working_directory
    assert resolver.resolve.await_count == 2
    assert runner.run_browser_command.await_count == 1


@pytest.mark.parametrize(
    "reason",
    ["runtime_unavailable", "browser_unavailable", "working_folder_unavailable"],
)
async def test_unavailable_projection_is_content_free_without_loading_runtime(
    reason: RuntimeBrowserReasonCode,
) -> None:
    service, resolver, runner = _service()
    resolver.resolve.return_value = RuntimeBrowserUnavailable(reason)
    projection = await _projection(service)
    assert not projection.available and projection.reason_code == reason
    assert not projection.tasks and not projection.allow_input
    runner.run_browser_command.assert_not_awaited()


@pytest.mark.parametrize("method", ["projection", "close"])
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_access_denied_before_any_runner_effect(
    method: str, status: Literal[401, 403, 404]
) -> None:
    service, resolver, runner = _service()
    resolver.resolve.side_effect = RuntimeBrowserRequestError(status, "Denied")
    with pytest.raises(RuntimeBrowserRequestError) as captured:
        await (_projection(service) if method == "projection" else _close(service))
    assert captured.value.status_code == status
    runner.run_browser_command.assert_not_awaited()


async def test_close_has_exact_main_page_target_and_current_generation() -> None:
    service, _, runner = _service()
    runner.run_browser_command.return_value = dataclasses.replace(
        _RESULT, tasks=(), action_state="dispatched"
    )
    projection = await _close(service)
    assert projection.available and projection.tasks == ()
    command = runner.run_browser_command.call_args.kwargs["command"]
    assert isinstance(command, BrowserActCommand)
    assert command.authority.session_id == "concrete-session"
    assert command.authority.working_directory == _AUTHORITY.working_directory
    assert command.target.task_id == "task-1" and command.target.page_id == "page-1"
    assert (
        command.target.resource_incarnation == "inc-1"
        and command.target.frame_id is None
    )
    assert command.action.kind == "close_page"
    encode_browser_command(command)
    assert runner.run_browser_command.await_count == 1


async def test_subagent_is_observable_but_never_closable() -> None:
    service, resolver, runner = _service()
    resolver.resolve.return_value = dataclasses.replace(_AUTHORITY, allow_input=False)
    projection = await _projection(service)
    assert projection.available and not projection.allow_input
    runner.reset_mock()
    with pytest.raises(RuntimeBrowserRequestError, match="read-only"):
        await _close(service)
    runner.run_browser_command.assert_not_awaited()


async def test_unavailable_close_is_conflict_not_successful_projection() -> None:
    service, resolver, runner = _service()
    resolver.resolve.return_value = RuntimeBrowserUnavailable("runtime_unavailable")
    with pytest.raises(RuntimeBrowserRequestError) as captured:
        await _close(service)
    assert captured.value.status_code == 409
    runner.run_browser_command.assert_not_awaited()


@pytest.mark.parametrize(
    "changed",
    [
        dataclasses.replace(
            _AUTHORITY,
            target=dataclasses.replace(_AUTHORITY.target, desired_generation=9),
        ),
        dataclasses.replace(
            _AUTHORITY,
            target=dataclasses.replace(_AUTHORITY.target, runner_generation=6),
        ),
        dataclasses.replace(_AUTHORITY, working_directory="/runner-workspace/other"),
        dataclasses.replace(_AUTHORITY, allow_input=False),
        RuntimeBrowserUnavailable("runtime_unavailable"),
    ],
)
async def test_changed_authority_during_command_hides_results_without_replay(
    changed: RuntimeBrowserAuthority | RuntimeBrowserUnavailable,
) -> None:
    service, resolver, runner = _service()
    resolver.resolve.side_effect = [_AUTHORITY, changed]
    with pytest.raises(RuntimeBrowserRequestError, match="authority changed"):
        await _projection(service)
    assert runner.run_browser_command.await_count == 1


async def test_account_revocation_during_command_prevents_returning_page_content() -> (
    None
):
    service, resolver, runner = _service()
    resolver.resolve.side_effect = [
        _AUTHORITY,
        RuntimeBrowserRequestError(401, "Not authenticated"),
    ]
    with pytest.raises(RuntimeBrowserRequestError) as captured:
        await _projection(service)
    assert captured.value.status_code == 401
    assert runner.run_browser_command.await_count == 1


@pytest.mark.parametrize(
    "error",
    [
        RuntimeRunnerOperationGenerationError("private"),
        RuntimeRunnerOperationUnavailable("private"),
        RuntimeRunnerOperationCanceledError("private"),
        RuntimeRunnerOperationFailedError("private", code="browser_stale_target"),
        RuntimeRunnerOperationFailedError("private", code="browser_input_conflict"),
    ],
)
async def test_expected_command_conflicts_raise_without_raw_error_or_retry(
    error: Exception,
) -> None:
    service, _, runner = _service()
    runner.run_browser_command.side_effect = error
    with pytest.raises(RuntimeBrowserRequestError) as captured:
        await _close(service)
    assert captured.value.status_code == 409 and "private" not in str(captured.value)
    assert runner.run_browser_command.await_count == 1


@pytest.mark.parametrize("code", ["browser_invalid_response", "unknown-private-code"])
async def test_actual_command_failure_is_not_an_unavailable_success(code: str) -> None:
    service, _, runner = _service()
    runner.run_browser_command.side_effect = RuntimeRunnerOperationFailedError(
        "signed-private-url", code=code
    )
    with pytest.raises(RuntimeBrowserOperationError) as captured:
        await _projection(service)
    assert "private" not in str(captured.value)
    assert runner.run_browser_command.await_count == 1


async def test_cancellation_propagates_without_replay() -> None:
    service, _, runner = _service()
    runner.run_browser_command.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await _close(service)
    assert runner.run_browser_command.await_count == 1


async def test_inconsistent_returned_task_page_list_is_rejected() -> None:
    service, _, runner = _service()
    runner.run_browser_command.return_value = dataclasses.replace(
        _RESULT,
        tasks=(
            dataclasses.replace(
                _TASK, pages=(dataclasses.replace(_PAGE, task_id="other-task"),)
            ),
        ),
    )
    with pytest.raises(RuntimeBrowserOperationError):
        await _projection(service)
    assert runner.run_browser_command.await_count == 1


async def test_projection_does_not_expose_command_content_capture_or_dialog() -> None:
    service, _, runner = _service()
    runner.run_browser_command.return_value = dataclasses.replace(
        _RESULT, content="private-not-part-of-list"
    )
    result = await _projection(service)
    assert "private-not-part-of-list" not in json.dumps(dataclasses.asdict(result))


@pytest.mark.parametrize(
    "result",
    [
        dataclasses.replace(_RESULT, tasks=(), action_state="none"),
        dataclasses.replace(_RESULT, tasks=(), action_state="dialog_pending"),
        dataclasses.replace(_RESULT, action_state="dispatched"),
    ],
)
async def test_unconfirmed_closure_does_not_become_success_or_retry(
    result: BrowserResult,
) -> None:
    service, _, runner = _service()
    runner.run_browser_command.return_value = result
    with pytest.raises(RuntimeBrowserOperationError, match="not confirmed"):
        await _close(service)
    assert runner.run_browser_command.await_count == 1
