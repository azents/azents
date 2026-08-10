"""Read-only External Channel ingress operator CLI."""

import asyncio
import json
from typing import Annotated

import typer
from azcommon.logging import configure_logging_for_runtime

from azents.app import run_with_container
from azents.core.config import Config
from azents.services.external_channel.ingress_observability import (
    ExternalChannelIngressObservabilityService,
)

app = typer.Typer(help="Inspect active External Channel ingress state")


@app.command("status")
def status(
    limit: Annotated[
        int,
        typer.Option(min=1, max=1000, help="Maximum active items to return"),
    ] = 200,
) -> None:
    """Print one sanitized active-ingress JSON snapshot."""

    async def main() -> None:
        config = Config.from_env()
        configure_logging_for_runtime(
            runtime_env=config.runtime_env,
            inhouse_name="azents",
            sentry_dsn=config.sentry_dsn,
        )
        async with run_with_container(config) as container:
            service = await container.solve(ExternalChannelIngressObservabilityService)
            observation = await service.observe(limit=limit)
        typer.echo(json.dumps(observation.model_dump(mode="json"), sort_keys=True))

    asyncio.run(main())


if __name__ == "__main__":
    app()
