"""Database dependency injection."""

from contextlib import asynccontextmanager
from typing import (
    Annotated,
    Any,
    AsyncGenerator,
    AsyncIterator,
    Callable,
)

import boto3
from fastapi import Depends
from mypy_boto3_rds import RDSClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.core.config import Config, PostgreSQLConfig
from azents.core.deps import get_appctx
from azents.utils.appctx import AppContext

from .session import SessionManager

#: Function type for creating IAM auth tokens.
IAMTokenGenerator = Callable[[], str]


def _create_iam_token_generator(
    db_config: PostgreSQLConfig, rds_client: "RDSClient"
) -> IAMTokenGenerator:
    """Return a function that creates RDS IAM auth tokens."""

    def generate() -> str:
        token: str = rds_client.generate_db_auth_token(
            DBHostname=db_config.host,
            Port=db_config.port,
            DBUsername=db_config.user,
            Region=db_config.region,
        )
        return token

    return generate


def _create_engine_with_iam_auth(
    db_config: PostgreSQLConfig,
    token_generator: IAMTokenGenerator,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Create an AsyncEngine that uses IAM authentication."""
    engine = create_async_engine(
        db_config.get_sqlalchemy_uri(),
        connect_args={"sslmode": db_config.ssl_mode},
        echo=echo,
        pool_pre_ping=True,
    )

    # Dynamically inject the IAM token when opening each connection.
    @event.listens_for(engine.sync_engine, "do_connect")
    def _provide_token(  # pyright: ignore[reportUnusedFunction]
        # listens_for requires any
        dialect: Any,  # noqa: ANN401
        conn_rec: Any,  # noqa: ANN401
        cargs: Any,  # noqa: ANN401
        cparams: dict[str, Any],
    ) -> None:
        cparams["password"] = token_generator()

    return engine


def _create_engine_with_password(
    db_config: PostgreSQLConfig,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Create an AsyncEngine that uses password authentication."""
    return create_async_engine(
        db_config.get_sqlalchemy_uri(with_password=True),
        connect_args={"sslmode": db_config.ssl_mode},
        echo=echo,
        pool_pre_ping=True,
    )


async def get_engine(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> AsyncEngine:
    """AsyncEngine dependency stored in AppContext."""

    async def get_engine_variable() -> AsyncIterator[AsyncEngine]:
        db_config = appctx.config.rdb
        echo = db_config.verbose

        if db_config.use_iam_auth:
            rds_client: RDSClient = boto3.client("rds", region_name=db_config.region)
            token_generator = _create_iam_token_generator(db_config, rds_client)
            engine = _create_engine_with_iam_auth(db_config, token_generator, echo=echo)
        else:
            engine = _create_engine_with_password(db_config, echo=echo)

        try:
            yield engine
        finally:
            await engine.dispose()

    return await appctx.get_variable(f"{__name__}.get_engine", get_engine_variable)


async def get_session_manager(
    engine: Annotated[AsyncEngine, Depends(get_engine)],
) -> SessionManager[AsyncSession]:
    """SessionManager dependency."""

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    return session_manager
