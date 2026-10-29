"""Trusted server-side inference credential operator CLI."""

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

import typer
from azcommon.logging import configure_logging_for_runtime
from azents_llm_contract.authority import Identifier, IssuedToken
from pydantic import TypeAdapter, ValidationError

from azents.core.config import Config
from azents.core.llm_access import LLMAccessDenied, LLMTokenConflict, SupplyState
from azents.process_lifecycle import run_with_container
from azents.services.llm_access import LLMAccessService

app = typer.Typer(
    help="Manage inference credentials using trusted server configuration",
    pretty_exceptions_enable=False,
)
OperationResult = IssuedToken | SupplyState | None
Operation = Callable[[LLMAccessService], Awaitable[OperationResult]]


def validate_identifiers(*values: str) -> None:
    """Apply the same identifier bounds as the Admin contract."""
    try:
        for value in values:
            TypeAdapter(Identifier).validate_python(value)
    except ValidationError:
        raise typer.BadParameter(
            "Identifiers must contain 1 to 256 characters."
        ) from None


def write_credential(descriptor: int, output: Path, result: IssuedToken) -> None:
    """Publish only to the reserved private file before reporting success."""
    try:
        with os.fdopen(os.dup(descriptor), "w", encoding="utf-8") as stream:
            stream.write(result.protected_json())
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        parent = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except OSError:
        typer.echo(
            "Credential output failed; inspect supply state before retrying issuance.",
            err=True,
        )
        raise typer.Exit(1) from None


def execute(operation: Operation, *, output: Path | None) -> None:
    """Run once; reserve secret output before any authority mutation."""
    descriptor: int | None = None
    if output is not None:
        try:
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            raise typer.BadParameter(
                "Secret output must be a new writable file; nothing was issued."
            ) from None

    async def run() -> None:
        config = Config.from_env()
        configure_logging_for_runtime(
            runtime_env=config.runtime_env,
            inhouse_name="azents",
            sentry_dsn=config.sentry_dsn,
        )
        async with run_with_container(config) as container:
            service = await container.solve(LLMAccessService)
            result = await operation(service)
            if isinstance(result, IssuedToken):
                if descriptor is None or output is None:
                    raise RuntimeError("Credential issuance requires secret output.")
                write_credential(descriptor, output, result)
                typer.echo(result.model_dump_json(exclude={"agent_token"}))
            elif isinstance(result, SupplyState):
                typer.echo(TypeAdapter(SupplyState).dump_json(result).decode())
            else:
                typer.echo("Inference credential revocation completed.")

    try:
        asyncio.run(run())
    except LLMAccessDenied:
        typer.echo("Inference authority is unavailable for this operation.", err=True)
        raise typer.Exit(1) from None
    except LLMTokenConflict:
        typer.echo("Supply state changed; inspect before replacing.", err=True)
        raise typer.Exit(1) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


@app.callback()
def main() -> None:
    """Use local server/DB authority, like the system_admin operator CLI."""


@app.command("issue")
def issue(
    agent_id: Annotated[str, typer.Option(help="Exact Agent ID")],
    subject: Annotated[str, typer.Option(help="Distinct supply subject")],
    output: Annotated[Path, typer.Option(help="New private JSON credential file")],
) -> None:
    """Issue one supply token; the raw credential is written only to --output."""
    validate_identifiers(agent_id, subject)
    execute(
        lambda service: service.issue(
            agent_id=agent_id, subject=subject, issuer="operator_cli"
        ),
        output=output,
    )


@app.command("rotate")
def rotate(
    supply_id: Annotated[str, typer.Option(help="Exact supply ID")],
    expected_token_id: Annotated[str, typer.Option(help="Expected current token ID")],
    output: Annotated[Path, typer.Option(help="New private JSON credential file")],
) -> None:
    """Replace once with the existing expected-token and overlap rules."""
    validate_identifiers(supply_id, expected_token_id)
    execute(
        lambda service: service.rotate(
            supply_id=supply_id, expected_token_id=expected_token_id
        ),
        output=output,
    )


@app.command("inspect")
def inspect_supply(
    supply_id: Annotated[str, typer.Option(help="Exact supply ID")],
) -> None:
    """Print nonsecret state, including after uncertain output delivery."""
    validate_identifiers(supply_id)
    execute(lambda service: service.inspect(supply_id=supply_id), output=None)


@app.command("lookup")
def lookup(
    agent_id: Annotated[str, typer.Option(help="Exact Agent ID")],
    subject: Annotated[str, typer.Option(help="Exact supply subject")],
) -> None:
    """Locate nonsecret state without issuing or recovering a raw token."""
    validate_identifiers(agent_id, subject)
    execute(
        lambda service: service.inspect_subject(agent_id=agent_id, subject=subject),
        output=None,
    )


@app.command("revoke")
def revoke(
    supply_id: Annotated[str, typer.Option(help="Exact supply ID")],
    token_id: Annotated[
        str | None,
        typer.Option(help="Revoke only this token; omission revokes the supply"),
    ] = None,
) -> None:
    """Revoke a test token or its whole supply without affecting other supplies."""
    validate_identifiers(supply_id)
    if token_id is not None:
        validate_identifiers(token_id)
    execute(
        lambda service: service.revoke(supply_id=supply_id, token_id=token_id),
        output=None,
    )


if __name__ == "__main__":
    app()
