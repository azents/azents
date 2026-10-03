"""Explicit offline Memory handover CLI requiring operator coordination."""

import asyncio
import dataclasses
import json
from typing import Annotated

import typer
from azcommon.logging import configure_logging_for_runtime

from azents.core.config import Config
from azents.core.historical_memory_cutover import (
    MemoryHandoverAction,
    MemoryHandoverRequest,
)
from azents.process_lifecycle import run_with_container
from azents.services.historical_memory.cutover import MemoryHandoverService

app = typer.Typer(
    help="Reset automatic Memory state during a coordinated offline handover."
)


@app.command()
def handover(
    action: Annotated[
        MemoryHandoverAction,
        typer.Argument(
            help="forward, rollback, or reactivate after any old-code interval"
        ),
    ],
    execution_quiesced: Annotated[
        bool,
        typer.Option(
            "--confirm-execution-quiesced",
            help=(
                "Assert API/gateway/scheduler/job and Engine admission is paused, "
                "workers drained/stopped, and old processes cannot resume"
            ),
        ),
    ] = False,
    batch_size: Annotated[int, typer.Option(min=1, max=100)] = 50,
) -> None:
    """Preserve Saved/source data and Run history; never deploy or start workers."""
    request = MemoryHandoverRequest(action, execution_quiesced, batch_size)
    try:
        request.validate()
    except ValueError as error:
        raise typer.BadParameter(str(error)) from None

    async def main() -> None:
        config = Config.from_env()
        configure_logging_for_runtime(
            runtime_env=config.runtime_env,
            inhouse_name="azents",
            sentry_dsn=config.sentry_dsn,
        )
        async with run_with_container(config) as container:
            service = await container.solve(MemoryHandoverService)
            result = await service.handover(request)
        typer.echo(json.dumps(dataclasses.asdict(result), sort_keys=True))

    asyncio.run(main())


if __name__ == "__main__":
    app()
