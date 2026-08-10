"""Application root lifecycle tests."""

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from azents.app import (
    _create_container,
    create_public_api_app,
    run_with_container,
)
from azents.core.enums import JobRuntimeBackend
from azents.job_runtime.deps import (
    JobRuntimeBackendUnavailableError,
    get_job_runtime,
)
from azents.utils.appctx import AppContext


@pytest.mark.asyncio
async def test_external_fastapi_lifespan_keeps_shared_runtime_owned_by_root() -> None:
    """A co-located API lifespan does not close the devserver AppContext."""
    config = cast(Any, MagicMock(job_runtime_backend=JobRuntimeBackend.LOCAL))
    appctx = AppContext(config)
    container = _create_container(appctx)

    async with appctx, container:
        runtime = await container.solve(get_job_runtime)
        app = create_public_api_app(
            config,
            appctx=appctx,
            container=container,
        )

        async with app.router.lifespan_context(app):
            assert await container.solve(get_job_runtime) is runtime

        assert await container.solve(get_job_runtime) is runtime


@pytest.mark.asyncio
async def test_run_with_container_rejects_unavailable_temporal_at_startup() -> None:
    """Root startup fails before serving work when Temporal is selected."""
    config = cast(Any, MagicMock(job_runtime_backend=JobRuntimeBackend.TEMPORAL))

    with pytest.raises(
        JobRuntimeBackendUnavailableError,
        match="Temporal Job Runtime backend is not implemented",
    ):
        async with run_with_container(config):
            pytest.fail("Unavailable Runtime backend entered the application body")
