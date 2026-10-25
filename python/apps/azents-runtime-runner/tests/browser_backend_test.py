"""Packaged browser selection, native profile separation and Firefox viewer checks."""

import asyncio
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiohttp import web
from azents_runtime_control.browser_configuration import BrowserImplementation
from azents_runtime_control.browser_contract import (
    BrowserAuthority,
    BrowserOpenCommand,
)
from browser_test import authority, observe, site, target
from browser_viewer_test import Budget, Transport, scope, stop

from azents_runtime_runner import browser_camoufox
from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_camoufox import (
    CamoufoxInstallationError,
    camoufox_executable,
)
from azents_runtime_runner.browser_input import BrowserInputKey
from azents_runtime_runner.browser_viewer import RunnerBrowserViewer

# Imported pytest fixtures retain their original local HTTP-only implementation.
__all__ = ["site"]


def test_camoufox_installation_is_closed_and_platform_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_camoufox.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(browser_camoufox.sys, "platform", "linux")
    with pytest.raises(CamoufoxInstallationError, match="unavailable"):
        camoufox_executable()
    binary = tmp_path / "share" / "azents-browsers" / "camoufox" / "camoufox-bin"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"fixture")
    assert camoufox_executable() == binary
    monkeypatch.setattr(browser_camoufox.sys, "platform", "unsupported-fixture")
    with pytest.raises(CamoufoxInstallationError, match="unsupported"):
        camoufox_executable()


async def test_missing_camoufox_does_not_fallback_or_leave_display(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(browser_camoufox.sys, "prefix", str(tmp_path))
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.CAMOUFOX,
    )
    try:
        with pytest.raises(BrowserFailure, match="startup"):
            await manager.initialize()
        assert manager.implementation is BrowserImplementation.CAMOUFOX
        assert manager.driver is None and not manager.contexts
        assert manager.display.process is None
    finally:
        await manager.close()


async def test_native_backends_keep_distinct_session_profiles(
    tmp_path: Path, site: str
) -> None:
    actor = authority(tmp_path)
    other = BrowserAuthority("other-session", str(tmp_path / "other"))
    for index, implementation in enumerate(
        (
            BrowserImplementation.PATCHRIGHT,
            BrowserImplementation.CAMOUFOX,
            BrowserImplementation.PATCHRIGHT,
            BrowserImplementation.CAMOUFOX,
        )
    ):
        manager = RunnerBrowserManager(
            workspace_root=tmp_path,
            proxy=None,
            input_key=BrowserInputKey(),
            implementation=implementation,
        )
        try:
            opened = await manager.execute(BrowserOpenCommand(actor, None, site, None))
            own = manager.contexts[actor.session_id]
            cookies = await own.cookies(site)
            names = {cookie["name"] for cookie in cookies}
            if index >= 2:
                assert implementation.value in names
            opposite = (
                "camoufox"
                if implementation is BrowserImplementation.PATCHRIGHT
                else "patchright"
            )
            assert opposite not in names
            await own.add_cookies(
                [
                    {
                        "name": implementation.value,
                        "value": "sentinel",
                        "url": site,
                        "expires": datetime.now(UTC).timestamp() + 3600,
                    }
                ]
            )
            dom = await observe(manager, actor, target(opened))
            assert dom.refs
            image = await observe(manager, actor, target(opened), "image")
            assert image.capture is not None
            assert Path(image.capture.path).read_bytes().startswith(b"\x89PNG")
            await manager.execute(BrowserOpenCommand(other, None, site, None))
            assert not await manager.contexts[other.session_id].cookies(site)
        finally:
            await manager.close()


async def test_camoufox_viewer_streams_current_frame_and_editables(
    tmp_path: Path, site: str
) -> None:
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.CAMOUFOX,
    )
    manager.bind_runtime("runtime", lambda: 7)
    budget = Budget()
    viewer = RunnerBrowserViewer(manager, budget)
    transport = Transport()
    running = None
    try:
        actor = await scope(manager, tmp_path, site)
        running = asyncio.create_task(
            viewer.run(actor, transport.receive, transport.send)
        )
        frame = await transport.frame()
        assert frame.source.width > 0 and frame.source.height > 0
        assert frame.editables
        assert viewer.sources[actor.page_id].page.popup_selection is None
    finally:
        if running is not None:
            await stop(running, transport)
        await viewer.close()
        await manager.close()
    assert budget.bytes == 0


@pytest.mark.parametrize("implementation", tuple(BrowserImplementation))
async def test_configured_proxy_is_authoritative_even_for_loopback(
    tmp_path: Path, implementation: BrowserImplementation
) -> None:
    seen: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append(request.raw_path)
        return web.Response(
            text="<title>Authoritative proxy route</title>", content_type="text/html"
        )

    application = web.Application()
    application.router.add_route("*", "/{path:.*}", handler)
    proxy = web.AppRunner(application)
    await proxy.setup()
    server = web.TCPSite(proxy, "127.0.0.1", 0)
    await server.start()
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=f"http://127.0.0.1:{proxy.addresses[0][1]}",
        input_key=BrowserInputKey(),
        implementation=implementation,
    )
    try:
        # This owned port is bound but not listening; a direct browser request
        # cannot succeed. Only the configured proxy can produce the sentinel.
        with socket.socket() as unreachable:
            unreachable.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{unreachable.getsockname()[1]}/fixture"
            opened = await manager.execute(
                BrowserOpenCommand(authority(tmp_path), None, url, None)
            )
            assert opened.page is not None
            assert opened.page.title == "Authoritative proxy route"
            assert url in seen
    finally:
        await manager.close()
        await proxy.cleanup()
