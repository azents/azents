"""Standalone Engine Worker.

Runs the worker process used in production.

run: uv run python src/cli/engineworker.py
"""

import asyncio
import logging
import signal

from azcommon.logging import configure_logging_for_runtime

from azents.app import run_with_container
from azents.core.config import Config
from azents.services.github_platform_system_setting.binding import (
    PlatformGitHubAppBindingMigration,
)
from azents.worker.deps import get_health_server
from azents.worker.worker import AgentWorker

logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the standalone Engine Worker."""
    config = Config.from_env()

    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
        sentry_dsn=config.sentry_dsn,
    )

    shutdown_event = asyncio.Event()

    async with run_with_container(config) as container:
        migration = await container.solve(PlatformGitHubAppBindingMigration)
        await migration.run()
        worker = await container.solve(AgentWorker)
        health = await container.solve(get_health_server)

        def _on_shutdown(sig: signal.Signals) -> None:
            """Switch the readiness probe to 503 immediately on SIGTERM/SIGINT."""
            logger.info(
                "Received shutdown signal, draining",
                extra={"signal": sig.name},
            )
            health.mark_shutting_down()
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_shutdown, sig)

        await health.start()
        try:
            await worker.run(shutdown_event=shutdown_event)
        finally:
            await health.stop()


if __name__ == "__main__":
    asyncio.run(main())
