"""Application-owned completion of an already-admitted one-use OAuth exchange."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.utils.appctx import AppContext
from azents.utils.logging import sanitized_exception_info

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class GitHubUserExchangeOperation:
    """Transient task ownership, not persisted credential or scheduling authority."""

    owner: "GitHubUserExchangeOwner" = field(repr=False)
    finalize: Callable[[], Awaitable[None]] = field(repr=False)
    task: asyncio.Task[object] | None = field(repr=False)
    cleanup_task: asyncio.Task[None] | None = field(repr=False)
    detached: bool
    observed: bool
    cleanup_observed: bool

    def detach(self) -> None:
        """Mark caller cancellation without performing database or provider I/O."""
        self.detached = True
        self.owner.operations.add(self)
        self.owner.loop.call_soon(self.owner.settled, self)


class GitHubUserExchangeOwner:
    """Retain admitted exchange/capture tasks through request cancellation."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.operations: set[GitHubUserExchangeOperation] = set()
        self.accepting = True

    async def run[T](
        self,
        call: Callable[[GitHubUserExchangeOperation], Awaitable[T]],
        finalize: Callable[[], Awaitable[None]],
    ) -> T:
        """Shield the existing sequence, while cancellation reaches its caller now."""
        if not self.accepting:
            raise RuntimeError("GitHub exchange owner is closing.")
        operation = GitHubUserExchangeOperation(
            owner=self,
            finalize=finalize,
            task=None,
            cleanup_task=None,
            detached=False,
            observed=False,
            cleanup_observed=False,
        )

        async def invoke() -> T:
            return await call(operation)

        task = asyncio.create_task(invoke())
        operation.task = task
        self.operations.add(operation)
        task.add_done_callback(lambda _: self.settled(operation))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            operation.detach()
            raise

    def settled(self, operation: GitHubUserExchangeOperation) -> None:
        """Observe completion and retain any required detached-caller cleanup."""
        task = operation.task
        if task is None or not task.done():
            return
        error = None if task.cancelled() else task.exception()
        if operation.detached:
            if error is not None and not operation.observed:
                logger.error(
                    "Detached GitHub authorization operation failed",
                    exc_info=sanitized_exception_info(
                        error, message="GitHub authorization completion failed."
                    ),
                )
                operation.observed = True
            if operation.cleanup_task is None:

                async def finalize() -> None:
                    await operation.finalize()

                cleanup = asyncio.create_task(finalize())
                operation.cleanup_task = cleanup
                cleanup.add_done_callback(lambda _: self.cleanup_settled(operation))
                return
            if not operation.cleanup_task.done():
                return
            self.cleanup_settled(operation)
            return
        self.operations.discard(operation)

    def cleanup_settled(self, operation: GitHubUserExchangeOperation) -> None:
        """Publish sanitized detached failures without swallowing their outcome."""
        if operation.cleanup_observed:
            return
        operation.cleanup_observed = True
        task = operation.cleanup_task
        if task is not None and not task.cancelled():
            error = task.exception()
            if error is not None:
                logger.error(
                    "Detached GitHub token cleanup failed",
                    exc_info=sanitized_exception_info(
                        error, message="GitHub token cleanup remains incomplete."
                    ),
                )
        self.operations.discard(operation)

    async def drain(self) -> None:
        """Finish admitted work before ordinary application DB resources close."""
        self.accepting = False
        while self.operations:
            tasks = [
                task
                for operation in tuple(self.operations)
                for task in (operation.task, operation.cleanup_task)
                if task is not None and not task.done()
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            for operation in tuple(self.operations):
                self.settled(operation)


async def get_github_user_exchange_owner(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> GitHubUserExchangeOwner:
    """Use the application's existing resource lifetime as the strong owner."""

    async def factory() -> AsyncIterator[GitHubUserExchangeOwner]:
        owner = GitHubUserExchangeOwner()
        appctx.add_pre_close_callback(owner.drain)
        yield owner

    return await appctx.get_variable("github_user_exchange_owner", factory)
