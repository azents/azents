"""Reduce explicit automation markers without changing browser authority."""

from playwright.async_api import BrowserContext
from playwright_stealth import Stealth

# Keep the managed headless transport and sandbox; suppress its public marker.
BROWSER_ARGS = ["--disable-blink-features=AutomationControlled"]
BROWSER_IGNORE_DEFAULT_ARGS = ["--enable-automation"]
# Use the installed full Chromium's new headless mode, not headless shell.
BROWSER_CHANNEL = "chromium"


async def prepare_browser_stealth(context: BrowserContext, user_agent: str) -> None:
    """Install context-wide scripts before site navigation."""
    stealth = Stealth(
        # Preserve the native OS, locale and GPU rather than spoofing Windows.
        navigator_platform=False,
        navigator_languages=False,
        # Upstream accepts None for disabled overrides but annotates them narrowly.
        navigator_platform_override=None,  # ty: ignore[invalid-argument-type]
        navigator_languages_override=None,  # ty: ignore[invalid-argument-type]
        webgl_vendor=False,
        navigator_user_agent_override=user_agent,
    )
    # The package's use_async wrapper does not wrap launch_persistent_context.
    # Explicit context installation also covers subsequent tabs and popups.
    await stealth.apply_stealth_async(context)
