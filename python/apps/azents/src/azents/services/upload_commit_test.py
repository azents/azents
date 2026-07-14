"""Upload metadata reconciliation tests."""

import asyncio

import pytest

from azents.services.upload_commit import (
    UploadedMetadataIdentityMismatch,
    reconcile_uploaded_metadata,
)


async def test_reconcile_rejects_preallocated_identity_collision() -> None:
    """A present but unexpected row is not classified as safe-to-delete absence."""
    with pytest.raises(UploadedMetadataIdentityMismatch):
        await reconcile_uploaded_metadata(
            lookup=lambda: _value("unexpected"),
            matches_expected_identity=lambda value: value == "expected",
            resource_kind="TestFile",
            resource_id="file-1",
        )


async def test_reconcile_absence_cleanup_survives_fresh_cancellation() -> None:
    """A detached reconciliation still compensates a proven rollback."""
    lookup_started = asyncio.Event()
    release_lookup = asyncio.Event()
    cleanup_completed = asyncio.Event()

    async def lookup() -> None:
        lookup_started.set()
        await release_lookup.wait()

    async def compensate() -> None:
        cleanup_completed.set()

    task = asyncio.create_task(
        reconcile_uploaded_metadata(
            lookup=lookup,
            matches_expected_identity=lambda _value: True,
            resource_kind="TestFile",
            resource_id="file-1",
            compensate_if_absent=compensate,
        )
    )
    await asyncio.wait_for(lookup_started.wait(), timeout=1)
    task.cancel("fresh cancellation")

    with pytest.raises(asyncio.CancelledError, match="fresh cancellation"):
        await asyncio.wait_for(task, timeout=0.1)
    assert not cleanup_completed.is_set()

    release_lookup.set()
    await asyncio.wait_for(cleanup_completed.wait(), timeout=1)


async def _value(value: str) -> str:
    """Return a value through an awaitable test lookup."""
    return value
