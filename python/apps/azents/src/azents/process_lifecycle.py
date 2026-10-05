"""Shared dependency-injection lifecycle for non-HTTP processes."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from azcommon import di

from azents.core.config import Config
from azents.core.deps import AppContextBinding, get_appctx
from azents.job_runtime.deps import get_job_runtime
from azents.runtime import deps as runtime_deps
from azents.services.runtime_terminal.invalidation import (
    get_runtime_terminal_invalidation_publisher,
)
from azents.services.terminal_policy.invalidation import (
    get_terminal_policy_invalidation_publisher,
)
from azents.utils.appctx import AppContext


@asynccontextmanager
async def run_with_container(config: Config) -> AsyncIterator[di.Container]:
    """Run one non-HTTP process with its configured dependency container."""
    if config.session_broker_backend == "memory":
        raise RuntimeError(
            "Memory Session broker requires the co-located all-in-one process"
        )
    async with run_co_located_container(config) as container:
        yield container


@asynccontextmanager
async def run_co_located_container(config: Config) -> AsyncIterator[di.Container]:
    """Own shared dependencies for API, Worker and Scheduler in one process."""
    async with (
        AppContext(config) as appctx,
        create_container(appctx) as container,
    ):
        await preload_process_services(container)
        yield container


async def preload_process_services(container: di.Container) -> None:
    """Resolve process singletons whose configuration must fail at startup."""
    await container.solve(get_job_runtime)


def create_container(appctx: AppContext[Config]) -> di.Container:
    """Create the application dependency container."""
    overrides: di.DependencyOverrides = {
        get_appctx: AppContextBinding(appctx),
        get_runtime_terminal_invalidation_publisher: (
            runtime_deps.get_runtime_terminal_invalidation_publisher
        ),
        get_terminal_policy_invalidation_publisher: (
            runtime_deps.get_runtime_terminal_policy_invalidation_publisher
        ),
    }
    return di.Container(dependency_overrides=overrides)
