"""Job Runtime dependency composition."""

from collections.abc import AsyncIterator
from typing import Annotated

from azcommon import di
from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx, get_config
from azents.core.enums import JobRuntimeBackend
from azents.job_runtime.local import LocalJobRuntime
from azents.job_runtime.registry import get_job_handler_registry
from azents.job_runtime.types import JobRuntime
from azents.utils.appctx import AppContext

_LOCAL_MAX_CONCURRENCY = 16
_LOCAL_CANCELLATION_GRACE_SECONDS = 5.0


class JobRuntimeBackendUnavailableError(RuntimeError):
    """Raised when configuration selects an unavailable Runtime backend."""


async def get_job_runtime(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    config: Annotated[Config, Depends(get_config)],
    container: Annotated[di.Container, Depends(di.get_container)],
) -> JobRuntime:
    """Return one AppContext-owned Job Runtime for the current process."""

    async def create() -> AsyncIterator[JobRuntime]:
        if config.job_runtime_backend is JobRuntimeBackend.TEMPORAL:
            raise JobRuntimeBackendUnavailableError(
                "The Temporal Job Runtime backend is not implemented."
            )
        runtime = LocalJobRuntime(
            handlers=get_job_handler_registry(),
            container_factory=container.copy,
            max_concurrency=_LOCAL_MAX_CONCURRENCY,
            cancellation_grace_seconds=_LOCAL_CANCELLATION_GRACE_SECONDS,
        )
        appctx.add_pre_close_callback(runtime.close)
        try:
            yield runtime
        finally:
            await runtime.close()

    return await appctx.get_variable(f"{__name__}.get_job_runtime", create)
