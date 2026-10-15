"""Content-free Browser diagnostics retain the caught exception's origin."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error, Page

from azents_runtime_runner.browser import BrowserFailure, _Page
from azents_runtime_runner.browser_viewer import BrowserFrameBudget, _LatestPage


async def test_capture_failure_keeps_traceback_without_sdk_content(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _Page("page", MagicMock(spec=Page), None, None, None)
    source = _LatestPage(page, MagicMock(spec=BrowserFrameBudget))
    sensitive = "synthetic-private-url-and-page-content"
    failure = Error(sensitive)
    monkeypatch.setattr(source.popups, "start", AsyncMock(side_effect=failure))

    await source.capture()

    assert source.failed
    record = next(
        r for r in caplog.records if r.message == "Browser live capture stopped"
    )
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], BrowserFailure)
    assert record.exc_info[2] is not None
    assert record.exc_info[1].__context__ is None
    assert record.exc_info[1].__cause__ is None
    assert sensitive not in caplog.text
    assert "Browser live capture failed" in caplog.text
