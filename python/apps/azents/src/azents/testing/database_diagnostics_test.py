"""Database fixture diagnostics remain available through standard logging."""

import logging

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_shared_test_engine_retains_opt_in_sql_diagnostics(
    rdb_engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """Request real SQL diagnostics without forcing echo output for every test."""
    with caplog.at_level(logging.INFO, logger="sqlalchemy.engine.Engine"):
        async with rdb_engine.connect() as connection:
            result = await connection.execute(sa.text("SELECT 1"))
            assert result.scalar_one() == 1
    assert any(
        record.name == "sqlalchemy.engine.Engine" and record.getMessage() == "SELECT 1"
        for record in caplog.records
    )
