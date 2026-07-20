"""Local development server.

Runs the Public API (:8010), Admin API (:8011), Engine Worker, and Scheduler together.
When ``AZ_TESTENV_API_ENABLED=1`` is set, it also runs the Testenv API (:8012).

run:
    uv run python src/cli/devserver.py
    uv run python src/cli/devserver.py --reload
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn
from azcommon.logging import RuntimeEnvironment, configure_logging_for_runtime
from fastapi import FastAPI

from azents.app import (
    create_admin_api_app,
    create_public_api_app,
    create_testenv_api_app,
    run_with_container,
)
from azents.core.config import Config
from azents.scheduler.service import SchedulerService
from azents.services.github_platform_system_setting.binding import (
    PlatformGitHubAppBindingMigration,
)
from azents.worker.worker import AgentWorker

_SRC_DIR = str(Path(__file__).resolve().parent.parent)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App factories imported by uvicorn reload mode.
# ---------------------------------------------------------------------------


def public_app() -> FastAPI:
    """Public API app factory."""
    config = Config.from_env()
    _enforce_production_testenv_guard(config)
    return create_public_api_app(config)


def admin_app() -> FastAPI:
    """Admin API app factory."""
    config = Config.from_env()
    _enforce_production_testenv_guard(config)
    return create_admin_api_app(config)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _enforce_production_testenv_guard(config: Config) -> None:
    """Fail startup when testenv flags are active outside local mode.

    Testenv devtools can inject broker events and lifecycle state. Enabling them
    outside local development is a security risk, so only ``runtime_env=LOCAL``
    is allowed.
    """
    testenv_flags: list[str] = []
    if config.testenv_api_enabled:
        testenv_flags.append("AZ_TESTENV_API_ENABLED")
    if testenv_flags and config.runtime_env != RuntimeEnvironment.LOCAL:
        raise SystemExit(
            "Testenv flags require AZ_RUNTIME_ENV=local: "
            f"{', '.join(testenv_flags)} set but runtime_env={config.runtime_env}"
        )


async def main(*, reload: bool = False) -> None:
    """Run the local development server."""
    config = Config.from_env()

    _enforce_production_testenv_guard(config)

    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
        configure_uvicorn=True,
        sentry_dsn=config.sentry_dsn,
    )

    # uvicorn reload imports factory functions by import string.
    # Add this file's directory to sys.path for reload imports.
    cli_dir = str(Path(__file__).resolve().parent)
    if cli_dir not in sys.path:
        sys.path.insert(0, cli_dir)

    public_server = uvicorn.Server(
        uvicorn.Config(
            "devserver:public_app",
            factory=True,
            host="0.0.0.0",
            port=8010,
            reload=reload,
            reload_dirs=[_SRC_DIR] if reload else [],
            log_config=None,  # noqa: S104 # development server
        )
    )
    admin_server = uvicorn.Server(
        uvicorn.Config(
            "devserver:admin_app",
            factory=True,
            host="0.0.0.0",
            port=8011,
            reload=reload,
            reload_dirs=[_SRC_DIR] if reload else [],
            log_config=None,  # noqa: S104 # development server
        )
    )
    # testenv_server receives an app instance directly because reload is unsupported.
    testenv_server: uvicorn.Server | None = None

    shutdown_event = asyncio.Event()

    def _on_shutdown(sig: signal.Signals) -> None:
        logger.info(
            "Received shutdown signal, draining",
            extra={"signal": sig.name},
        )
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_shutdown, sig)

    async with run_with_container(config) as container:
        migration = await container.solve(PlatformGitHubAppBindingMigration)
        await migration.run()
        worker = await container.solve(AgentWorker)
        scheduler = await container.solve(SchedulerService)

        if config.testenv_api_enabled:
            testenv_app_instance = create_testenv_api_app(config)
            testenv_server = uvicorn.Server(
                uvicorn.Config(
                    testenv_app_instance,
                    # Testenv API should only be reachable from the local machine.
                    host="127.0.0.1",
                    port=8012,
                    log_config=None,
                )
            )

        tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(public_server.serve()),
            asyncio.create_task(admin_server.serve()),
            asyncio.create_task(worker.run(shutdown_event=shutdown_event)),
            asyncio.create_task(scheduler.run(shutdown_event=shutdown_event)),
        ]

        if testenv_server is not None:
            tasks.append(asyncio.create_task(testenv_server.serve()))
            logger.info("Testenv API enabled on port 8012")

        async def _graceful_shutdown() -> None:
            """Propagate shutdown_event to all running services."""
            await shutdown_event.wait()
            logger.info("Shutting down all services")
            public_server.should_exit = True
            admin_server.should_exit = True
            if testenv_server is not None:
                testenv_server.should_exit = True

        tasks.append(asyncio.create_task(_graceful_shutdown()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Azents all-in-one dev server")
    parser.add_argument(
        "--reload", action="store_true", help="Auto-restart on code changes"
    )
    args = parser.parse_args()
    asyncio.run(main(reload=args.reload))
