"""Build asset integrity and the startup no-download boundary."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from azents_runtime_control.browser_configuration import BrowserImplementation
from azents_runtime_control.browser_contract import BrowserAuthority, BrowserOpenCommand
from camoufox import async_api, fpgen_model
from playwright.async_api import Browser, BrowserContext, Playwright

from azents_runtime_runner import browser_camoufox
from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_camoufox import CamoufoxInstallationError
from azents_runtime_runner.browser_input import BrowserInputKey
from azents_runtime_runner.browser_install import (
    unpack_archive,
    verify_archive,
    verify_pairing,
)


def test_selected_sdk_and_upstream_asset_pins_match() -> None:
    verify_pairing()


def test_archive_hash_and_extraction_are_fail_closed(tmp_path: Path) -> None:
    archive = tmp_path / "fixture.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("properties.json", "{}")
    verify_archive(archive, hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(CamoufoxInstallationError, match="integrity"):
        verify_archive(archive, "0" * 64)
    destination = tmp_path / "distribution"
    unpack_archive(archive, destination)
    assert (destination / "properties.json").read_text() == "{}"
    with ZipFile(archive, "w") as output:
        output.writestr("../escape", "unsafe")
    with pytest.raises(CamoufoxInstallationError, match="Unsafe"):
        unpack_archive(archive, destination)
    assert not (tmp_path / "escape").exists()


async def test_missing_model_never_invokes_upstream_launcher_or_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "share" / "azents-browsers" / "camoufox" / "camoufox-bin"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"fixture")
    monkeypatch.setattr(browser_camoufox.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(fpgen_model, "is_pinned", lambda: False)
    launcher = AsyncMock(side_effect=AssertionError("Launcher must not fetch assets"))
    monkeypatch.setattr(async_api, "AsyncNewBrowser", launcher)
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.CAMOUFOX,
    )
    try:
        with pytest.raises(BrowserFailure, match="startup"):
            await manager.initialize()
        launcher.assert_not_awaited()
        assert manager.driver is None and manager.display.process is None
    finally:
        await manager.close()


async def test_camoufox_native_window_covers_the_fixed_input_viewport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch = async_api.AsyncNewBrowser

    async def small_generated_window(
        driver: Playwright, *, persistent_context: bool = False, **options: object
    ) -> Browser | BrowserContext:
        if persistent_context:
            config = options["config"]
            assert isinstance(config, dict)
            # Reproduce a sampled outer window narrower than the SDK plane.
            # Explicit product geometry takes precedence over generated values.
            options["config"] = {
                "window.outerWidth": 932,
                "window.outerHeight": 824,
                **config,
            }
            return await launch(
                driver, persistent_context=True, from_options=None, **options
            )
        return await launch(
            driver, persistent_context=False, from_options=None, **options
        )

    monkeypatch.setattr(async_api, "AsyncNewBrowser", small_generated_window)
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.CAMOUFOX,
    )
    try:
        actor = BrowserAuthority("window-fixture", str(tmp_path / "session"))
        opened = await manager.execute(BrowserOpenCommand(actor, None, None, None))
        assert opened.page is not None
        page = manager.tasks[opened.page.task_id].pages[opened.page.id].page
        await page.set_content(
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<button style="position:fixed;left:320px;top:90px" '
            "onclick=\"document.title='Delivered'\">Edge input</button>"
            '<button style="position:fixed;left:20px;top:500px" '
            "onclick=\"document.title='Bottom delivered'\">Bottom input</button>"
        )
        await page.get_by_role("button", name="Edge input").click(timeout=10000)
        assert await page.title() == "Delivered"
        await page.get_by_role("button", name="Bottom input").click(timeout=10000)
        assert await page.title() == "Bottom delivered"
        assert await page.evaluate(
            "() => outerWidth >= innerWidth && outerHeight >= innerHeight"
        )
    finally:
        await manager.close()
