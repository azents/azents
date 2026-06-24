"""Periodic scheduler CLI."""

import asyncio
import datetime
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Annotated, TypeVar

import typer
from azcommon.logging import configure_logging_for_runtime

from azents.app import run_with_container
from azents.core.config import Config
from azents.scheduler.service import SchedulerService

logger = logging.getLogger(__name__)

app = typer.Typer(help="Azents periodic scheduler")
T = TypeVar("T")


async def _with_scheduler(callback: Callable[[SchedulerService], Awaitable[T]]) -> T:
    config = Config.from_env()
    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
        sentry_dsn=config.sentry_dsn,
    )
    async with run_with_container(config) as container:
        scheduler = await container.solve(SchedulerService)
        return await callback(scheduler)


@app.command("run")
def run_scheduler() -> None:
    """Run scheduler loop."""

    async def main() -> None:
        config = Config.from_env()
        configure_logging_for_runtime(
            runtime_env=config.runtime_env,
            inhouse_name="azents",
            sentry_dsn=config.sentry_dsn,
        )
        shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _on_shutdown(sig: signal.Signals) -> None:
            logger.info("Received shutdown signal", extra={"signal": sig.name})
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_shutdown, sig)
        async with run_with_container(config) as container:
            scheduler = await container.solve(SchedulerService)
            await scheduler.run(shutdown_event=shutdown_event)

    asyncio.run(main())


@app.command("list")
def list_tasks() -> None:
    """List scheduler task states."""

    async def main() -> None:
        async def callback(scheduler: SchedulerService) -> None:
            states = await scheduler.list_states()
            for state in states:
                typer.echo(
                    f"{state.task_key}\t{state.latest_status.value}\t"
                    f"next={state.next_run_at.isoformat()}\t"
                    f"last_success={_format_dt(state.last_succeeded_at)}\t"
                    f"last_error={state.latest_error_code or '-'}"
                )

        await _with_scheduler(callback)

    asyncio.run(main())


@app.command("status")
def show_status(task_key: str) -> None:
    """Show one scheduler task state."""

    async def main() -> None:
        async def callback(scheduler: SchedulerService) -> None:
            state = await scheduler.get_state(task_key)
            if state is None:
                raise typer.BadParameter(f"Unknown task key: {task_key}")
            typer.echo(f"task_key: {state.task_key}")
            typer.echo(f"status: {state.latest_status.value}")
            typer.echo(f"next_run_at: {state.next_run_at.isoformat()}")
            typer.echo(f"last_started_at: {_format_dt(state.last_started_at)}")
            typer.echo(f"last_succeeded_at: {_format_dt(state.last_succeeded_at)}")
            typer.echo(f"last_failed_at: {_format_dt(state.last_failed_at)}")
            typer.echo(f"failure_streak: {state.failure_streak}")
            typer.echo(f"latest_error_code: {state.latest_error_code or '-'}")
            typer.echo(f"latest_error_message: {state.latest_error_message or '-'}")
            typer.echo(f"lease_owner: {state.lease_owner or '-'}")
            typer.echo(f"lease_until: {_format_dt(state.lease_until)}")
            typer.echo(f"manual_requested_at: {_format_dt(state.manual_requested_at)}")

        await _with_scheduler(callback)

    asyncio.run(main())


@app.command("trigger")
def trigger(
    task_key: Annotated[str, typer.Argument(help="Task key to trigger")],
) -> None:
    """Request manual execution for a scheduler task."""

    async def main() -> None:
        async def callback(scheduler: SchedulerService) -> None:
            state = await scheduler.trigger(task_key)
            if state is None:
                raise typer.BadParameter(f"Unknown task key: {task_key}")
            typer.echo(f"triggered: {task_key}")
            typer.echo(f"next_run_at: {state.next_run_at.isoformat()}")

        await _with_scheduler(callback)

    asyncio.run(main())


def _format_dt(value: datetime.datetime | None) -> str:
    if value is None:
        return "-"
    return value.isoformat()


if __name__ == "__main__":
    app()
