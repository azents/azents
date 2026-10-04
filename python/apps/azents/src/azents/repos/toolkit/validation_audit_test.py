"""Duplicate Scope/attachment persistence contracts without opening a database."""

from collections.abc import Sequence

import psycopg
import sqlalchemy as sa
from azcommon.result import Failure
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ToolkitScopeType
from azents.core.toolkit_errors import DuplicateAgentToolkit, DuplicateScope
from azents.rdb.models.toolkit import RDBAgentToolkit, RDBToolkitScope
from azents.rdb.session_capabilities import ReadWriteSession
from azents.repos.toolkit import AgentToolkitRepository, ToolkitScopeRepository
from azents.repos.toolkit.data import AgentToolkitCreate, ToolkitScopeCreate


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


async def test_duplicate_scope_uses_declared_constraint_and_rolls_back() -> None:
    constraint = RDBToolkitScope.UQ_TOOLKIT_SCOPE
    assert list(constraint.columns.keys()) == ["toolkit_id", "scope_type", "scope_id"]
    async with _DuplicateSession(constraint) as session:
        result = await ToolkitScopeRepository().create(
            ReadWriteSession(session),
            ToolkitScopeCreate(
                toolkit_id="toolkit-1",
                scope_type=ToolkitScopeType.WORKSPACE,
                scope_id="workspace-1",
            ),
        )
        assert result == Failure(
            DuplicateScope(
                toolkit_id="toolkit-1",
                scope_type=ToolkitScopeType.WORKSPACE,
                scope_id="workspace-1",
            )
        )
        assert session.rolled_back


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
