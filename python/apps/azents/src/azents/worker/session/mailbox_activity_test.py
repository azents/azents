"""Mailbox activity observer tests."""

import asyncio

import pytest

from azents.worker.session.mailbox_activity import MailboxActivityObserver


@pytest.mark.asyncio
async def test_observer_revision_coalesces_and_wakes_waiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = MailboxActivityObserver()
    revision = observer.current_revision()
    wait_started = asyncio.Event()
    original_wait_after = observer.wait_after

    async def wait_after(revision: int, timeout_seconds: float) -> bool:
        wait_started.set()
        return await original_wait_after(revision, timeout_seconds)

    monkeypatch.setattr(observer, "wait_after", wait_after)
    waiter = asyncio.create_task(observer.wait_after(revision, 1))
    await wait_started.wait()
    observer.notify()
    observer.notify()
    assert await waiter
    assert observer.current_revision() == revision + 2


@pytest.mark.asyncio
async def test_observer_timeout_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    observer = MailboxActivityObserver()
    assert not await observer.wait_after(observer.current_revision(), 0)
    wait_started = asyncio.Event()
    original_wait_after = observer.wait_after

    async def wait_after(revision: int, timeout_seconds: float) -> bool:
        wait_started.set()
        return await original_wait_after(revision, timeout_seconds)

    monkeypatch.setattr(observer, "wait_after", wait_after)
    waiter = asyncio.create_task(observer.wait_after(observer.current_revision(), 1))
    await wait_started.wait()
    observer.close()
    assert await waiter


@pytest.mark.asyncio
async def test_observer_waits_for_a_new_revision_after_prior_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = MailboxActivityObserver()
    observer.notify()
    revision = observer.current_revision()

    wait_started = asyncio.Event()
    original_wait_after = observer.wait_after

    async def wait_after(revision: int, timeout_seconds: float) -> bool:
        wait_started.set()
        return await original_wait_after(revision, timeout_seconds)

    monkeypatch.setattr(observer, "wait_after", wait_after)
    waiter = asyncio.create_task(observer.wait_after(revision, 1))
    await wait_started.wait()
    assert not waiter.done()

    observer.notify()
    assert await waiter
