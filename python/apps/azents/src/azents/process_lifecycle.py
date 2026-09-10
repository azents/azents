"""Shared dependency-injection lifecycle for non-HTTP processes."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from azcommon import di

from azents.core.config import Config
from azents.core.deps import get_appctx
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
        get_appctx: lambda: appctx,
        get_runtime_terminal_invalidation_publisher: (
            runtime_deps.get_runtime_terminal_invalidation_publisher
        ),
        get_terminal_policy_invalidation_publisher: (
            runtime_deps.get_runtime_terminal_policy_invalidation_publisher
        ),
    }
    return di.Container(dependency_overrides=overrides)
