"""Archived-session retention schema tests."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from azents.rdb.models.archived_session_retention import (
    RDBArchivedSessionRetentionApplication,
)


def test_active_application_index_uses_postgresql_expression_syntax() -> None:
    """Compile the singleton active-application index with double parentheses."""
    compiled = str(
        CreateIndex(RDBArchivedSessionRetentionApplication.UQ_ACTIVE).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "archived_session_retention_applications ((1))" in compiled
