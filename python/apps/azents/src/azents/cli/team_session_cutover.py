"""Operator CLI for the Team Session coordinated cutover."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

import typer
from azcommon.logging import configure_logging_for_runtime

from azents.app import run_with_container
from azents.core.config import Config
from azents.services.team_session_cutover_replay import (
    TeamSessionCutoverReplayInvariantFailure,
    TeamSessionCutoverReplayReport,
    TeamSessionCutoverReplayService,
)

app = typer.Typer(
    help=(
        "Preflight and replay Team Session durable work during the coordinated "
        "cutover. Replay purges broker state and sends routing-only wake-ups."
    )
)


async def _with_service(
    callback: Callable[[TeamSessionCutoverReplayService], Awaitable[None]],
) -> None:
    """Run one operator callback with the application dependency container."""
    config = Config.from_env()
    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
        sentry_dsn=config.sentry_dsn,
    )
    async with run_with_container(config) as container:
        service = await container.solve(TeamSessionCutoverReplayService)
        await callback(service)


@app.command("preflight")
def preflight(
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            min=1,
            max=500,
            help="Maximum Sessions to inspect in one bounded batch.",
        ),
    ] = 100,
    after_session_id: Annotated[
        str | None,
        typer.Option(
            "--after-session-id",
            help="Exclusive Session ID cursor from the prior bounded batch.",
        ),
    ] = None,
) -> None:
    """Report durable replay work and fail when invariants are unresolved."""

    async def main(service: TeamSessionCutoverReplayService) -> None:
        report = await service.preflight(
            batch_size=batch_size,
            after_session_id=after_session_id,
        )
        _echo_report(report)
        if report.invariant_failures:
            typer.echo("preflight_blocked: invariant_failures")
            raise typer.Exit(code=2)

    asyncio.run(_with_service(main))


@app.command("replay")
def replay(
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help="Confirm broker-state discard and pure wake-up emission.",
        ),
    ] = False,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            min=1,
            max=500,
            help="Maximum Sessions to replay in one bounded batch.",
        ),
    ] = 100,
    after_session_id: Annotated[
        str | None,
        typer.Option(
            "--after-session-id",
            help="Exclusive Session ID cursor from the prior bounded batch.",
        ),
    ] = None,
) -> None:
    """Discard broker state and send pure wake-ups for a valid durable batch."""
    if not execute:
        raise typer.BadParameter("Replay requires --execute.")

    async def main(service: TeamSessionCutoverReplayService) -> None:
        try:
            report = await service.replay(
                batch_size=batch_size,
                after_session_id=after_session_id,
            )
        except TeamSessionCutoverReplayInvariantFailure as exc:
            typer.echo("replay_blocked: invariant_failures")
            for code, count in exc.invariant_failures:
                typer.echo(f"invariant_failure.{code}: {count}")
            raise typer.Exit(code=2) from None
        _echo_report(report)

    asyncio.run(_with_service(main))


def _echo_report(report: TeamSessionCutoverReplayReport) -> None:
    """Print only bounded, content-free cutover report fields."""
    typer.echo(f"scanned_sessions: {report.scanned_sessions}")
    typer.echo(f"valid_sessions: {report.valid_sessions}")
    typer.echo(f"replayed_sessions: {report.replayed_sessions}")
    typer.echo(f"pending_input_sessions: {report.pending_input_sessions}")
    typer.echo(f"pending_command_sessions: {report.pending_command_sessions}")
    typer.echo(f"recoverable_run_sessions: {report.recoverable_run_sessions}")
    typer.echo(
        "pending_idle_continuation_sessions: "
        f"{report.pending_idle_continuation_sessions}"
    )
    typer.echo(f"stop_request_sessions: {report.stop_request_sessions}")
    for code, count in report.invariant_failures:
        typer.echo(f"invariant_failure.{code}: {count}")
    cursor = report.next_session_cursor or "-"
    typer.echo(f"next_session_cursor: {cursor}")


if __name__ == "__main__":
    app()
