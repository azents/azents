"""ExchangeFileRepository tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from . import ExchangeFileRepository


async def test_detach_source_user_id_clears_retained_provenance() -> None:
    """Detach one deleted User from retained ExchangeFile provenance."""
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=4))
    session.flush = AsyncMock()

    detached = await ExchangeFileRepository().detach_source_user_id(
        session,
        source_user_id="user-1",
    )

    assert detached == 4
    statement = session.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "exchange_files" in sql
    assert "source_user_id" in sql
    session.flush.assert_awaited_once()
