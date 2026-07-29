"""Operator CLI for the guarded External Channel cutover."""

import asyncio
from collections.abc import Awaitable, Callable

import typer
from azcommon.logging import configure_logging_for_runtime

from azents.app import run_with_container
from azents.core.config import Config
from azents.services.external_channel.cutover_preflight import (
    ExternalChannelCutoverPreflightReport,
    ExternalChannelCutoverPreflightService,
)

app = typer.Typer(
    help=(
        "Inspect aggregate PostgreSQL state before the coordinated External "
        "Channel synchronous-ingress cutover."
    )
)


@app.callback()
def main() -> None:
    """Run an explicit External Channel cutover operator command."""


async def _with_service(
    callback: Callable[[ExternalChannelCutoverPreflightService], Awaitable[None]],
) -> None:
    """Run one operator callback with the application dependency container."""
    config = Config.from_env()
    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
        sentry_dsn=config.sentry_dsn,
    )
    async with run_with_container(config) as container:
        service = await container.solve(ExternalChannelCutoverPreflightService)
        await callback(service)


@app.command("preflight")
def preflight() -> None:
    """Report aggregate cutover invariants and fail when any remain."""

    async def main(service: ExternalChannelCutoverPreflightService) -> None:
        report = await service.preflight()
        _echo_report(report)
        if not report.ready:
            typer.echo("preflight_blocked: invariant_failures")
            raise typer.Exit(code=2)

    asyncio.run(_with_service(main))


def _echo_report(report: ExternalChannelCutoverPreflightReport) -> None:
    """Print only stable category counts and the aggregate gate result."""
    for category, count in report.category_counts:
        typer.echo(f"category.{category}: {count}")
    typer.echo(f"preflight_ready: {str(report.ready).lower()}")


if __name__ == "__main__":
    app()
