from unittest.mock import Mock

import psycopg.errors
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError

from azcommon.sqlalchemy.postgres import is_constrained_by


class TestIsConstrainedBy:
    """Test is_constrained_by function."""

    def test_with_string_constraint_name_matching(self) -> None:
        """Test when constraint name matches as string."""
        diag = Mock()
        diag.constraint_name = "unique_email"

        psycopg_error = Mock(spec=psycopg.errors.UniqueViolation)
        psycopg_error.diag = diag

        sa_error = IntegrityError(
            statement="INSERT INTO users...",
            params={},
            orig=psycopg_error,
        )

        assert is_constrained_by(sa_error, "unique_email") is True

    def test_with_unique_constraint_object(self) -> None:
        """Test when UniqueConstraint object's name matches."""
        diag = Mock()
        diag.constraint_name = "unique_email"

        psycopg_error = Mock(spec=psycopg.errors.UniqueViolation)
        psycopg_error.diag = diag

        sa_error = IntegrityError(
            statement="INSERT INTO users...",
            params={},
            orig=psycopg_error,
        )

        constraint = UniqueConstraint(name="unique_email")

        assert is_constrained_by(sa_error, constraint) is True
