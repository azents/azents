"""Exact-intent transition and recovery tests for browser-only ownership."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from azents_runtime_control.browser_configuration import (
    BrowserConfigurationRequest,
    BrowserImplementation,
)
from azents_runtime_control.browser_contract import BrowserOpenCommand
from browser_operations_test import Sink, operation
from browser_test import authority, site, target
from browser_viewer_test import Budget, Transport, scope

from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_controller import RunnerBrowserController
from azents_runtime_runner.browser_input import BrowserInputKey
from azents_runtime_runner.browser_viewer import RunnerBrowserViewer
from azents_runtime_runner.execution import DirectExecutionBackend
from azents_runtime_runner.operation_payloads import (
    ProcessStartPayload,
    ProcessWritePayload,
)
from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.workspace import Workspace

__all__ = ["site"]


def request(
    intent: str, expected: str | None, implementation: BrowserImplementation
) -> BrowserConfigurationRequest:
    return BrowserConfigurationRequest(intent, expected, implementation)


async def test_switch_retires_only_browser_and_preserves_native_profiles(
    tmp_path: Path, site: str
) -> None:
    budget = Budget()
    generation = 7
    key = BrowserInputKey()

    def factory(implementation: BrowserImplementation) -> RunnerBrowserManager:
        manager = RunnerBrowserManager(
            workspace_root=tmp_path,
            proxy=None,
            input_key=key,
            implementation=implementation,
        )
        manager.bind_runtime("runtime", lambda: generation)
        return manager

    controller = RunnerBrowserController(
        factory, lambda manager: RunnerBrowserViewer(manager, budget), key
    )
    operations = RunnerOperations(
        client=Sink(),
        browser_manager=controller,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    try:
        await operations._process_start(
            replace(operation(tmp_path, generation), operation_type="process.start"),
            ProcessStartPayload(
                "read value; printf '%s' \"$value\" > continued.txt",
                str(tmp_path),
                {},
                0,
                4096,
                False,
            ),
        )
        [process] = operations._processes.values()
        assert process.process.returncode is None
        assert controller.status.state == "unconfigured"
        with pytest.raises(BrowserFailure, match="stale"):
            await controller.execute(
                "first", BrowserOpenCommand(authority(tmp_path), None, site, None)
            )
        first = request("first", None, BrowserImplementation.PATCHRIGHT)
        assert (await controller.configure(first)).state == "ready"
        opened = await controller.execute(
            "first", BrowserOpenCommand(authority(tmp_path), None, site, None)
        )
        old = controller.manager
        assert old is not None
        assert (await controller.configure(first)).state == "ready"
        assert controller.manager is old and old.tasks
        viewer_scope = await scope(old, tmp_path, site)
        transport = Transport()
        attachment = asyncio.create_task(
            controller.run(viewer_scope, transport.receive, transport.send)
        )
        await transport.frame()
        assert (
            await controller.configure(
                request("second", "first", BrowserImplementation.CAMOUFOX)
            )
        ).state == "ready"
        with pytest.raises(asyncio.CancelledError):
            await attachment
        with pytest.raises(BrowserFailure, match="unavailable"):
            controller.validate(viewer_scope)
        assert budget.bytes == 0
        assert operations._processes[process.process_id] is process
        assert process.process.returncode is None
        await operations._process_write(
            replace(
                operation(tmp_path, generation),
                request_id="shell-write",
                operation_type="process.write",
            ),
            ProcessWritePayload(
                process.process_id, "continued-after-switch\n", 0, 4096
            ),
        )
        assert await process.process.wait() == 0
        assert (tmp_path / "continued.txt").read_text() == "continued-after-switch"
        assert old.closed and not old.tasks and old.driver is None
        with pytest.raises(BrowserFailure, match="closed"):
            old.target(authority(tmp_path), target(opened))
        with pytest.raises(BrowserFailure, match="stale"):
            await controller.execute(
                "first", BrowserOpenCommand(authority(tmp_path), None, site, None)
            )
        with pytest.raises(BrowserFailure, match="stale"):
            await controller.configure(
                request("late", "first", BrowserImplementation.PATCHRIGHT)
            )
        current = controller.manager
        assert current is not None and current is not old
        current.validate_operation("runtime", generation)
        await controller.execute(
            "second", BrowserOpenCommand(authority(tmp_path), None, site, None)
        )
        assert generation == 7
    finally:
        await operations.close()
        await controller.close()
    assert budget.bytes == 0


class ControlledManager(RunnerBrowserManager):
    def __init__(self, root: Path, implementation: BrowserImplementation) -> None:
        super().__init__(
            workspace_root=root,
            proxy=None,
            input_key=BrowserInputKey(),
            implementation=implementation,
        )
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.fail_startup = False
        self.fail_cleanup = False

    async def initialize(self) -> None:
        self.started.set()
        await self.release.wait()
        if self.fail_startup:
            raise BrowserFailure("browser_unavailable", "Fixture startup failure")

    async def close(self) -> None:
        await super().close()
        if self.fail_cleanup:
            raise BrowserFailure("browser_cleanup_failed", "Fixture cleanup failure")


async def test_superseded_startup_never_promotes_old_intent(tmp_path: Path) -> None:
    created: asyncio.Queue[ControlledManager] = asyncio.Queue()
    superseded = asyncio.Event()

    class SignaledController(RunnerBrowserController):
        async def _apply(self, request: BrowserConfigurationRequest) -> None:
            if request.intent_id == "second":
                superseded.set()
            await super()._apply(request)

    def factory(implementation: BrowserImplementation) -> RunnerBrowserManager:
        manager = ControlledManager(tmp_path, implementation)
        created.put_nowait(manager)
        return manager

    controller = SignaledController(
        factory,
        lambda manager: RunnerBrowserViewer(manager, Budget()),
        BrowserInputKey(),
    )
    first = asyncio.create_task(
        controller.configure(request("first", None, BrowserImplementation.PATCHRIGHT))
    )
    old = await created.get()
    await old.started.wait()
    second = asyncio.create_task(
        controller.configure(request("second", "first", BrowserImplementation.CAMOUFOX))
    )
    await superseded.wait()
    old.release.set()
    new = await created.get()
    await new.started.wait()
    assert old.closed and controller.status.intent_id == "second"
    assert controller.status.state == "applying"
    new.release.set()
    await asyncio.gather(first, second)
    assert (
        controller.status.intent_id == "second" and controller.status.state == "ready"
    )
    assert controller.manager is new
    await controller.close()


async def test_lost_response_reconciles_without_restart(tmp_path: Path) -> None:
    manager = ControlledManager(tmp_path, BrowserImplementation.CAMOUFOX)
    controller = RunnerBrowserController(
        lambda _: manager,
        lambda manager: RunnerBrowserViewer(manager, Budget()),
        BrowserInputKey(),
    )
    intent = request("first", None, BrowserImplementation.CAMOUFOX)
    call = asyncio.create_task(controller.configure(intent))
    await manager.started.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert (await controller.configure(intent)).state == "applying"
    manager.release.set()
    await asyncio.gather(*controller.transitions)
    assert (await controller.configure(intent)).state == "ready"
    assert controller.manager is manager and not manager.closed
    await controller.close()


async def test_failed_startup_never_falls_back_or_replays_same_intent(
    tmp_path: Path,
) -> None:
    manager = ControlledManager(tmp_path, BrowserImplementation.CAMOUFOX)
    manager.fail_startup = True
    manager.release.set()
    controller = RunnerBrowserController(
        lambda _: manager,
        lambda manager: RunnerBrowserViewer(manager, Budget()),
        BrowserInputKey(),
    )
    intent = request("first", None, BrowserImplementation.CAMOUFOX)
    result = await controller.configure(intent)
    assert (
        result.state == "failed"
        and result.implementation is BrowserImplementation.CAMOUFOX
    )
    manager.fail_startup = False
    assert (await controller.configure(intent)).state == "failed"
    assert manager.closed
    await controller.close()


async def test_unconfirmed_retirement_never_starts_competing_browser(
    tmp_path: Path,
) -> None:
    created: list[ControlledManager] = []

    def factory(implementation: BrowserImplementation) -> RunnerBrowserManager:
        manager = ControlledManager(tmp_path, implementation)
        manager.release.set()
        created.append(manager)
        return manager

    controller = RunnerBrowserController(
        factory,
        lambda manager: RunnerBrowserViewer(manager, Budget()),
        BrowserInputKey(),
    )
    await controller.configure(request("first", None, BrowserImplementation.PATCHRIGHT))
    created[0].fail_cleanup = True
    second = await controller.configure(
        request("second", "first", BrowserImplementation.CAMOUFOX)
    )
    assert second.state == "failed" and second.reason_code == "browser_cleanup_failed"
    assert len(created) == 1
    created[0].fail_cleanup = False
    third = await controller.configure(
        request("third", "second", BrowserImplementation.CAMOUFOX)
    )
    assert third.state == "failed" and third.reason_code == "browser_cleanup_failed"
    assert len(created) == 1
    await controller.close()


async def test_unexpected_startup_failure_is_failed_evidence_without_private_values(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class BrokenManager(ControlledManager):
        async def initialize(self) -> None:
            raise ValueError("private-startup-canary")

    manager = BrokenManager(tmp_path, BrowserImplementation.CAMOUFOX)
    controller = RunnerBrowserController(
        lambda _: manager,
        lambda manager: RunnerBrowserViewer(manager, Budget()),
        BrowserInputKey(),
    )
    result = await controller.configure(
        request("first", None, BrowserImplementation.CAMOUFOX)
    )
    assert (
        result.state == "failed" and result.reason_code == "browser_application_failed"
    )
    assert manager.closed
    assert "private-startup-canary" not in caplog.text
    assert caplog.records[-1].getMessage() == "Browser application failed"
    await controller.close()
