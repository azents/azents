"""Real headed Chromium checks for native identity and Session isolation."""

import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiohttp import web
from azents_runtime_control.browser_configuration import BrowserImplementation
from azents_runtime_control.browser_contract import BrowserAuthority, BrowserOpenCommand
from patchright.async_api import BrowserContext, Page

from azents_runtime_runner.browser import RunnerBrowserManager
from azents_runtime_runner.browser_input import BrowserInputKey


@pytest.fixture
async def fingerprint_site() -> AsyncIterator[str]:
    async def handler(request: web.Request) -> web.Response:
        # The first page script records values before product observation occurs.
        return (
            web.Response(
                text="""<!doctype html><script>
window.firstFingerprint = {
  webdriver: navigator.webdriver,
  ua: navigator.userAgent,
  appVersion: navigator.appVersion,
  platform: navigator.platform,
  brands: navigator.userAgentData?.brands ?? [],
  languages: navigator.languages
};
</script><iframe src='/frame'></iframe>""",
                content_type="text/html",
                headers={
                    "X-Seen-User-Agent": request.headers.get("User-Agent", "missing"),
                    "X-Seen-Client-Hint": request.headers.get("sec-ch-ua", "missing"),
                },
            )
            if request.path != "/frame"
            else web.Response(
                text="<script>window.firstWebdriver = navigator.webdriver;</script>",
                content_type="text/html",
            )
        )

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    server = web.TCPSite(runner, "127.0.0.1", 0)
    await server.start()
    address = runner.addresses[0]
    port = address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


async def test_native_identity_covers_navigation_frames_popups_and_session_isolation(
    tmp_path: Path, fingerprint_site: str
) -> None:
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.PATCHRIGHT,
    )
    authority = BrowserAuthority("session-a", str(tmp_path / "a"))
    try:
        opened = await manager.execute(
            BrowserOpenCommand(authority, None, fingerprint_site, None)
        )
        assert opened.page is not None
        context = manager.contexts[authority.session_id]
        page = manager.tasks[opened.page.task_id].pages[opened.page.id].page
        assert isinstance(context, BrowserContext)
        assert isinstance(page, Page)
        first = await page.evaluate("window.firstFingerprint", isolated_context=False)
        assert first["webdriver"] is False
        assert "HeadlessChrome" not in first["ua"]
        assert "HeadlessChrome" not in first["appVersion"]
        assert "HeadlessChrome" not in str(first["brands"])
        if "Linux" in first["ua"]:
            assert "Linux" in first["platform"]
        frame = page.frames[1]
        await frame.wait_for_load_state("load")
        assert (
            await frame.evaluate("window.firstWebdriver", isolated_context=False)
            is False
        )
        response = await page.reload(wait_until="load")
        assert response is not None
        headers = await response.all_headers()
        assert headers["x-seen-user-agent"] == first["ua"]
        assert "HeadlessChrome" not in headers["x-seen-client-hint"]
        assert "Chromium" in headers["x-seen-client-hint"]
        assert [
            {"brand": brand, "version": version}
            for brand, version in re.findall(
                r'"([^"]+)";v="([^"]+)"', headers["x-seen-client-hint"]
            )
        ] == first["brands"]
        async with context.expect_page() as popup_info:
            await page.evaluate("window.open(location.origin + '/popup')")
        popup = await popup_info.value
        await popup.wait_for_load_state()
        assert (
            await popup.evaluate(
                "window.firstFingerprint.webdriver", isolated_context=False
            )
            is False
        )
        assert (
            await popup.evaluate("window.firstFingerprint.ua", isolated_context=False)
            == first["ua"]
        )
        assert (
            await popup.evaluate(
                "window.firstFingerprint.appVersion", isolated_context=False
            )
            == first["appVersion"]
        )
        await context.add_cookies(
            [{"name": "session_secret", "value": "a", "url": fingerprint_site}]
        )
        await manager.execute(
            BrowserOpenCommand(
                BrowserAuthority("session-b", str(tmp_path / "b")),
                None,
                fingerprint_site,
                None,
            )
        )
        assert not await manager.contexts["session-b"].cookies()
    finally:
        await manager.close()
