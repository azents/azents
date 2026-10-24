"""Build asset integrity and the startup no-download boundary."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from azents_runtime_control.browser_configuration import BrowserImplementation
from camoufox import async_api, fpgen_model

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
