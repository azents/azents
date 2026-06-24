"""Azents interactive shell.

Starts a REPL with the DI container, DB session, and models preloaded. Use
``-c`` to execute a command non-interactively.
"""

import asyncio
import dataclasses
import importlib
import os
import pkgutil
import sys
import textwrap
from contextlib import AsyncExitStack
from types import ModuleType
from typing import Any, Dict, Type, TypeVar

import sqlalchemy as sa
import typer
from azcommon.di import Container
from azcommon.logging import configure_logging_for_runtime
from dotenv import load_dotenv
from ptpython.repl import embed
from sqlalchemy.ext.asyncio import AsyncSession

from azents.app import run_with_container
from azents.core.config import Config, Settings
from azents.rdb.deps import get_session_manager
from azents.rdb.models.base import RDBModel

load_dotenv()

T = TypeVar("T")


@dataclasses.dataclass(slots=True)
class Variable:
    """Variable exposed to the shell."""

    name: str
    value: Any  # noqa: ANN401
    description: str


def collect_db_models(module_name: str, source: str, base_class: Type[T]) -> ModuleType:
    """Collect subclasses of ``base_class`` from a package and return a module."""
    models_module = ModuleType(module_name)
    collected_models: Dict[str, Type[T]] = {}

    def _collect_from_package(pkg_name: str) -> None:
        package = importlib.import_module(pkg_name)
        for _, mod_name, is_pkg in pkgutil.iter_modules(
            package.__path__, pkg_name + "."
        ):
            module = importlib.import_module(mod_name)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, base_class)
                    and attr is not base_class
                ):
                    collected_models[attr_name] = attr
            if is_pkg:
                _collect_from_package(mod_name)

    _collect_from_package(source)
    for name, model in collected_models.items():
        setattr(models_module, name, model)
    return models_module


async def _build_variables(
    config: Config,
    container: Container,
    session: AsyncSession,
) -> list[Variable]:
    """Configure the variable list used by the shell."""
    return [
        Variable(
            name="config",
            value=config,
            description="Application configuration",
        ),
        Variable(
            name="container",
            value=container,
            description="Dependency injection container",
        ),
        Variable(
            name="session",
            value=session,
            description="SQLAlchemy session",
        ),
        Variable(
            name="models",
            value=collect_db_models(
                "models",
                "azents.rdb.models",
                RDBModel,
            ),
            description="SQLAlchemy models",
        ),
        Variable(
            name="sa",
            value=sa,
            description="Alias for sqlalchemy module",
        ),
    ]


async def run(command: str | None = None) -> None:
    """Shell main logic."""
    settings = Settings()  # pyright: ignore[reportCallIssue] # pydantic-settings
    config = Config.from_settings(settings)
    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
    )
    async with run_with_container(config) as container, AsyncExitStack() as stack:
        session_cm = await container.solve(get_session_manager)
        session = await stack.enter_async_context(session_cm())
        variables = await _build_variables(config, container, session)
        locals_dict = {var.name: var.value for var in variables}

        if command is not None:
            # Wrap the command in an async function so await can be used.
            wrapped = (
                "async def __shell_exec__():\n"
                + textwrap.indent(command, "    ")
                + "\n"
            )
            exec(compile(wrapped, "<string>", "exec"), locals_dict)  # noqa: S102 — development-only CLI shell command
            await locals_dict["__shell_exec__"]()
            return

        variable_description = "\n".join(
            textwrap.dedent(
                f"""
                - {var.name}: {var.description}
                """
            ).strip()
            for var in variables
        )

        typer.echo(
            textwrap.dedent(
                """
                Azents Shell
                ==============

                Following variables are available:

                """
            )
            + variable_description
            + "\n"
        )
        await embed(
            title="Azents REPL",
            locals=locals_dict,
            return_asyncio_coroutine=True,
        )


def main(
    command: str | None = typer.Option(None, "-c", help="Execute command and exit"),
) -> None:
    """Run the interactive shell or execute a command with ``-c``."""
    asyncio.run(run(command))


if not __package__:
    package_source_path = os.path.dirname(os.path.dirname(__file__))
    sys.path.insert(0, package_source_path)

if __name__ == "__main__":
    typer.run(main)
