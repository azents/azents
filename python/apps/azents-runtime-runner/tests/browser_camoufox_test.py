"""Camoufox adapter options preserve the owned launch and authority boundary."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import Browser, BrowserContext, Playwright

from azents_runtime_runner import browser_camoufox
from azents_runtime_runner.browser_mobile import (
    MOBILE_DEVICE_SCALE,
    MOBILE_HEIGHT,
    MOBILE_WIDTH,
)


async def test_camoufox_launches_use_explicit_canvas_policy_and_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from camoufox import async_api  # noqa: PLC0415

    binary = tmp_path / "camoufox-bin"
    monkeypatch.setattr(browser_camoufox, "camoufox_executable", lambda: binary)
    monkeypatch.setattr(browser_camoufox, "require_camoufox_model", lambda: None)
    browser = Mock(spec=Browser)
    browser.close = AsyncMock()
    context = Mock(spec=BrowserContext)
    launch = AsyncMock(side_effect=[browser, context])
    monkeypatch.setattr(async_api, "AsyncNewBrowser", launch)
    driver = Mock(spec=Playwright)
    environment: dict[str, str | float] = {"DISPLAY": ":owned"}
    proxy = {"server": "http://policy-proxy:8080"}
    profile = tmp_path / "session-profile"

    await browser_camoufox.probe_camoufox(driver, environment, proxy)
    browser.close.assert_awaited_once()
    opened = await browser_camoufox.open_camoufox_context(
        driver, profile=profile, environment=environment, proxy=proxy
    )
    assert opened is context
    assert launch.await_count == 2
    for call in launch.await_args_list:
        assert call.args == (driver,)
        assert call.kwargs["executable_path"] == str(binary)
        assert call.kwargs["canvas_noise"] is True
        assert call.kwargs["headless"] is False
        assert call.kwargs["env"] == environment
        assert call.kwargs["proxy"] == proxy
        assert call.kwargs["firefox_user_prefs"]["network.proxy.no_proxies_on"] == ""
        assert (
            call.kwargs["firefox_user_prefs"]["network.proxy.allow_hijacking_localhost"]
            is True
        )
    persistent = launch.await_args_list[1].kwargs
    assert persistent["persistent_context"] is True
    assert persistent["user_data_dir"] == str(profile)
    assert persistent["device_scale_factor"] == MOBILE_DEVICE_SCALE
    assert persistent["viewport"] == {
        "width": MOBILE_WIDTH,
        "height": MOBILE_HEIGHT,
    }
    assert "window.devicePixelRatio" not in persistent["config"]
