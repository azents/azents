"""Tests for ChatGPT OAuth constants and headers."""

import os
import subprocess
import sys
from pathlib import Path


def test_build_headers_without_installed_package_metadata() -> None:
    """Build headers when Azents is loaded directly from its source tree."""
    source_root = Path(__file__).parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    script = """
from importlib.metadata import PackageNotFoundError, version

try:
    version("azents")
except PackageNotFoundError:
    pass
else:
    raise AssertionError("azents package metadata must be unavailable")

from azents.core.chatgpt_oauth import build_chatgpt_oauth_headers

assert build_chatgpt_oauth_headers(account_id="account-id") == {
    "originator": "azents",
    "user-agent": "azents/0.1.0",
    "ChatGPT-Account-Id": "account-id",
}
"""

    subprocess.run(
        [sys.executable, "-S", "-c", script],
        check=True,
        env=env,
    )
