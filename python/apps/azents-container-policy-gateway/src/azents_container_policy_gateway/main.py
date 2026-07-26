"""Container policy gateway process entrypoint."""

import argparse
import asyncio
import logging
import os
from pathlib import Path

from aiohttp import web

from azents_container_policy_gateway.config import gateway_config_from_env
from azents_container_policy_gateway.engine_client import EngineClient
from azents_container_policy_gateway.server import (
    check_readiness,
    create_application,
)

_LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Run the gateway server or one exact readiness check."""
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("serve")
    check = subcommands.add_parser("check-ready")
    check.add_argument("--socket", required=True)
    check.add_argument("--runtime-id", required=True)
    check.add_argument("--desired-generation", required=True, type=int)
    check.add_argument("--snapshot-id", required=True)
    check.add_argument("--policy-digest", required=True)
    args = parser.parse_args()
    if args.command == "check-ready":
        ready = asyncio.run(
            check_readiness(
                socket_path=args.socket,
                runtime_id=args.runtime_id,
                desired_generation=args.desired_generation,
                snapshot_id=args.snapshot_id,
                policy_digest=args.policy_digest,
            )
        )
        raise SystemExit(0 if ready else 1)
    asyncio.run(run_gateway())


async def run_gateway() -> None:
    """Validate policy, then bind the public Unix socket."""
    logging.basicConfig(
        level=os.environ.get("AZ_LOG_LEVEL", "INFO").upper(),
    )
    config = gateway_config_from_env()
    engine = EngineClient(str(config.private_engine_socket_path))
    application = create_application(
        config,
        engine_execute=engine.execute,
        engine_compatible=engine.compatible,
        engine_container_usage=engine.container_usage,
        engine_resource_owned=engine.resource_owned,
    )
    runner = create_application_runner(application)
    await runner.setup()
    socket_path = config.public_socket_path
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    site = web.UnixSite(runner, str(socket_path))
    try:
        await site.start()
        socket_path.chmod(0o660)
        _LOGGER.info(
            "Container policy gateway ready",
            extra={
                "runtime_id": config.runtime_id,
                "desired_generation": config.desired_generation,
                "policy_digest": config.policy_digest,
            },
        )
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await engine.close()
        Path(socket_path).unlink(missing_ok=True)


def create_application_runner(application: web.Application) -> web.AppRunner:
    """Create the production runner with disconnect cancellation enabled."""
    return web.AppRunner(
        application,
        access_log=None,
        handler_cancellation=True,
    )


if __name__ == "__main__":
    main()
