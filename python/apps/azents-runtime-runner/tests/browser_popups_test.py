"""Deterministic private popup correlation lifetime checks without browser effects."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import CDPSession, Page

from azents_runtime_runner.browser_popups import BrowserPopupTracker


@pytest.mark.parametrize(
    "invalidation", ["navigation", "owner", "destroyed", "other-owner"]
)
async def test_consumed_popup_cannot_survive_invalidation_during_detach(
    invalidation: str,
) -> None:
    page = MagicMock(spec=Page)
    page.is_closed.return_value = False
    session = MagicMock(spec=CDPSession)
    session.send = AsyncMock(return_value={"targetInfo": {"targetId": "child"}})
    entered, release = asyncio.Event(), asyncio.Event()

    async def detach() -> None:
        entered.set()
        await release.wait()

    session.detach = AsyncMock(side_effect=detach)
    page.context.new_cdp_session = AsyncMock(return_value=session)
    tracker = BrowserPopupTracker(page, lambda: "owner")
    tracker.target_id = "source"
    tracker.created({"targetInfo": {"targetId": "child", "openerId": "source"}})
    consuming = asyncio.create_task(tracker.consume(page))
    async with asyncio.timeout(5):
        await entered.wait()
        assert not tracker.pending and len(tracker.consuming) == 1
        match invalidation:
            case "navigation":
                tracker.clear()
            case "owner":
                tracker.discard("owner")
            case "destroyed":
                tracker.destroyed({"targetId": "child"})
            case "other-owner":
                tracker.discard("another-attachment")
        release.set()
        assert await consuming == ("owner" if invalidation == "other-owner" else None)
    assert not tracker.consuming


def test_popup_records_are_bounded_and_exactly_opener_scoped() -> None:
    page = MagicMock(spec=Page)
    tracker = BrowserPopupTracker(page, lambda: "owner")
    tracker.target_id = "source"
    tracker.created({"targetInfo": {"targetId": "foreign", "openerId": "other"}})
    assert not tracker.pending
    for number in range(40):
        tracker.created({"targetInfo": {"targetId": str(number), "openerId": "source"}})
    assert len(tracker.pending) == 16
    tracker.discard("another-attachment")
    assert len(tracker.pending) == 16
    tracker.discard("owner")
    assert not tracker.pending
