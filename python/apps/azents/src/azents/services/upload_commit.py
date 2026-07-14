"""Recovery helpers for upload-then-metadata-commit services."""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from azents.utils.task_recovery import run_bounded_cancellation_safe

_T = TypeVar("_T")


class UploadedMetadataIdentityMismatch(RuntimeError):
    """A preallocated metadata ID resolved to an unexpected durable row."""


async def reconcile_uploaded_metadata(
    *,
    lookup: Callable[[], Awaitable[_T | None]],
    matches_expected_identity: Callable[[_T], bool],
    resource_kind: str,
    resource_id: str,
    compensate_if_absent: Callable[[], Awaitable[None]] | None = None,
) -> _T | None:
    """Resolve an ambiguous commit and compensate a proven rollback.

    The lookup, identity check, and optional absence compensation form one
    retained recovery operation. A freshly cancelled caller therefore exits
    immediately without abandoning cleanup after a later proven rollback.
    """

    async def reconcile() -> _T | None:
        row = await lookup()
        if row is None:
            if compensate_if_absent is not None:
                await compensate_if_absent()
            return None
        if not matches_expected_identity(row):
            raise UploadedMetadataIdentityMismatch(
                f"{resource_kind} {resource_id} resolved to unexpected metadata"
            )
        return row

    return await run_bounded_cancellation_safe(reconcile)
