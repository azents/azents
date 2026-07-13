"""System administrator operator CLI."""

import asyncio
from typing import Annotated

import typer
from azcommon.logging import configure_logging_for_runtime
from azcommon.result import Failure, Success

from azents.app import run_with_container
from azents.core.config import Config
from azents.core.enums import SystemUserRole
from azents.repos.system_user_role.data import SystemUserNotFound
from azents.services.system_user_role.service import SystemUserRoleService

app = typer.Typer(help="Manage Azents instance system administrators")


@app.callback()
def main() -> None:
    """Manage instance system administrator assignments."""


@app.command("grant")
def grant_system_admin(
    email: Annotated[
        str,
        typer.Option("--email", help="Exact email of an existing Azents User"),
    ],
) -> None:
    """Grant system administrator authority to an existing User by exact email."""

    async def main() -> None:
        config = Config.from_env()
        configure_logging_for_runtime(
            runtime_env=config.runtime_env,
            inhouse_name="azents",
            sentry_dsn=config.sentry_dsn,
        )
        async with run_with_container(config) as container:
            service = await container.solve(SystemUserRoleService)
            result = await service.grant_by_email(
                email,
                SystemUserRole.SYSTEM_ADMIN,
                source="operator_cli",
            )
        match result:
            case Success(assignment):
                typer.echo(f"user_id: {assignment.user_id}")
                typer.echo(f"role: {assignment.role.value}")
                typer.echo("System administrator grant completed.")
            case Failure(SystemUserNotFound()):
                raise typer.BadParameter(
                    "No existing User matches the exact email."
                ) from None

    asyncio.run(main())


if __name__ == "__main__":
    app()
