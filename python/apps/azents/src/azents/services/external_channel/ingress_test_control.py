"""One-shot deterministic controls reachable only through the Testenv API."""

import threading
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.utils.appctx import AppContext


class ExternalChannelIngressTestControl:
    """Hold bounded one-shot failure injection state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake_failure_session_id: str | None = None

    def fail_next_wake(self, *, session_id: str) -> None:
        """Arm one post-commit wake failure for the exact Session."""
        with self._lock:
            self._wake_failure_session_id = session_id

    def consume_wake_failure(self, *, session_id: str) -> bool:
        """Consume the exact armed wake failure once."""
        with self._lock:
            if self._wake_failure_session_id != session_id:
                return False
            self._wake_failure_session_id = None
            return True


async def get_external_channel_ingress_test_control(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> ExternalChannelIngressTestControl:
    """Return one AppContext-owned deterministic failure controller."""

    async def create() -> AsyncIterator[ExternalChannelIngressTestControl]:
        yield ExternalChannelIngressTestControl()

    return await appctx.get_variable(
        f"{__name__}.get_external_channel_ingress_test_control",
        create,
    )
