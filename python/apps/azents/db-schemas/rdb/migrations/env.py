"""Alembic environment settings."""

import asyncio
import importlib
import pkgutil
from logging.config import fileConfig

# alembic_postgresql_enum supports automatic PostgreSQL enum management.
import alembic_postgresql_enum  # noqa: F401  # pyright: ignore[reportUnusedImport]
import boto3
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from azents.core.config import Config
from azents.rdb.models.base import RDBModel


def import_db_models(source: str) -> None:
    """Import all models from packages and subpackages."""

    def _collect_from_package(pkg_name: str) -> None:
        package = importlib.import_module(pkg_name)
        for _, module_name, is_pkg in pkgutil.iter_modules(
            package.__path__, pkg_name + "."
        ):
            importlib.import_module(module_name)
            if is_pkg:
                _collect_from_package(module_name)

    _collect_from_package(source)


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = RDBModel.metadata

# Model imports
import_db_models("azents.rdb.models")

if not config.get_main_option("sqlalchemy.url"):
    # Application config
    app_config = Config.from_env()

    # IAM authentication requires a boto3 client
    rds_client = None
    if app_config.rdb.use_iam_auth:
        rds_client = boto3.client("rds", region_name=app_config.rdb.region)

    config.set_main_option(
        "sqlalchemy.url",
        app_config.rdb.get_sqlalchemy_uri(
            with_password=True, rds_client=rds_client
        ).replace(
            "%",
            "%%",
        ),  # Escape for Alembic's own formatting
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
