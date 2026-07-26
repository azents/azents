"""Mailbox activity observer tests."""

import asyncio

import pytest

from azents.worker.session.mailbox_activity import MailboxActivityObserver


@pytest.mark.asyncio
async def test_observer_revision_coalesces_and_wakes_waiters() -> None:
    observer = MailboxActivityObserver()
    revision = observer.current_revision()
    waiter = asyncio.create_task(observer.wait_after(revision, 1))
    await asyncio.sleep(0)
    observer.notify()
    observer.notify()
    assert await waiter
    assert observer.current_revision() == revision + 2


@pytest.mark.asyncio
async def test_observer_timeout_and_close() -> None:
    observer = MailboxActivityObserver()
    assert not await observer.wait_after(observer.current_revision(), 0)
    waiter = asyncio.create_task(observer.wait_after(observer.current_revision(), 1))
    await asyncio.sleep(0)
    observer.close()
    assert await waiter


@pytest.mark.asyncio
async def test_observer_waits_for_a_new_revision_after_prior_notification() -> None:
    observer = MailboxActivityObserver()
    observer.notify()
    revision = observer.current_revision()

    waiter = asyncio.create_task(observer.wait_after(revision, 1))
    await asyncio.sleep(0)
    assert not waiter.done()

    observer.notify()
    assert await waiter
