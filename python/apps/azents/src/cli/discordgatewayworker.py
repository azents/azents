"""Standalone Discord Gateway Worker."""

import asyncio
import logging
import signal

from azcommon.logging import configure_logging_for_runtime

from azents.app import run_with_container
from azents.core.config import Config
from azents.services.external_channel.discord_gateway_manager import (
    DiscordGatewayManagerService,
)
from azents.worker.deps import get_health_server

logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the dedicated lease-fenced Discord Gateway Worker."""
    config = Config.from_env()
    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
        sentry_dsn=config.sentry_dsn,
    )
    shutdown_event = asyncio.Event()
    async with run_with_container(config) as container:
        manager = await container.solve(DiscordGatewayManagerService)
        health = await container.solve(get_health_server)

        def _on_shutdown(sig: signal.Signals) -> None:
            """Stop readiness before releasing owned Gateway sessions."""
            logger.info(
                "Received Discord Gateway shutdown signal",
                extra={"signal": sig.name},
            )
            health.mark_shutting_down()
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_shutdown, sig)
        await health.start()
        try:
            await manager.run(shutdown_event)
        finally:
            await health.stop()


if __name__ == "__main__":
    asyncio.run(main())
