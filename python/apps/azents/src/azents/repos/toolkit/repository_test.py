"""Toolkit repository tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.toolkit import RDBToolkitConfig

from . import ToolkitRepository
from .data import ToolkitCreate, ToolkitUpdate


class _StopAfterWrite(Exception):
    """Stop a repository write after its mapped statement is observable."""


class _Credentials(BaseModel):
    """Test toolkit credentials."""

    token: str


def _toolkit_create() -> ToolkitCreate:
    """Build a complete Toolkit repository create input."""
    return ToolkitCreate(
        workspace_id="workspace-1",
        toolkit_type="mcp",
        slug="toolkit",
        name="Toolkit",
        config={},
    )


async def test_create_initializes_revision_to_one() -> None:
    """Map the initial persisted source revision on creation."""
    session = AsyncMock(spec=AsyncSession)
    session.flush.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await ToolkitRepository().create(session, _toolkit_create())

    toolkit = session.add.call_args.args[0]
    assert isinstance(toolkit, RDBToolkitConfig)
    assert toolkit.revision == 1


async def test_update_increments_revision_once() -> None:
    """Increment persisted source revision once for a config update."""
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await ToolkitRepository().update_by_id(
            session,
            "toolkit-1",
            ToolkitUpdate(config={"url": "https://example.test"}),
        )

    statement = session.execute.call_args.args[0]
    compiled = statement.compile()
    assert compiled.params["revision_1"] == 1
    assert compiled.params["config"] == {"url": "https://example.test"}


async def test_update_credentials_increments_revision_once() -> None:
    """Increment persisted source revision once for a credential update."""
    session = AsyncMock(spec=AsyncSession)
    cipher = MagicMock()
    cipher.encrypt.return_value = "encrypted"

    await ToolkitRepository(cipher=cipher).update_credentials(
        session,
        "toolkit-1",
        _Credentials(token="secret"),
    )

    statement = session.execute.call_args.args[0]
    compiled = statement.compile()
    assert compiled.params["revision_1"] == 1
    assert compiled.params["encrypted_credentials"] == "encrypted"
