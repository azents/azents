"""Documented Camoufox launcher boundary with explicit native SDK narrowing."""

import os
import sys
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Playwright

from azents_runtime_runner.browser_mobile import (
    FIREFOX_MOBILE_USER_AGENT,
    MOBILE_HEIGHT,
    MOBILE_WIDTH,
)


class CamoufoxInstallationError(RuntimeError):
    """The immutable browser distribution is missing or unsupported."""


def require_camoufox_model() -> None:
    """Reject missing model assets before the upstream launcher can fetch them."""
    from camoufox.fpgen_model import is_pinned  # noqa: PLC0415

    if os.environ.get("FPGEN_MODEL_URL") or not is_pinned():
        raise CamoufoxInstallationError("Packaged Camoufox model is unavailable")


def camoufox_executable() -> Path:
    """Resolve packaged assets, without invoking an upstream auto-downloader."""
    root = Path(sys.prefix) / "share" / "azents-browsers" / "camoufox"
    match sys.platform:
        case "linux":
            path = root / "camoufox-bin"
        case "darwin":
            path = root / "Camoufox.app" / "Contents" / "MacOS" / "camoufox"
        case "win32":
            path = root / "camoufox.exe"
        case _:
            raise CamoufoxInstallationError("Camoufox platform is unsupported")
    if not path.is_file():
        raise CamoufoxInstallationError("Packaged Camoufox browser is unavailable")
    return path


async def probe_camoufox(
    driver: Playwright,
    environment: dict[str, str | float] | None,
    proxy: dict[str, str] | None,
) -> None:
    """Establish native browser availability without opening a Session profile."""
    executable = str(camoufox_executable())
    require_camoufox_model()
    # Camoufox validates its platform at import. Keep default startup independent.
    from camoufox.addons import DefaultAddons  # noqa: PLC0415
    from camoufox.async_api import AsyncNewBrowser  # noqa: PLC0415

    browser = await AsyncNewBrowser(
        driver,
        executable_path=executable,
        headless=False,
        humanize=False,
        exclude_addons=list(DefaultAddons),
        env=environment,
        proxy=proxy,
        firefox_user_prefs=_proxy_preferences(proxy),
    )
    try:
        if not isinstance(browser, Browser):
            raise RuntimeError("Camoufox availability probe returned a context")
    finally:
        await browser.close()


async def open_camoufox_context(
    driver: Playwright,
    *,
    profile: Path,
    environment: dict[str, str | float] | None,
    proxy: dict[str, str] | None,
) -> BrowserContext:
    """Launch the packaged paired browser with the Runner's exact profile/network."""
    executable = str(camoufox_executable())
    require_camoufox_model()
    # Camoufox validates its platform at import. Keep default startup independent.
    from camoufox.addons import DefaultAddons  # noqa: PLC0415
    from camoufox.async_api import AsyncNewBrowser  # noqa: PLC0415

    context = await AsyncNewBrowser(
        driver,
        executable_path=executable,
        persistent_context=True,
        user_data_dir=str(profile),
        headless=False,
        humanize=False,
        exclude_addons=list(DefaultAddons),
        env=environment,
        proxy=proxy,
        firefox_user_prefs={
            **(_proxy_preferences(proxy) or {}),
            "dom.meta-viewport.enabled": True,
            "dom.w3c_touch_events.enabled": 1,
            "ui.primaryPointerCapabilities": 1,
            "ui.allPointerCapabilities": 1,
        },
        has_touch=True,
        device_scale_factor=1,
        accept_downloads=True,
        # Keep the native window large enough for the fixed SDK input plane.
        # A generated smaller outer window clips otherwise valid native clicks.
        config={
            "window.outerWidth": MOBILE_WIDTH,
            "window.outerHeight": MOBILE_HEIGHT + 100,
            "window.innerWidth": MOBILE_WIDTH,
            "window.innerHeight": MOBILE_HEIGHT,
            "screen.width": MOBILE_WIDTH,
            "screen.height": MOBILE_HEIGHT,
            "screen.availWidth": MOBILE_WIDTH,
            "screen.availHeight": MOBILE_HEIGHT,
            "navigator.userAgent": FIREFOX_MOBILE_USER_AGENT,
            "navigator.platform": "Linux armv8l",
            "navigator.maxTouchPoints": 5,
        },
        viewport={"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT},
    )
    if not isinstance(context, BrowserContext):
        await context.close()
        raise RuntimeError("Camoufox persistent launch did not return a context")
    return context


def _proxy_preferences(proxy: dict[str, str] | None) -> dict[str, str | bool] | None:
    if proxy is None:
        return None
    # Firefox exempts loopback even with an explicit proxy. The Runtime policy
    # proxy is authoritative for those destinations too, as it is for Chromium.
    return {
        "network.proxy.allow_hijacking_localhost": True,
        "network.proxy.no_proxies_on": "",
    }
