"""Availability and duplicate attachment contracts without opening a database."""

from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock

import psycopg
import sqlalchemy as sa
from azcommon.result import Failure
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.toolkit_errors import DuplicateAgentToolkit
from azents.rdb.models.toolkit import RDBAgentToolkit
from azents.rdb.session_capabilities import ReadWriteSession
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.repos.toolkit.data import AgentToolkitCreate


class _DuplicateSession(AsyncSession):
    """Map objects in memory, then expose the driver's real duplicate diagnostic."""

    def __init__(self, constraint: sa.UniqueConstraint) -> None:
        super().__init__(expire_on_commit=False)
        name = constraint.name
        assert isinstance(name, str)
        self.failure = IntegrityError(
            "fixture duplicate",
            {},
            psycopg.errors.UniqueViolation("duplicate", info={ord("n"): name.encode()}),
        )
        self.rolled_back = False

    async def flush(self, objects: Sequence[object] | None = None) -> None:
        """Mirror AsyncSession's optional flush selector without issuing SQL."""
        raise self.failure

    async def rollback(self) -> None:
        self.rolled_back = True
        await super().rollback()


async def test_duplicate_attachment_uses_declared_constraint_and_rolls_back() -> None:
    constraint = RDBAgentToolkit.UQ_AGENT_TOOLKIT
    assert list(constraint.columns.keys()) == ["agent_id", "toolkit_id"]
    async with _DuplicateSession(constraint) as session:
        result = await AgentToolkitRepository().create(
            ReadWriteSession(session),
            AgentToolkitCreate(
                agent_id="agent-1", toolkit_id="toolkit-1", toolkit_type="mcp"
            ),
        )
        assert result == Failure(
            DuplicateAgentToolkit(agent_id="agent-1", toolkit_id="toolkit-1")
        )
        assert session.rolled_back


async def test_available_query_preserves_workspace_member_eligibility() -> None:
    """Use canonical ownership and membership without a visibility-table join."""
    session = AsyncMock(spec=AsyncSession)
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    session.execute.return_value = empty_result

    result = await ToolkitRepository().list_available_for_workspace_user(
        ReadWriteSession(session),
        workspace_id="workspace-1",
        user_id="member-1",
    )

    assert result == []
    session.execute.assert_awaited_once()
    call = session.execute.await_args
    assert call is not None
    statement = call.args[0]
    assert isinstance(statement, sa.sql.Select)
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "EXISTS (SELECT workspace_users.id" in sql
    assert "workspace_users.user_id =" in sql
    assert "workspace_users.workspace_id =" in sql
    assert "toolkit_configs.workspace_id =" in sql
    assert "toolkit_configs.enabled = true" in sql
    assert "toolkit_configs.owner_agent_id IS NULL" in sql
    assert "JOIN" not in sql
    assert "DISTINCT" not in sql
    assert compiled.params is not None
    assert set(compiled.params.values()) == {"workspace-1", "member-1"}
