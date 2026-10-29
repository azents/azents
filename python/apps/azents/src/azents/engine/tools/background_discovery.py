"""Expected discovery errors and explicitly observed background task faults."""

import asyncio
import logging
from collections.abc import Callable

import httpx
import httpx2
from anyio import BrokenResourceError, ClosedResourceError, EndOfStream
from botocore.exceptions import BotoCoreError, ClientError
from google.auth.exceptions import GoogleAuthError
from mcp import MCPError

from azents.utils.logging import sanitized_exception_info

# SDK/MCP failures are expected; arbitrary ValueError/TypeError and invariant
# failures from injected projection or credential code must remain unexpected.
DISCOVERY_ERRORS = (
    httpx.HTTPError,
    httpx2.HTTPError,
    MCPError,
    OSError,
    BrokenResourceError,
    ClosedResourceError,
    EndOfStream,
    BotoCoreError,
    ClientError,
    GoogleAuthError,
)


async def cancel_owned_discovery(task: asyncio.Task[None] | None) -> None:
    """Join an owned task without confusing its cancellation with the caller's."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        (result,) = await asyncio.gather(task, return_exceptions=True)
    except asyncio.CancelledError as cancellation:
        # gather waits for the child but prioritizes cancellation over its error.
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                raise error from cancellation
        raise
    if isinstance(result, BaseException) and not isinstance(
        result, asyncio.CancelledError
    ):
        raise result


def require_expected_discovery_failure(error: BaseException) -> None:
    """Preserve unrelated siblings of a mixed error group."""
    if isinstance(error, BaseExceptionGroup):
        _, remainder = error.split(DISCOVERY_ERRORS)
        if remainder is not None:
            raise error
    elif not isinstance(error, DISCOVERY_ERRORS):
        raise error


def observe_discovery_failure(
    logger: logging.Logger,
    *,
    toolkit: str,
) -> Callable[[asyncio.Task[None]], None]:
    """Create a one-time unexpected-task error observer."""

    def observe(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Unexpected Toolkit discovery failure",
                extra={"toolkit": toolkit, "error_type": type(error).__name__},
                exc_info=sanitized_exception_info(
                    error, message="Unexpected Toolkit discovery failure"
                ),
            )

    return observe
