"""Display ownership, readiness and failure cleanup without startup sleeps."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from azents_runtime_control.browser_contract import BrowserAuthority, BrowserOpenCommand

import azents_runtime_runner.browser as browser_module
import azents_runtime_runner.browser_display as display_module
from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_display import BrowserDisplay, BrowserDisplayError
from azents_runtime_runner.browser_input import BrowserInputKey


@pytest.mark.parametrize("platform, native", [("linux", ":99"), ("darwin", None)])
async def test_native_display_is_not_owned(
    monkeypatch: pytest.MonkeyPatch, platform: str, native: str | None
) -> None:
    monkeypatch.setattr(display_module.sys, "platform", platform)
    if native is None:
        monkeypatch.delenv("DISPLAY", raising=False)
    else:
        monkeypatch.setenv("DISPLAY", native)
    spawn = AsyncMock()
    monkeypatch.setattr(display_module.asyncio, "create_subprocess_exec", spawn)
    owner = BrowserDisplay()
    assert await owner.start() is None
    await owner.close()
    spawn.assert_not_called()


async def test_owned_display_reuses_readiness_and_reaps_exact_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(display_module.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    process = MagicMock(spec=asyncio.subprocess.Process)
    process.returncode = None
    process.stdout = asyncio.StreamReader()
    process.stdout.feed_data(b"143\n")
    process.wait = AsyncMock(return_value=0)
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(display_module.asyncio, "create_subprocess_exec", spawn)
    owner = BrowserDisplay()
    environment = await owner.start()
    assert environment is not None and environment["DISPLAY"] == ":143"
    assert await owner.start() is environment
    spawn.assert_awaited_once()
    assert spawn.call_args.args[-2:] == ("-nolisten", "tcp")
    assert "DISPLAY" not in display_module.os.environ
    await owner.close()
    process.terminate.assert_called_once()
    process.wait.assert_awaited_once()
    await owner.close()
    process.terminate.assert_called_once()


async def test_invalid_display_readiness_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(display_module.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    process = MagicMock(spec=asyncio.subprocess.Process)
    process.returncode = None
    process.stdout = asyncio.StreamReader()
    process.stdout.feed_eof()
    process.wait = AsyncMock(return_value=1)
    monkeypatch.setattr(
        display_module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    owner = BrowserDisplay()
    with pytest.raises(BrowserDisplayError, match="readiness"):
        await owner.start()
    process.terminate.assert_called_once()
    process.wait.assert_awaited_once()
    assert owner.process is None


async def test_missing_display_executable_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(display_module.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(
        display_module.asyncio,
        "create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError("sensitive native path")),
    )
    with pytest.raises(BrowserDisplayError, match="executable is unavailable") as error:
        await BrowserDisplay().start()
    assert "sensitive" not in str(error.value)


async def test_display_startup_timeout_kills_and_reaps_unresponsive_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(display_module.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    process = MagicMock(spec=asyncio.subprocess.Process)
    process.returncode = None
    process.stdout = MagicMock(spec=asyncio.StreamReader)
    process.stdout.readline = AsyncMock(side_effect=TimeoutError)
    process.wait = AsyncMock(side_effect=[TimeoutError, 0])
    monkeypatch.setattr(
        display_module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    owner = BrowserDisplay()
    with pytest.raises(BrowserDisplayError, match="startup timed out"):
        await owner.start()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.await_count == 2
    assert owner.process is None
    assert owner.environment is None


@pytest.mark.parametrize("display_failure", [True, False])
async def test_failed_browser_initialization_releases_owned_display(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, display_failure: bool
) -> None:
    manager = RunnerBrowserManager(
        workspace_root=tmp_path, proxy=None, input_key=BrowserInputKey()
    )
    start = AsyncMock(
        side_effect=(
            BrowserDisplayError("Synthetic failure") if display_failure else None
        ),
        return_value={"DISPLAY": ":143"},
    )
    close = AsyncMock()
    monkeypatch.setattr(manager.display, "start", start)
    monkeypatch.setattr(manager.display, "close", close)
    driver = MagicMock()
    driver.chromium.launch = AsyncMock(
        side_effect=browser_module.Error("Synthetic launch failure")
    )
    driver.stop = AsyncMock()
    entrypoint = MagicMock()
    entrypoint.start = AsyncMock(return_value=driver)
    monkeypatch.setattr(browser_module, "async_playwright", lambda: entrypoint)
    authority = BrowserAuthority("failed-session", str(tmp_path / "failed"))
    with pytest.raises(BrowserFailure, match="could not start|startup failed"):
        await manager.execute(BrowserOpenCommand(authority, None, None, None))
    assert manager.driver is None
    assert not manager.contexts
    assert manager.browser_environment is None
    close.assert_awaited_once()
    if display_failure:
        entrypoint.start.assert_not_awaited()
    else:
        driver.stop.assert_awaited_once()
    await manager.close()
