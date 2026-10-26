"""Connection loss is recoverable without weakening account or target admission."""

import dataclasses
from datetime import timedelta

import pytest
from azents_runtime_control.browser_source_contract import BrowserScopeState

from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationGenerationError,
)
from azents.services.runtime_browser.data import (
    RuntimeBrowserAuthority,
    RuntimeBrowserStreamUnavailable,
    RuntimeBrowserUnavailable,
)
from azents.services.runtime_browser.socket import BrowserSocketFailure
from azents.services.runtime_browser.socket_test import (
    _harness as socket_harness,
)
from azents.services.runtime_browser.socket_test import (
    _start,
)
from azents.services.runtime_browser.stream_authority_test import (
    _CURRENT,
    _NOW,
    _RESOURCE,
    _TARGET,
    _harness,
    _scope,
)


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (
            dataclasses.replace(
                _CURRENT,
                target=dataclasses.replace(_CURRENT.target, runner_generation=6),
            ),
            BrowserScopeState.UNAVAILABLE,
        ),
        (
            RuntimeBrowserUnavailable("runtime_unavailable"),
            BrowserScopeState.UNAVAILABLE,
        ),
        (RuntimeBrowserUnavailable("browser_disabled"), BrowserScopeState.REVOKED),
        (dataclasses.replace(_CURRENT, allow_input=False), BrowserScopeState.REVOKED),
        (
            dataclasses.replace(
                _CURRENT, authentication_session_expires_at=_NOW + timedelta(minutes=1)
            ),
            BrowserScopeState.EXPIRED,
        ),
    ],
)
async def test_live_scope_classifies_reconnection_separately(
    current: RuntimeBrowserAuthority | RuntimeBrowserUnavailable,
    expected: BrowserScopeState,
) -> None:
    h = _harness()
    h.resolver.resolve.return_value = current
    assert await h.validator(_scope()) is expected
    h.runner.run_browser_command.assert_not_awaited()


@pytest.mark.parametrize(
    ("state", "code"),
    [
        (BrowserScopeState.UNAVAILABLE, 4500),
        (BrowserScopeState.REVOKED, 4403),
        (BrowserScopeState.EXPIRED, 4408),
    ],
)
async def test_socket_loss_does_not_mark_live_page_as_destroyed(
    state: BrowserScopeState, code: int
) -> None:
    h = socket_harness()
    h.validator.return_value = state
    with pytest.raises(BrowserSocketFailure) as caught:
        await _start(h)
    assert caught.value.code == code
    assert h.connection.closed and not h.socket.images


async def test_initial_native_admission_epoch_loss_is_not_stale_target() -> None:
    h = _harness()
    h.runner.run_browser_command.side_effect = RuntimeRunnerOperationGenerationError(
        "changed"
    )
    with pytest.raises(RuntimeBrowserStreamUnavailable):
        await h.validator.admit(
            resource=_RESOURCE,
            user_id="user-a",
            authentication_session_id="auth-a",
            target=_TARGET,
        )
    h.runner.run_browser_command.assert_awaited_once()
