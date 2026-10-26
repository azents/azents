"""Same-process native continuity and former connection effect retirement."""

import asyncio
from pathlib import Path
from typing import Literal

import pytest
from azents_runtime_control.browser_configuration import (
    BrowserConfigurationRequest,
    BrowserImplementation,
)
from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserCommand,
    BrowserObserveCommand,
    BrowserOpenCommand,
    BrowserResult,
)
from browser_controller_test import ControlledManager
from browser_test import _action, act, authority, observe, site, target
from browser_viewer_test import Budget, Transport, scope
from patchright.async_api import Error

from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_controller import RunnerBrowserController
from azents_runtime_runner.browser_input import BrowserInputKey
from azents_runtime_runner.browser_viewer import RunnerBrowserViewer, _Attachment
from azents_runtime_runner.execution import DirectExecutionBackend
from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.workspace import Workspace

__all__ = ["site"]


@pytest.mark.parametrize("implementation", list(BrowserImplementation))
async def test_connection_retirement_preserves_native_page_and_state(
    tmp_path: Path, site: str, implementation: BrowserImplementation
) -> None:
    generation: int | None = 7
    key = BrowserInputKey()
    budget = Budget()

    def factory(engine: BrowserImplementation) -> RunnerBrowserManager:
        manager = RunnerBrowserManager(
            workspace_root=tmp_path, proxy=None, input_key=key, implementation=engine
        )
        manager.bind_runtime("runtime", lambda: generation)
        return manager

    controller = RunnerBrowserController(
        factory, lambda manager: RunnerBrowserViewer(manager, budget), key
    )
    controller.bind_runtime("runtime", lambda: generation)
    intent = BrowserConfigurationRequest("intent", None, implementation)
    backend = DirectExecutionBackend()
    operations = RunnerOperations(
        client=TransportSink(),
        browser_manager=controller,
        workspace=Workspace(str(tmp_path)),
        execution_backend=backend,
    )
    try:
        assert (await controller.configure(intent)).state == "ready"
        opened = await controller.execute(
            "intent", BrowserOpenCommand(authority(tmp_path), None, site, None)
        )
        manager = controller.manager
        assert manager is not None and opened.page is not None
        native = manager.tasks[opened.page.task_id].pages[opened.page.id].page
        await native.evaluate("window.reconnectCanary = {value: 'survived'}")
        await native.evaluate("sessionStorage.setItem('reconnect', 'survived')")
        observed = await controller.execute(
            "intent",
            BrowserObserveCommand(
                authority(tmp_path), target(opened), "dom", False, 10000
            ),
        )
        assert observed.refs
        old_ref = observed.refs[0]
        transport = Transport()
        attachment = asyncio.create_task(
            controller.run(
                await scope(manager, tmp_path, site), transport.receive, transport.send
            )
        )
        await transport.frame()
        generation = None
        controller.cancel_connection_operations()
        await controller.suspend_connection()
        await operations.close()
        with pytest.raises(asyncio.CancelledError):
            await attachment
        assert budget.bytes == 0
        assert controller.manager is manager and not manager.closed
        assert not native.is_closed()
        generation = 8
        controller.validate_operation("runtime", 8)
        with pytest.raises(BrowserFailure, match="generation"):
            controller.validate_operation("runtime", 7)
        assert (await controller.configure(intent)).state == "ready"
        assert controller.manager is manager
        assert await native.evaluate("window.reconnectCanary.value") == "survived"
        assert (
            await native.evaluate("sessionStorage.getItem('reconnect')") == "survived"
        )
        with pytest.raises(BrowserFailure, match="reference"):
            await controller.execute(
                "intent",
                BrowserActCommand(
                    authority(tmp_path),
                    target(opened),
                    _action(
                        "click", ref=old_ref.id, observation_id=old_ref.observation_id
                    ),
                ),
            )
        fresh = await controller.execute(
            "intent",
            BrowserObserveCommand(
                authority(tmp_path), target(opened), "dom", False, 10000
            ),
        )
        assert fresh.page is not None
        assert fresh.page.id == opened.page.id
        assert fresh.page.resource_incarnation == opened.page.resource_incarnation
    finally:
        await operations.close()
        await controller.close()
        await backend.close()
    assert budget.bytes == 0


class TransportSink:
    async def append_runner_event(self, event: object) -> None:
        del event


async def test_detected_disconnect_cancels_admitted_effect_before_dispatch(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    effects: list[str] = []

    class WaitingManager(ControlledManager):
        async def execute(self, command: BrowserCommand) -> BrowserResult:
            entered.set()
            await release.wait()
            effects.append("must-not-dispatch")
            raise AssertionError("Former connection dispatched a native effect")

    manager = WaitingManager(tmp_path, BrowserImplementation.PATCHRIGHT)
    manager.release.set()
    controller = RunnerBrowserController(
        lambda _: manager,
        lambda native: RunnerBrowserViewer(native, Budget()),
        manager.input_key,
    )
    await controller.configure(
        BrowserConfigurationRequest("intent", None, BrowserImplementation.PATCHRIGHT)
    )
    operation = asyncio.create_task(
        controller.execute(
            "intent", BrowserOpenCommand(authority(tmp_path), None, None, None)
        )
    )
    await entered.wait()
    controller.cancel_connection_operations()
    release.set()
    await controller.suspend_connection()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not effects and not manager.closed
    await controller.close()


@pytest.mark.parametrize("failed_disposal", [False, True])
async def test_disconnect_drain_never_recancels_native_input_cleanup(
    tmp_path: Path, site: str, monkeypatch: pytest.MonkeyPatch, failed_disposal: bool
) -> None:
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.PATCHRIGHT,
    )
    manager.bind_runtime("runtime", lambda: 7)
    controller = RunnerBrowserController(
        lambda _: manager,
        lambda native: RunnerBrowserViewer(native, Budget()),
        manager.input_key,
    )
    await controller.configure(
        BrowserConfigurationRequest("intent", None, BrowserImplementation.PATCHRIGHT)
    )
    attached = await scope(manager, tmp_path, site)
    native = manager.tasks[attached.task_id].pages[attached.page_id].page
    entered = asyncio.Event()
    release = asyncio.Event()
    native_released = asyncio.Event()
    original_up = native.mouse.up

    async def blocked_up(*, button: Literal["left", "middle", "right"] | None) -> None:
        entered.set()
        await release.wait()
        await original_up(button=button)
        native_released.set()

    monkeypatch.setattr(native.mouse, "up", blocked_up)
    transport = Transport()
    running = asyncio.create_task(
        controller.run(attached, transport.receive, transport.send)
    )
    await transport.frame()
    ack = await transport.input(
        1, {"kind": "pointer", "phase": "down", "x": 10, "y": 10, "button": "left"}
    )
    assert ack["accepted"] is True
    if failed_disposal:

        async def dispose_failed(attachment: _Attachment) -> None:
            del attachment
            assert native_released.is_set()
            raise Error("Synthetic field snapshot disposal failure")

        monkeypatch.setattr(_Attachment, "discard_field_edit", dispose_failed)
    controller.cancel_connection_operations()
    await entered.wait()
    draining = asyncio.create_task(controller.suspend_connection())
    # This repeats the real receive-termination -> main teardown notifications.
    controller.cancel_connection_operations()
    release.set()
    await draining
    with pytest.raises(Error if failed_disposal else asyncio.CancelledError):
        await running
    assert manager.connection_cleanup_failed is failed_disposal
    assert not manager.closed and native_released.is_set()
    assert controller.configuration_status().state == (
        "failed" if failed_disposal else "ready"
    )
    assert manager.tasks[attached.task_id].guard.actor is None
    await controller.close()


async def test_pending_dialog_survives_without_automatic_answer_or_replay(
    tmp_path: Path, site: str
) -> None:
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.PATCHRIGHT,
    )
    manager.bind_runtime("runtime", lambda: 7)
    try:
        opened = await manager.execute(
            BrowserOpenCommand(authority(tmp_path), None, site, None)
        )
        current = target(opened)
        blocked = await act(
            manager,
            authority(tmp_path),
            current,
            await observe(manager, authority(tmp_path), current),
            "Alert",
        )
        assert blocked.dialog is not None
        resource = manager.tasks[current.task_id].pages[current.page_id]
        assert resource.pending is not None
        await manager.suspend_connection()
        assert not resource.page.is_closed() and resource.pending is None
        assert resource.dialog is not None
        refreshed = await observe(manager, authority(tmp_path), current, "status")
        assert refreshed.dialog is not None
        assert refreshed.dialog.id != blocked.dialog.id
        await manager.execute(
            BrowserActCommand(
                authority(tmp_path),
                current,
                _action("dialog", dialog_id=refreshed.dialog.id, accept=False),
            )
        )
    finally:
        await manager.close()


async def test_unconfirmed_attachment_cleanup_blocks_fresh_browser_authority(
    tmp_path: Path,
) -> None:
    manager = ControlledManager(tmp_path, BrowserImplementation.PATCHRIGHT)
    manager.release.set()
    controller = RunnerBrowserController(
        lambda _: manager,
        lambda native: RunnerBrowserViewer(native, Budget()),
        manager.input_key,
    )
    intent = BrowserConfigurationRequest(
        "intent", None, BrowserImplementation.PATCHRIGHT
    )
    await controller.configure(intent)
    manager.connection_cleanup_failed = True
    assert controller.configuration_status().reason_code == "browser_cleanup_failed"
    assert (await controller.configure(intent)).state == "failed"
    with pytest.raises(BrowserFailure, match="not ready"):
        await controller.execute(
            "intent", BrowserOpenCommand(authority(tmp_path), None, None, None)
        )
    assert not manager.closed
    await controller.close()


async def test_viewer_source_disposal_failure_preserves_native_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ControlledManager(tmp_path, BrowserImplementation.PATCHRIGHT)
    manager.release.set()
    controller = RunnerBrowserController(
        lambda _: manager,
        lambda native: RunnerBrowserViewer(native, Budget()),
        manager.input_key,
    )
    await controller.configure(
        BrowserConfigurationRequest("intent", None, BrowserImplementation.PATCHRIGHT)
    )
    viewer = controller.viewer
    assert viewer is not None

    async def fail_source_close() -> None:
        raise Error("Synthetic editable source disposal failure")

    with monkeypatch.context() as patch:
        patch.setattr(viewer, "close", fail_source_close)
        await controller.suspend_connection()
        assert controller.configuration_status().reason_code == "browser_cleanup_failed"
        assert controller.manager is manager and not manager.closed
    await controller.close()
